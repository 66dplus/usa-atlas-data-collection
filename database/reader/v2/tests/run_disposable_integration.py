"""Bootstrap v1 and locally load the candidate v2 slice in a fresh disposable database."""
import argparse
import json
import hashlib
import pathlib
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import contextlib
import io

import psycopg2
from database.reader.v2 import admission

ROOT = pathlib.Path(__file__).resolve().parents[4]
GUARD_ROOT = pathlib.Path("/tmp/usa-maps-data-flow-20261026").resolve()
OBSERVATION_COLUMNS = "observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,district_code,boundary_vintage,congress_session,is_at_large,period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,source_release,source_version,source_url,source_sha256,methodology_note,candidate_status,retrieved_at,ingest_id"
OBSERVATION_INSERT = "INSERT INTO usa_atlas.reader_observation (" + OBSERVATION_COLUMNS + ") VALUES (" + ",".join(["%s"] * 36) + ")"


def run_fixture_database(admin):
    dbname = "reader_v2_worker_" + uuid.uuid4().hex[:12]
    with admin.cursor() as cur:
        cur.execute('CREATE DATABASE "' + dbname + '"')
    connection = psycopg2.connect(host=str(GUARD_ROOT / "pgsocket"), port=55446, user="atlas", dbname=dbname, connect_timeout=3)
    try:
        with connection.cursor() as cur:
            cur.execute((ROOT / "database/reader/v1/schema.sql").read_text())
            cur.execute((ROOT / "database/reader/v2/schema.sql").read_text())
            cur.execute((ROOT / "database/reader/v2/fixtures/reader-fixture.sql").read_text())
            cur.execute((ROOT / "database/reader/v2/tests/invariants.sql").read_text())
        connection.commit()
    finally:
        connection.close()
        with admin.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "' + dbname + '" WITH (FORCE)')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    dbname = "reader_v2_worker_" + uuid.uuid4().hex[:12]
    guard_path = GUARD_ROOT / (dbname + ".json")
    config = {"host": str(GUARD_ROOT / "pgsocket"), "port": 55446, "user": "atlas", "dbname": dbname}
    admin = psycopg2.connect(host=config["host"], port=config["port"], user=config["user"], dbname="postgres", connect_timeout=3)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute('CREATE DATABASE "' + dbname + '"')
        target = psycopg2.connect(host=config["host"], port=config["port"], user=config["user"], dbname=dbname, connect_timeout=3)
        try:
            with target.cursor() as cur:
                cur.execute((ROOT / "database/reader/v1/schema.sql").read_text())
                cur.execute("INSERT INTO usa_atlas.catalog_field VALUES ('11.01','Legacy cancer field','run_now','uscs','legacy-release','{}'::jsonb,repeat('a',64))")
                cur.execute("INSERT INTO usa_atlas.ingest_run VALUES ('00000000-0000-4000-8000-000000009999','legacy','legacy-fixture',repeat('b',64),repeat('c',64),1,now(),now(),'pass',NULL)")
                cur.execute("INSERT INTO usa_atlas.observation VALUES ('06001','county','2023','11.01','11.01',1,'count','legacy','legacy-release','https://example.test','preserved legacy row',now(),'00000000-0000-4000-8000-000000009999')")
            target.commit()
        finally:
            target.close()
        baseline = psycopg2.connect(host=config["host"],port=config["port"],user=config["user"],dbname=dbname,connect_timeout=3)
        try:
            with baseline.cursor() as cur:
                cur.execute("SELECT catalog_field_id,catalog_label,source_release,contract_sha256 FROM usa_atlas.catalog_field ORDER BY catalog_field_id"); legacy_catalog_original=cur.fetchall()
                cur.execute("SELECT count(*) FROM usa_atlas.observation"); legacy_observations_original=cur.fetchone()[0]
        finally: baseline.close()
        guard_path.write_text(json.dumps(config))
        command = [sys.executable, "-m", "database.reader.v2.load_local_review", "--guard-config", str(guard_path), "--prepared-dir", str(args.prepared_dir), "--scope", "2024"]
        loaded = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
        check = psycopg2.connect(host=config["host"], port=config["port"], user=config["user"], dbname=dbname, connect_timeout=3)
        try:
            with check.cursor() as cur:
                cur.execute("SELECT catalog_field_id,catalog_label,source_release,contract_sha256 FROM usa_atlas.catalog_field ORDER BY catalog_field_id")
                legacy_catalog_before=cur.fetchall()
                assert legacy_catalog_before==legacy_catalog_original
                cur.execute("SELECT count(*) FROM usa_atlas.observation")
                legacy_observations_before=cur.fetchone()[0]
                assert legacy_observations_before==legacy_observations_original
                cur.execute("SELECT count(*) FROM usa_atlas.reader_observation WHERE field_id='01.04:aian_share' AND period_kind='multi_year' AND period_start_year=2020 AND period_end_year=2024")
                assert cur.fetchone()[0] == 3275
                cur.execute("SELECT count(*) FROM usa_atlas.election_contest WHERE election_year=2024 AND candidate_status='local_review'")
                assert cur.fetchone()[0] > 1000
                cur.execute("SELECT count(*) FROM usa_atlas.election_contest WHERE office='house' AND geo_id='1198' AND boundary_vintage=2024 AND congress_session='119' AND election_year=2024 AND party_aggregation_status='validated'")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT party_votes::numeric/reported_total_votes FROM usa_atlas.election_party_result WHERE contest_id=(SELECT contest_id FROM usa_atlas.election_contest WHERE office='house' AND geo_id='1198' AND election_year=2024 AND result_mode='TOTAL' AND party_aggregation_status='validated') AND party_normalized='DEMOCRAT'")
                dc = cur.fetchone()[0]
                assert abs(float(dc) - 0.765946821597788) < 1e-12, dc
                cur.execute("SELECT coalesce(p.party_votes,0),coalesce(p.share_all_votes,0) FROM usa_atlas.election_contest c LEFT JOIN usa_atlas.election_party_result p ON p.contest_id=c.contest_id AND p.party_normalized='UNLISTED_TEST_PARTY' WHERE c.office='house' AND c.geo_id='1198' AND c.election_year=2024 AND c.result_mode='TOTAL' AND c.party_aggregation_status='validated'")
                assert cur.fetchone() == (0, 0)
                cur.execute("SELECT count(*) FROM usa_atlas.election_availability WHERE office='senate' AND election_year=2024 AND quality_status='no_election'")
                assert cur.fetchone()[0] == 17
                cur.execute("SELECT count(*) FROM usa_atlas.election_contest WHERE office='president' AND election_year=2024 AND result_mode='UNSPECIFIED' AND party_aggregation_status='quarantined' AND '' = ANY(source_mode_values)")
                assert cur.fetchone()[0] == 621
                cur.execute("SELECT count(*) FROM usa_atlas.election_candidate e JOIN usa_atlas.election_contest c USING (contest_id) WHERE c.office='president' AND c.election_year=2024 AND c.result_mode='UNSPECIFIED' AND e.source_mode_raw='' AND e.quality_status='observed'")
                assert cur.fetchone()[0] > 0
                cur.execute("SELECT count(*) FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING (ingest_id) WHERE b.candidate_status='local_review' AND i.status='pass'")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT count(*) FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING (ingest_id) WHERE b.candidate_status='admitted' AND i.status='pass'")
                assert cur.fetchone()[0] == 0
                cur.execute("SELECT count(*) FROM usa_atlas.observation")
                assert cur.fetchone()[0] == legacy_observations_original  # v1 observation rows are preserved byte-for-value.
                cur.execute("SELECT " + OBSERVATION_COLUMNS + " FROM usa_atlas.reader_observation LIMIT 1")
                row = cur.fetchone()
                cur.execute(OBSERVATION_INSERT, row)
                raise AssertionError("duplicate observation grain unexpectedly accepted")
        except psycopg2.errors.UniqueViolation:
            check.rollback()
        try:
            with check.cursor() as cur:
                cur.execute("SELECT * FROM usa_atlas.reader_observation LIMIT 1")
                sample = list(cur.fetchone())
                for column, value, message in ((13, 13, "M13-as-month"), (17, None, "observed NULL value"), (20, "invalid", "observed invalid source status")):
                    bad = sample[:]
                    bad[0] = "negative-" + message.replace(" ", "-")
                    if column == 13:
                        bad[11], bad[12], bad[13], bad[14], bad[15], bad[16] = "monthly", 2024, value, 2024, 2024, "M13"
                    else:
                        bad[column] = value
                    try:
                        cur.execute(OBSERVATION_INSERT, bad)
                        raise AssertionError(message + " unexpectedly accepted")
                    except psycopg2.errors.CheckViolation:
                        check.rollback()
                try:
                    cur.execute("INSERT INTO usa_atlas.election_contest (contest_id,dataset_id,field_id,catalog_field_id,office,election_year,stage,is_special,is_runoff,geography_type,geo_id,result_mode,reported_total_votes,source_release,source_url,source_sha256,source_version,source_status,production_eligible,quality_status,geography_mapping_status,party_aggregation_status,quarantine_reasons,methodology_note,candidate_status,ingest_id) VALUES ('bad-house-state','house_election','12.03','12.03','house',2024,'GENERAL',false,false,'state','06','TOTAL',100,'bad','https://example.test',repeat('a',64),'test','test',false,'observed','mapped','validated',ARRAY[]::text[],'bad','local_review',%s)", (loaded["ingest_id"],))
                    check.commit()
                    raise AssertionError("office/geography mismatch unexpectedly accepted")
                except psycopg2.errors.CheckViolation:
                    check.rollback()
        finally:
            check.close()
        diag=psycopg2.connect(host=config["host"],port=config["port"],user=config["user"],dbname=dbname,connect_timeout=3)
        with diag.cursor() as cur:
            cur.execute("""SELECT quality_status,source_value_status,geography_mapping_status,count(*) FROM usa_atlas.reader_observation
                WHERE ingest_id=%s::uuid AND ((quality_status='observed' AND (value IS NULL OR source_value_status<>'observed' OR geography_mapping_status<>'mapped')) OR (quality_status IN ('missing','suppressed','invalid','no_election') AND value IS NOT NULL)) GROUP BY 1,2,3""",(loaded["ingest_id"],))
            bad_quality=cur.fetchall()
        diag.close()
        if bad_quality: print(json.dumps({"diagnostic_bad_quality_rows":bad_quality}))
        admission_roundtrip = run_portable_stage_roundtrip(admin,config,loaded["ingest_id"],legacy_catalog_original,legacy_observations_original)
        fixtures_passed = run_fixture_database(admin)
        print(json.dumps({"status": "PASS", "database": dbname, "candidate_status": "local_review", "load": loaded, "checks": {"aian_county_state_nation": 3275, "house_2024_dc_delegate_validated": True, "house_dc_democrat_share": float(dc), "validated_absent_party_returns_zero": True, "senate_no_election_rows": 17, "unspecified_president_modes_quarantined_with_raw_blank": 621, "source_value_validity_preserved_under_aggregation_quarantine": True, "local_review_pass_run_not_admitted": True, "duplicate_observation_grain_rejected": True, "M13_month_null_and_invalid_13_rejected": True, "observed_value_and_source_status_invariants": True, "office_geography_mismatch_rejected": True, "legacy_catalog_and_v1_observations_unchanged_through_admit_revoke": admission_roundtrip, "v1_to_additive_v2_fixture_migration": fixtures_passed, "fixture_zero_missing_no_election_and_constraint_invariants": fixtures_passed}}, indent=2))
    finally:
        if guard_path.exists():
            guard_path.unlink()
        with admin.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "' + dbname + '" WITH (FORCE)')
        admin.close()


