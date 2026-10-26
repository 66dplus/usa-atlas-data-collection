"""Guarded candidate-only loader for prepared data refresh observations."""
import argparse
import csv
import hashlib
import json
import pathlib
import uuid
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values

from database.reader.v2.load_local_review import GUARD_ROOT, ROOT, guard, sha256

CATALOG = {
    "01.01": {"label":"Census PEP population", "release":"Census PEP Vintage 2025", "dataset_id":"pep_population", "source_code":"census_pep"},
    "07.01": {"label":"IRS SOI income 2023 with matching PEP denominator contract", "release":"irs-soi-2023-pep-vintage-2025", "dataset_id":"irs_agi", "source_code":"irs_soi"},
    "08.05": {"label":"EIA 2025 electricity prices", "release":"EIA Electric Power Annual 2025", "dataset_id":"electricity_price", "source_code":"eia"},
    "11.01": {"label":"Cancer incidence 2023 (multiple retained USCS source releases)", "release":"uscs-diagnosis-2023-multiple-source-releases-local-review", "dataset_id":"cancer", "source_code":"cdc_uscs"},
    "11.02": {"label":"Provisional HIV diagnoses 2024", "release":"AtlasPlus observed 2026-10-11; 2024 diagnoses provisional, reported through December 2025 with 12-month reporting delay", "dataset_id":"hiv", "source_code":"cdc_atlasplus"},
    "11.03": {"label":"Under-18 deaths 2024", "release":"NCHS NVSS Mortality 2018-2024, CDC WONDER release 2026", "dataset_id":"child_deaths_under18", "source_code":"cdc_wonder"},
}
NATIVE_PEP_SOURCE_ID = "census-pep-national-single-age-v2025"
NATIVE_PEP_SHA256 = "6436d4f6972d415caf14cb20776807bc031fc9f1bfc9d6ff26055d592a2b0230"


