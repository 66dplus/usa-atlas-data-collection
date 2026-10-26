"""Load validated candidate JSONL only into a guarded disposable review database."""
import argparse
import hashlib
import json
import pathlib
import re
import sys
import uuid

import psycopg2
from psycopg2.extras import execute_values

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "full" / "politics_20261026"))
from prepare import BOUNDARY_SOURCE_URL

GUARD_ROOT = pathlib.Path("/tmp/usa-maps-data-flow-20261026").resolve()
SOCKET = str((GUARD_ROOT / "pgsocket").resolve())
SOURCE_METADATA = {
    "01.04": {"label":"AIAN alone or in combination share", "rate":"acs_acs5"},
    "12.01": {"label":"President election results", "rate":"medsl"},
    "12.02": {"label":"Senate election results", "rate":"medsl"},
    "12.03": {"label":"House election results", "rate":"medsl"},
}


def sha256(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def guard(config_path):
    config_path=pathlib.Path(config_path).resolve()
    if GUARD_ROOT not in config_path.parents:
        raise ValueError("guard config must be under the approved /tmp task directory")
    config=json.loads(config_path.read_text())
    if str(pathlib.Path(config.get("host","")).resolve()) != SOCKET or int(config.get("port",0)) != 55446 or config.get("user") != "atlas":
        raise ValueError("database target is not the approved temporary PostgreSQL local socket")
    dbname=config.get("dbname","")
    if dbname == "usa_atlas" or not re.fullmatch(r"reader_v2_worker_[a-z0-9_]{6,50}",dbname):
        raise ValueError("database name must be a unique reader_v2_worker_* disposable database")
    return config


def checked_manifest(prepared_dir):
    prepared_dir=pathlib.Path(prepared_dir).resolve()
    if GUARD_ROOT not in prepared_dir.parents:
        raise ValueError("prepared output must be under the approved /tmp task directory")
    manifest_path=prepared_dir/"reader-results.json"
    manifest=json.loads(manifest_path.read_text())
    if manifest.get("candidate_status") != "local_review_not_admitted":
        raise ValueError("prepared manifest is not explicitly marked candidate local review")
    for key,item in manifest.get("outputs",{}).items():
        path=pathlib.Path(item["path"]).resolve()
        if prepared_dir not in path.parents or not path.is_file() or sha256(path)!=item["sha256"]:
            raise ValueError("missing or corrupt prepared output: "+key)
    boundary_path=pathlib.Path(manifest["boundary"]["path"]).resolve()
    feature_path=pathlib.Path(manifest["boundary"]["features_jsonl_path"]).resolve()
    if prepared_dir not in boundary_path.parents or sha256(boundary_path)!=manifest["boundary"]["sha256"]:
        raise ValueError("missing or corrupt prepared congressional geometry")
    if prepared_dir not in feature_path.parents or sha256(feature_path)!=manifest["boundary"]["features_jsonl_sha256"]:
        raise ValueError("missing or corrupt boundary feature JSONL")
    return manifest,manifest_path


def records(path,scope=None):
    with pathlib.Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row=json.loads(line)
            if scope=="2024" and row.get("election_year")!=2024:
                continue
            yield row


def insert_jsonl(cur, path, query, mapper, scope=None):
    batch=[]; count=0
    for row in records(path,scope):
        batch.append(mapper(row))
        if len(batch)>=1000:
            execute_values(cur,query,batch,page_size=1000);count+=len(batch);batch=[]
    if batch:
        execute_values(cur,query,batch,page_size=1000);count+=len(batch)
    return count


def load(args):
    config=guard(args.guard_config)
    manifest,manifest_path=checked_manifest(args.prepared_dir)
    contract_path=ROOT/"database/reader/v2/contract.json"
    input_manifest_sha=sha256(manifest_path)
    contract_sha=sha256(contract_path)
    output_dir=pathlib.Path(args.prepared_dir).resolve()
    connection=psycopg2.connect(host=config["host"],port=config["port"],user=config["user"],dbname=config["dbname"],connect_timeout=3)
    try:
        connection.autocommit=False
        cur=connection.cursor()
        cur.execute("SELECT current_database(),to_regclass('usa_atlas.ingest_run'),to_regclass('usa_atlas.catalog_field')")
        actual,run_rel,catalog_rel=cur.fetchone()
        if actual!=config["dbname"] or run_rel is None or catalog_rel is None:
            raise ValueError("target must already contain the v1 usa_atlas schema")
        migration=(ROOT/"database/reader/v2/schema.sql").read_text()
        cur.execute(migration)
        catalog_contract=json.loads(contract_path.read_text())
        for field,label in (("01.04","AIAN broad share"),("12.01","President election results"),("12.02","Senate election results"),("12.03","House election results")):
            body={"contract_version":catalog_contract["contract_version"],"field_id":field,"dataset_id":label}
            cur.execute("""INSERT INTO usa_atlas.catalog_field
                (catalog_field_id,catalog_label,planned_state,rate_limit_profile,source_release,contract,contract_sha256)
                VALUES (%s,%s,'candidate','local_review','candidate-v2',%s::jsonb,%s)
                ON CONFLICT (catalog_field_id) DO NOTHING""",(field,label,json.dumps(body),contract_sha))
        ingest_id=uuid.uuid4()
        row_count=sum(item["rows"] for item in manifest["outputs"].values())
        cur.execute("""INSERT INTO usa_atlas.ingest_run
            (ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,completed_at,status,error_code)
            VALUES (%s,'candidate_local_review',%s,%s,%s,%s,now(),now(),'pass',NULL)""",
            (str(ingest_id),str(manifest_path),input_manifest_sha,contract_sha,row_count))
        cur.execute("""INSERT INTO usa_atlas.reader_batch
            (ingest_id,contract_version,collector_version,observation_release,candidate_status,input_manifest_sha256)
            VALUES (%s,%s,%s,'multi-source-local-review','local_review',%s)""",
            (str(ingest_id),manifest["reader_contract_version"],manifest["collector_version"],input_manifest_sha))
        counts={}

        observation_sql="""INSERT INTO usa_atlas.reader_observation
        (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,district_code,boundary_vintage,congress_session,is_at_large,period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,source_release,source_url,source_sha256,methodology_note,candidate_status,retrieved_at,ingest_id)
        VALUES %s"""
        counts["reader_observation"]=insert_jsonl(cur,output_dir/"reader_observations.jsonl",observation_sql,lambda r:(r["observation_id"],r["dataset_id"],r["field_id"],r["catalog_field_id"],r["geo_id"],r["geo_type"],r.get("state_fips"),r.get("district_code"),r.get("boundary_vintage"),r.get("congress_session"),r.get("is_at_large",False),r["period_kind"],r["period_year"],r.get("period_month"),r["period_start_year"],r["period_end_year"],r.get("source_period_code"),r.get("value"),r["unit"],r["quality_status"],r["source_value_status"],r["geography_mapping_status"],r.get("raw_estimate"),r.get("raw_estimate_moe"),r.get("raw_denominator"),r.get("raw_denominator_moe"),r.get("denominator_value"),r["source"],r["source_release"],r["source_url"],r["source_sha256"],r["methodology_note"],"local_review",r["retrieved_at"],str(ingest_id)))

        boundary_sql="""INSERT INTO usa_atlas.geography_boundary
        (geo_id,geo_type,state_fips,district_code,congress_session,boundary_vintage,is_at_large,seat_type,label,geometry_json,geometry_source_url,geometry_source_sha256,geometry_record_sha256,source_release,source_status,candidate_status,ingest_id)
        VALUES %s"""
        def boundary_mapper(r):
            feature=r["feature"]
            props=feature["properties"]
            source=manifest["boundary"].get("source",{})
            zipsha=source.get("source_zip_sha256",source.get("trusted_geojson_sha256",manifest["boundary"]["sha256"]))
            return (r["geo_id"],"congressional_district",r["state_fips"],r["district_code"],r["congress_session"],r["boundary_vintage"],r["is_at_large"],"nonvoting_delegate" if r["is_nonvoting"] else "voting_district",str(props.get("NAMELSAD",r["geo_id"])),json.dumps(feature["geometry"]),BOUNDARY_SOURCE_URL,zipsha,r["geometry_sha256"],"census-cb-2024-cd119-500k","candidate_not_admitted","local_review",str(ingest_id))
        counts["geography_boundary"]=insert_jsonl(cur,pathlib.Path(manifest["boundary"]["features_jsonl_path"]),boundary_sql,boundary_mapper)

        contest_sql="""INSERT INTO usa_atlas.election_contest
        (contest_id,dataset_id,field_id,catalog_field_id,office,election_year,election_date,stage,is_special,is_runoff,geography_type,geo_id,state_fips,district_code,boundary_vintage,congress_session,result_mode,reported_total_votes,source_release,source_url,source_sha256,source_version,source_status,production_eligible,quality_status,geography_mapping_status,party_aggregation_status,quarantine_reasons,methodology_note,candidate_status,ingest_id)
        VALUES %s"""
        def contest_mapper(r):
            return (r["contest_id"],r["dataset_id"],r["field_id"],r["catalog_field_id"],r["office"],r["election_year"],None,r["stage"],r["is_special"],r["is_runoff"],r["geography_type"],r["geo_id"],r.get("state_fips"),r.get("district_code"),r.get("boundary_vintage"),r.get("congress_session"),r["result_mode"],r.get("reported_total_votes"),r["source_release"],r["source_url"],r["source_sha256"],r["source_version"],r["source_status"],r["production_eligible"],r["quality_status"],r["geography_mapping_status"],r["party_aggregation_status"],r["quarantine_reasons"],r["methodology_note"],"local_review",str(ingest_id))
        counts["election_contest"]=insert_jsonl(cur,output_dir/"election_contests.jsonl",contest_sql,contest_mapper,"2024")

        candidate_sql="""INSERT INTO usa_atlas.election_candidate
        (contest_id,source_row_id,candidate_id,candidate_label,candidate_kind,party_original,party_normalized,candidatevotes_raw,totalvotes_raw,candidate_votes,source_total_votes,result_mode,write_in,fusion_ticket,source_version,source_url,source_sha256,source_status,quality_status,aggregation_quarantine_reasons,candidate_status,ingest_id)
        VALUES %s"""
        def candidate_mapper(r):
            return (r["contest_id"],r["source_row_id"],None,r["candidate_label"],r["candidate_kind"],r.get("party_original"),r.get("party_normalized"),str(r.get("candidatevotes_raw") or ""),str(r.get("totalvotes_raw") or ""),r.get("candidate_votes"),r.get("source_total_votes"),r["result_mode"],r.get("write_in"),r.get("fusion_ticket"),r["source_version"],r["source_url"],r["source_sha256"],r["source_status"],r["quality_status"],r["aggregation_quarantine_reasons"],"local_review",str(ingest_id))
        counts["election_candidate"]=insert_jsonl(cur,output_dir/"election_candidates.jsonl",candidate_sql,candidate_mapper,"2024")

        party_sql="""INSERT INTO usa_atlas.election_party_result
        (contest_id,party_normalized,party_votes,reported_total_votes,share_all_votes,quality_status,party_aggregation_status,source_release,source_status,production_eligible,candidate_status,ingest_id)
        VALUES %s"""
        def party_mapper(r):
            return (r["contest_id"],r["party_normalized"],r.get("party_votes"),r.get("reported_total_votes"),r.get("share_all_votes"),r["quality_status"],r["party_aggregation_status"],r["source_release"],r["source_status"],r["production_eligible"],"local_review",str(ingest_id))
        counts["election_party_result"]=insert_jsonl(cur,output_dir/"election_party_results.jsonl",party_sql,party_mapper,"2024")

        availability_sql="""INSERT INTO usa_atlas.election_availability
        (field_id,dataset_id,office,election_year,geography_type,geo_id,boundary_vintage,congress_session,stage,is_special,is_runoff,quality_status,source_release,reason,candidate_status,ingest_id)
        VALUES %s"""
        def availability_mapper(r):
            return (r["field_id"],r["dataset_id"],r["office"],r["election_year"],r["geography_type"],r["geo_id"],r.get("boundary_vintage"),r.get("congress_session"),r["stage"],r["is_special"],r["is_runoff"],r["quality_status"],r["source_release"],r["reason"],"local_review",str(ingest_id))
        counts["election_availability"]=insert_jsonl(cur,output_dir/"election_availability.jsonl",availability_sql,availability_mapper,"2024")
        connection.commit()
        return {"database":config["dbname"],"ingest_id":str(ingest_id),"candidate_status":"local_review","local_ingest_status":"pass","scope":"2024 elections plus complete ACS period/geography slice","loaded":counts}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard-config",required=True,type=pathlib.Path)
    parser.add_argument("--prepared-dir",required=True,type=pathlib.Path)
    parser.add_argument("--scope",required=True,choices=["2024"])
    args=parser.parse_args()
    print(json.dumps(load(args),indent=2))


if __name__=="__main__":
    main()