def run_admission_roundtrip(config, ingest_id, legacy_catalog_before, legacy_observations_before):
    db=psycopg2.connect(host=config["host"],port=config["port"],user=config["user"],dbname=config["dbname"],connect_timeout=3)
    try:
        with db.cursor() as cur:
            cur.execute("SELECT input_manifest_sha256 FROM usa_atlas.reader_batch WHERE ingest_id=%s::uuid",(ingest_id,)); input_hash=cur.fetchone()[0]
            cur.execute("SELECT artifact_sha256,contract_sha256,row_count FROM usa_atlas.ingest_run WHERE ingest_id=%s::uuid",(ingest_id,)); artifact,contract_sha,row_count=cur.fetchone()
            counts={}; digests={}
            for relation in admission.RELATIONS:
                if relation=="reader_v2_catalog_field":
                    cur.execute("SELECT count(*) FROM usa_atlas.reader_v2_catalog_field WHERE source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=%s::uuid UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=%s::uuid)",(ingest_id,ingest_id))
                else: cur.execute('SELECT count(*) FROM usa_atlas.'+relation+' WHERE ingest_id=%s::uuid',(ingest_id,))
                counts[relation]=cur.fetchone()[0]
                digests[relation]=admission._relation_digest(cur,relation,ingest_id)
        db.commit()
    finally: db.close()
    batch={"ingest_id":ingest_id,"artifact_sha256":artifact,"contract_sha256":contract_sha,"row_count":row_count,
           "input_manifest_sha256":input_hash,"table_counts":counts,"table_digests":digests}
    bundle={"format":"usa_atlas_reader_v2_admission_bundle","contract_sha256":contract_sha,
            "expected_input_manifest_sha256s":[input_hash],"ingests":[batch]}
    fake_target={**config,"target_id":"reader_v2_worker_integration_20261026","reader_role":"atlas_reader","write_enabled":True}
    with tempfile.TemporaryDirectory(dir=str(admission.GUARD_ROOT)) as temp:
        receipt=pathlib.Path(temp)/"review.json"; digest="a"*64
        args=SimpleNamespace(target_config="unused",bundle="unused",review_receipt=receipt,apply=True,actor="")
        for action,decision in (("admit","approved"),("revoke","revoke")):
            receipt.write_text(json.dumps({"decision":decision,"bundle_sha256":digest,"contract_sha256":contract_sha,
                "target_id":fake_target["target_id"],"reviewer":"disposable integration test",
                "reason":"exercise transactional status roundtrip","expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}))
            with patch.object(admission,"connect_target",return_value=fake_target), patch.object(admission,"validate_bundle",return_value=(bundle,digest)), contextlib.redirect_stdout(io.StringIO()):
                admission.apply_action(args,action)
            verify=psycopg2.connect(host=config["host"],port=config["port"],user=config["user"],dbname=config["dbname"],connect_timeout=3)
            try:
                with verify.cursor() as cur:
                    expected="admitted" if action=="admit" else "local_review"
                    cur.execute("SELECT candidate_status FROM usa_atlas.reader_batch WHERE ingest_id=%s::uuid",(ingest_id,))
                    assert cur.fetchone()[0]==expected
                    cur.execute("SELECT count(*) FROM usa_atlas.reader_observation o JOIN usa_atlas.ingest_run i USING(ingest_id) JOIN usa_atlas.reader_batch b USING(ingest_id) WHERE o.ingest_id=%s::uuid AND i.status='pass' AND b.candidate_status='admitted'",(ingest_id,))
                    available=cur.fetchone()[0]
                    assert (available>0)==(action=="admit")
                    cur.execute("SELECT catalog_field_id,catalog_label,source_release,contract_sha256 FROM usa_atlas.catalog_field ORDER BY catalog_field_id")
                    assert cur.fetchall()==legacy_catalog_before
                    cur.execute("SELECT count(*) FROM usa_atlas.observation")
                    assert cur.fetchone()[0]==legacy_observations_before
                    cur.execute("SELECT action FROM usa_atlas.reader_v2_admission_event WHERE ingest_id=%s::uuid ORDER BY event_id",(ingest_id,))
                    expected_events=["admitted"] if action=="admit" else ["admitted","revoked"]
                    assert [r[0] for r in cur.fetchall()]==expected_events
            finally: verify.close()
    return True


def run_portable_stage_roundtrip(admin, source_config, source_ingest_id, legacy_catalog, legacy_observations):
    """Exercise portable COPY import and admitted/revoked read filtering in throwaway DBs."""
    refresh_id=str(uuid.uuid4()); refresh_manifest="d"*64; contract_sha=admission.sha256(admission.CONTRACT)
    src=psycopg2.connect(host=source_config["host"],port=source_config["port"],user=source_config["user"],dbname=source_config["dbname"],connect_timeout=3)
    try:
        with src.cursor() as cur:
            cur.execute("INSERT INTO usa_atlas.ingest_run VALUES (%s,'refresh-fixture','fixture://refresh',%s,%s,0,now(),now(),'pass',NULL)",(refresh_id,"e"*64,contract_sha))
            cur.execute("INSERT INTO usa_atlas.reader_batch VALUES (%s,'2.0.0','fixture-collector','multi-source-refresh-local-review','local_review',%s,now())",(refresh_id,refresh_manifest))
        src.commit()
    finally: src.close()
    with tempfile.TemporaryDirectory(dir=str(admission.GUARD_ROOT)) as temp:
        root=pathlib.Path(temp); evidence=root/"evidence.json"
        evidence.write_text(json.dumps({"verified_artifacts":[],"source_receipts":[],"code_artifacts":[]}))
        output=root/"portable"; source_target={**source_config,"target_id":"reader_v2_worker_integration_20261026","target_class":"disposable_test"}
        export_args=SimpleNamespace(target_config="unused",evidence_manifest=evidence,output_dir=output)
        with patch.object(admission,"connect_target",return_value=source_target),contextlib.redirect_stdout(io.StringIO()): admission.export_bundle(export_args)
        package=json.loads((output/"bundle.json").read_text())
        destination="reader_v2_stage_test_"+uuid.uuid4().hex[:10]
        with admin.cursor() as cur: cur.execute('CREATE DATABASE "'+destination+'"')
        dest_config={"target_id":"reader_v2_stage_test","target_class":"disposable_test","dbname":destination,
            "host":source_config["host"],"port":source_config["port"],"user":source_config["user"],"reader_role":"atlas_reader","write_enabled":True}
        stage_target=dest_config.copy()
        try:
            fresh=psycopg2.connect(host=source_config["host"],port=source_config["port"],user=source_config["user"],dbname=destination,connect_timeout=3)
            try:
                with fresh.cursor() as cur:
                    cur.execute((ROOT/"database/reader/v1/schema.sql").read_text())
                    cur.execute("INSERT INTO usa_atlas.catalog_field VALUES ('11.01','Legacy cancer field','run_now','uscs','legacy-release','{}'::jsonb,repeat('a',64))")
                    cur.execute("INSERT INTO usa_atlas.ingest_run VALUES ('00000000-0000-4000-8000-000000009999','legacy','legacy-fixture',repeat('b',64),repeat('c',64),1,now(),now(),'pass',NULL)")
                    cur.execute("INSERT INTO usa_atlas.observation VALUES ('06001','county','2023','11.01','11.01',1,'count','legacy','legacy-release','https://example.test','preserved legacy row',now(),'00000000-0000-4000-8000-000000009999')")
                fresh.commit()
            finally: fresh.close()
            stage_receipt=root/"stage-receipt.json"
            stage_receipt.write_text(json.dumps({"decision":"stage","bundle_sha256":package["manifest_sha256"],"contract_sha256":package["contract_sha256"],"target_id":stage_target["target_id"],"reviewer":"disposable test","expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}))
            args=SimpleNamespace(bundle_dir=output,target_config="unused",review_receipt=stage_receipt,apply=True)
            with patch.object(admission,"connect_target",return_value=stage_target),patch.object(admission,"_read_portable_bundle",return_value=(output,package)),contextlib.redirect_stdout(io.StringIO()): admission.stage_bundle(args)
            normalized=[]
            for item in package["ingests"]:
                row=item["ledger"]
                normalized.append({"ingest_id":row[0],"artifact_sha256":row[3],"contract_sha256":row[4],"row_count":row[5],
                    "input_manifest_sha256":item["input_manifest_sha256"],"table_counts":item["table_counts"],"table_digests":item["table_digests"]})
            bundle={"format":"usa_atlas_reader_v2_admission_bundle","contract_sha256":package["contract_sha256"],
                "expected_input_manifest_sha256s":sorted({r["input_manifest_sha256"] for r in normalized}),"ingests":normalized}
            fake_target={**stage_target,"write_enabled":True}
            digest=hashlib.sha256((output/"bundle.json").read_bytes()).hexdigest()
            action_args=SimpleNamespace(target_config="unused",bundle=output/"bundle.json",review_receipt=stage_receipt,apply=True,actor="")
            for action,decision in (("admit","approved"),("revoke","revoke")):
                stage_receipt.write_text(json.dumps({"decision":decision,"bundle_sha256":digest,"contract_sha256":package["contract_sha256"],"target_id":fake_target["target_id"],"reviewer":"disposable test","reason":"roundtrip","expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}))
                with patch.object(admission,"connect_target",return_value=fake_target),patch.object(admission,"validate_bundle",return_value=(bundle,digest)),contextlib.redirect_stdout(io.StringIO()): admission.apply_action(action_args,action)
                check=psycopg2.connect(host=source_config["host"],port=source_config["port"],user=source_config["user"],dbname=destination,connect_timeout=3)
                try:
                    with check.cursor() as cur:
                        cur.execute("SELECT count(*) FROM usa_atlas.reader_observation o JOIN usa_atlas.ingest_run i USING(ingest_id) JOIN usa_atlas.reader_batch b USING(ingest_id) WHERE i.status='pass' AND b.candidate_status='admitted'")
                        assert (cur.fetchone()[0]>0)==(action=="admit")
                        cur.execute("SELECT catalog_field_id,catalog_label,source_release,contract_sha256 FROM usa_atlas.catalog_field ORDER BY catalog_field_id"); assert cur.fetchall()==legacy_catalog
                        cur.execute("SELECT count(*) FROM usa_atlas.observation"); assert cur.fetchone()[0]==legacy_observations
                        cur.execute("SELECT action FROM usa_atlas.reader_v2_admission_event ORDER BY event_id"); events=[r[0] for r in cur.fetchall()]
                        assert events==(["admitted","admitted"] if action=="admit" else ["admitted","admitted","revoked","revoked"])
                        cur.execute("SET ROLE atlas_reader")
                        cur.execute("SELECT count(*) FROM usa_atlas.reader_observation o JOIN usa_atlas.ingest_run i USING(ingest_id) JOIN usa_atlas.reader_batch b USING(ingest_id) WHERE i.status='pass' AND b.candidate_status='admitted'")
                        assert (cur.fetchone()[0]>0)==(action=="admit")
                finally: check.close()
        finally:
            with admin.cursor() as cur: cur.execute('DROP DATABASE IF EXISTS "'+destination+'" WITH (FORCE)')
    return True


if __name__ == "__main__":
    main()
