"""Bootstrap v1 and locally load the candidate v2 slice in a fresh disposable database."""
import argparse
import json
import pathlib
import subprocess
import sys
import uuid

import psycopg2

ROOT = pathlib.Path(__file__).resolve().parents[4]
GUARD_ROOT = pathlib.Path("/tmp/usa-maps-data-flow-20261026").resolve()


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
            target.commit()
        finally:
            target.close()
        guard_path.write_text(json.dumps(config))
        command = [sys.executable, "-m", "database.reader.v2.load_local_review", "--guard-config", str(guard_path), "--prepared-dir", str(args.prepared_dir), "--scope", "2024"]
        loaded = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
        check = psycopg2.connect(host=config["host"], port=config["port"], user=config["user"], dbname=dbname, connect_timeout=3)
        try:
            with check.cursor() as cur:
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
                cur.execute("SELECT count(*) FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING (ingest_id) WHERE b.candidate_status='local_review' AND i.status='pass'")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT count(*) FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING (ingest_id) WHERE b.candidate_status='admitted' AND i.status='pass'")
                assert cur.fetchone()[0] == 0
                cur.execute("SELECT count(*) FROM usa_atlas.observation")
                assert cur.fetchone()[0] == 0  # v1 relation survived; v2 load does not rewrite it.
                cur.execute("SELECT observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,district_code,boundary_vintage,congress_session,is_at_large,period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,source_release,source_url,source_sha256,methodology_note,candidate_status,retrieved_at,ingest_id FROM usa_atlas.reader_observation LIMIT 1")
                row = cur.fetchone()
                cur.execute("INSERT INTO usa_atlas.reader_observation VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
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
                        cur.execute("INSERT INTO usa_atlas.reader_observation VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", bad)
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
        fixtures_passed = run_fixture_database(admin)
        print(json.dumps({"status": "PASS", "database": dbname, "candidate_status": "local_review", "load": loaded, "checks": {"aian_county_state_nation": 3275, "house_2024_dc_delegate_validated": True, "house_dc_democrat_share": float(dc), "validated_absent_party_returns_zero": True, "senate_no_election_rows": 17, "local_review_pass_run_not_admitted": True, "duplicate_observation_grain_rejected": True, "M13_month_null_and_invalid_13_rejected": True, "observed_value_and_source_status_invariants": True, "office_geography_mismatch_rejected": True, "v1_to_additive_v2_fixture_migration": fixtures_passed, "fixture_zero_missing_no_election_and_constraint_invariants": fixtures_passed}}, indent=2))
    finally:
        if guard_path.exists():
            guard_path.unlink()
        with admin.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "' + dbname + '" WITH (FORCE)')
        admin.close()


if __name__ == "__main__":
    main()