def verify_native_pep_source(manifest, data_path):
    """Independently verify native national denominators before any DB connection."""
    item = manifest.get("verified_raw_sources", {}).get("pep_nation_age", {})
    source_path = pathlib.Path(item.get("path", ""))
    if item.get("sourceId") != NATIVE_PEP_SOURCE_ID or item.get("sha256") != NATIVE_PEP_SHA256 or not source_path.is_file() or sha256(source_path) != NATIVE_PEP_SHA256:
        raise ValueError("native national PEP source identity or checksum is not verified")
    with source_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("SEX") == "0"]
    totals = [row for row in rows if row.get("AGE") == "999"]
    if len(totals) != 1:
        raise ValueError("native national PEP SEX=0/AGE=999 selector is not unique")
    expected = {}
    for year in (2023, 2024):
        column = f"POPESTIMATE{year}"
        ages = {int(row["AGE"]):int(row[column]) for row in rows if row.get("AGE", "").isdigit() and row.get(column, "").isdigit()}
        total = int(totals[0][column])
        expected[(year,"01.01:pep_population_total")] = total
        if not set(range(13)).issubset(ages) or not set(range(18)).issubset(ages):
            raise ValueError("native national PEP age selectors are incomplete")
        expected[(year,"01.01:pep_population_age_13_plus")] = total - sum(ages[age] for age in range(13))
        expected[(year,"01.01:pep_population_under_18")] = sum(ages[age] for age in range(18))
    observed = {}
    irs = cancer = None
    with pathlib.Path(data_path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("dataset_id") == "pep_population" and row.get("geo_type") == "nation" and row.get("geo_id") == "US":
                observed[(int(row["period_year"]),row["field_id"])] = row
            elif row.get("dataset_id") == "irs_agi" and row.get("field_id") == "07.01:derived:per-resident" and row.get("geo_type") == "nation" and row.get("geo_id") == "US" and int(row.get("period_year",0)) == 2023:
                irs = row
            elif row.get("dataset_id") == "cancer" and row.get("field_id") == "11.01" and row.get("geo_type") == "nation" and row.get("geo_id") == "US" and int(row.get("period_year",0)) == 2023:
                cancer = row
    for identity, value in expected.items():
        row = observed.get(identity)
        if not row or row.get("quality_status") != "observed" or int(row["value"]) != value or row.get("source_sha256") != NATIVE_PEP_SHA256:
            raise ValueError("prepared national PEP differs from independently verified native Census rows")
    pep_2023 = expected[(2023,"01.01:pep_population_total")]
    if not irs or irs.get("quality_status") != "observed" or int(irs.get("raw_denominator",0)) != pep_2023:
        raise ValueError("national IRS row does not use native 2023 PEP total")
    if abs(Decimal(irs["value"]) - Decimal(irs["raw_estimate"]) * 1000 / Decimal(pep_2023)) > Decimal("0.00000001"):
        raise ValueError("national IRS per-resident formula does not match native 2023 PEP")
    if not cancer or cancer.get("quality_status") != "observed" or int(cancer.get("raw_estimate",0)) != 1941540 or int(cancer.get("raw_denominator",0)) != pep_2023:
        raise ValueError("national cancer row does not use verified count and native 2023 PEP total")
    if abs(Decimal(cancer["value"]) - Decimal(1941540) / Decimal(pep_2023) * 100000) > Decimal("0.000001"):
        raise ValueError("national cancer crude-rate formula does not match native 2023 PEP")


def checked_manifest(filename):
    path = pathlib.Path(filename).resolve()
    if GUARD_ROOT not in path.parents:
        raise ValueError("refresh manifest must be under approved /tmp task directory")
    manifest = json.loads(path.read_text())
    if (manifest.get("candidate_status") != "local_review_not_admitted" or
            manifest.get("contract_version") != "2.0.0-candidate" or
            manifest.get("collector_version") != "data-refresh-preparation-2026.10.26.1"):
        raise ValueError("refresh manifest is not the reviewed candidate contract")
    for item in manifest.get("inputs", {}).values():
        source = pathlib.Path(item["path"]).resolve()
        if GUARD_ROOT not in source.parents or not source.is_file() or sha256(source) != item["sha256"]:
            raise ValueError("prepared refresh input is missing or corrupt")
    for item in manifest.get("verified_raw_sources", {}).values():
        source = pathlib.Path(item.get("path", "")).resolve()
        if not item.get("sha256") or not source.is_file() or sha256(source) != item["sha256"]:
            raise ValueError("verified refresh source artifact is missing or corrupt")
    output = manifest.get("output", {})
    data_path = pathlib.Path(output.get("path", "")).resolve()
    if path.parent not in data_path.parents or not data_path.is_file() or sha256(data_path) != output.get("sha256"):
        raise ValueError("normalized refresh JSONL is missing or corrupt")
    return manifest, path, data_path


def load(guard_config, manifest_path):
    config = guard(guard_config)
    manifest, manifest_path, data_path = checked_manifest(manifest_path)
    verify_native_pep_source(manifest, data_path)
    db = psycopg2.connect(host=config["host"], port=config["port"], user=config["user"],
                          dbname=config["dbname"], connect_timeout=3)
    ingest_id = uuid.uuid4()
    contract_sha = sha256(ROOT / "database/reader/v2/contract.json")
    try:
        with db.cursor() as cur:
            cur.execute("SELECT current_database(),to_regclass('usa_atlas.ingest_run'),to_regclass('usa_atlas.catalog_field')")
            name, run_rel, catalog_rel = cur.fetchone()
            if name != config["dbname"] or run_rel is None or catalog_rel is None:
                raise ValueError("target must already have the v1 schema on the approved disposable DB")
            cur.execute((ROOT / "database/reader/v2/schema.sql").read_text())
            contract_json = json.loads((ROOT / "database/reader/v2/contract.json").read_text())
            for field, metadata in CATALOG.items():
                body = {"contract_version": contract_json["contract_version"], "field_id":field,
                        "dataset_id":metadata["dataset_id"], "sourceCode":metadata["source_code"],
                        "sourceRelease":metadata["release"], "candidate_status":"local_review_not_admitted"}
                if field == "01.01":
                    body["fieldIds"] = ["01.01:pep_population_total", "01.01:pep_population_age_13_plus", "01.01:pep_population_under_18"]
                elif field == "07.01":
                    body.update({"fieldIds":["07.01:agi_total","07.01:derived:per-resident"],
                                 "incomeField":"A00100", "incomeYear":2023, "populationYear":2023,
                                 "formula":"A00100 thousand USD * 1000 / same-geography 2023 PEP total population"})
                elif field == "08.05":
                    body.update({"fieldId":"08.05:sector_ALL", "year":2025, "sector":"ALL", "unit":"cents/kWh"})
                else:
                    body.update({"periodKind":"annual", "year":2023 if field == "11.01" else 2024,
                                 "sourceAdjustment":"crude; numerator / same-year appropriate PEP population * 100000"})
                    if field == "11.01":
                        body["sourceReleases"] = [
                            "2025 NPCR/SEER submission released June 2026; diagnosis year 2023",
                            "USCS 2026 submission; 2023 incidence",
                        ]
                body_sha = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                cur.execute("""INSERT INTO usa_atlas.catalog_field
                    (catalog_field_id,catalog_label,planned_state,rate_limit_profile,source_release,contract,contract_sha256)
                    VALUES (%s,%s,'candidate','local_review',%s,%s::jsonb,%s)
                    ON CONFLICT (catalog_field_id) DO UPDATE SET catalog_label=EXCLUDED.catalog_label,
                    planned_state=EXCLUDED.planned_state,rate_limit_profile=EXCLUDED.rate_limit_profile,
                    source_release=EXCLUDED.source_release,contract=EXCLUDED.contract,
                    contract_sha256=EXCLUDED.contract_sha256""",
                    (field, metadata["label"], metadata["release"], json.dumps(body), body_sha))

            data_sha = sha256(data_path)
            count = manifest["output"]["rows"]
            cur.execute("""INSERT INTO usa_atlas.ingest_run
                (ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,completed_at,status,error_code)
                VALUES (%s,'candidate_refresh_local_review',%s,%s,%s,%s,now(),now(),'pass',NULL)""",
                (str(ingest_id), str(manifest_path), sha256(manifest_path), contract_sha, count))
            cur.execute("""INSERT INTO usa_atlas.reader_batch
                (ingest_id,contract_version,collector_version,observation_release,candidate_status,input_manifest_sha256)
                VALUES (%s,%s,%s,'multi-source-refresh-local-review','local_review',%s)""",
                (str(ingest_id), manifest["contract_version"], manifest["collector_version"], sha256(manifest_path)))
            sql = """INSERT INTO usa_atlas.reader_observation
              (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,district_code,boundary_vintage,congress_session,is_at_large,period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,source_release,source_version,source_url,source_sha256,methodology_note,candidate_status,retrieved_at,ingest_id)
              VALUES %s
              ON CONFLICT (observation_id) DO UPDATE SET
                dataset_id=EXCLUDED.dataset_id,field_id=EXCLUDED.field_id,catalog_field_id=EXCLUDED.catalog_field_id,
                geo_id=EXCLUDED.geo_id,geo_type=EXCLUDED.geo_type,state_fips=EXCLUDED.state_fips,
                district_code=EXCLUDED.district_code,boundary_vintage=EXCLUDED.boundary_vintage,
                congress_session=EXCLUDED.congress_session,is_at_large=EXCLUDED.is_at_large,
                period_kind=EXCLUDED.period_kind,period_year=EXCLUDED.period_year,period_month=EXCLUDED.period_month,
                period_start_year=EXCLUDED.period_start_year,period_end_year=EXCLUDED.period_end_year,
                source_period_code=EXCLUDED.source_period_code,value=EXCLUDED.value,unit=EXCLUDED.unit,
                quality_status=EXCLUDED.quality_status,source_value_status=EXCLUDED.source_value_status,
                geography_mapping_status=EXCLUDED.geography_mapping_status,raw_estimate=EXCLUDED.raw_estimate,
                raw_estimate_moe=EXCLUDED.raw_estimate_moe,raw_denominator=EXCLUDED.raw_denominator,
                raw_denominator_moe=EXCLUDED.raw_denominator_moe,denominator_value=EXCLUDED.denominator_value,
                source=EXCLUDED.source,source_release=EXCLUDED.source_release,source_version=EXCLUDED.source_version,
                source_url=EXCLUDED.source_url,source_sha256=EXCLUDED.source_sha256,
                methodology_note=EXCLUDED.methodology_note,candidate_status=EXCLUDED.candidate_status,
                retrieved_at=EXCLUDED.retrieved_at,ingest_id=EXCLUDED.ingest_id"""
            batch = []; loaded = 0
            with data_path.open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    batch.append((row["observation_id"],row["dataset_id"],row["field_id"],row["catalog_field_id"],row["geo_id"],row["geo_type"],row.get("state_fips"),row.get("district_code"),row.get("boundary_vintage"),row.get("congress_session"),row.get("is_at_large",False),row["period_kind"],row["period_year"],row.get("period_month"),row["period_start_year"],row["period_end_year"],row.get("source_period_code"),row.get("value"),row["unit"],row["quality_status"],row["source_value_status"],row["geography_mapping_status"],row.get("raw_estimate"),row.get("raw_estimate_moe"),row.get("raw_denominator"),row.get("raw_denominator_moe"),row.get("denominator_value"),row["source"],row["source_release"],row.get("source_version", ""),row["source_url"],row["source_sha256"],row["methodology_note"],"local_review",row.get("retrieved_at"),str(ingest_id)))
                    if len(batch) >= 1000:
                        execute_values(cur, sql, batch, page_size=1000); loaded += len(batch); batch = []
            if batch:
                execute_values(cur, sql, batch, page_size=1000); loaded += len(batch)
            if loaded != count:
                raise ValueError("refresh row count differs from manifest")
        db.commit()
        return {"database":config["dbname"],"ingest_id":str(ingest_id),"loaded_rows":loaded,
                "candidate_status":"local_review","local_ingest_status":"pass",
                "source_release_versions":manifest["source_release_versions"]}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard-config", required=True, type=pathlib.Path)
    parser.add_argument("--refresh-manifest", required=True, type=pathlib.Path)
    args = parser.parse_args()
    print(json.dumps(load(args.guard_config, args.refresh_manifest), indent=2))


if __name__ == "__main__":
    main()
