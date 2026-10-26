"""Read-only end-to-end checks against the current app adapter and source-backed local review DB."""
import argparse
import csv
import hashlib
import json
import os
import pathlib
import sys
from decimal import Decimal
from datetime import datetime, timezone


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def find_record(path, predicate):
    with pathlib.Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if predicate(row):
                return row
    raise AssertionError("expected source-backed record was not found")


def source_party_share(csv_path, office, geography_id, party):
    votes = 0
    denominator = None
    with pathlib.Path(csv_path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("year") != "2024" or row.get("mode", "").strip().upper() != "TOTAL":
                continue
            if office == "president":
                matches = str(int(row["county_fips"])).zfill(5) == geography_id
            else:
                state = str(int(row["state_fips"])).zfill(2)
                district = str(int(row["district"])).zfill(2)
                geoid = "1198" if state == "11" and district == "00" else state + district
                matches = geoid == geography_id
            if not matches:
                continue
            current_total = int(row["totalvotes"])
            if denominator is not None and denominator != current_total:
                raise AssertionError("source totalvotes differ within the chosen contest")
            denominator = current_total
            party_column = "party_detailed" if office == "senate" else "party"
            source_party = row.get(party_column, "").strip().upper()
            normalized = "DEMOCRAT" if source_party in ("DEMOCRAT", "DEMOCRATIC") else source_party
            if normalized == party:
                votes += int(row["candidatevotes"])
    if denominator is None:
        raise AssertionError("source contest not found")
    return votes, denominator


def run(args):
    guard = json.loads(args.guard_config.read_text())
    if guard.get("dbname") != args.database or guard.get("port") != 55446 or guard.get("user") != "atlas":
        raise ValueError("guard config does not describe the requested approved disposable database")
    approved_socket = pathlib.Path("/tmp/usa-maps-data-flow-20261026/pgsocket").resolve()
    if pathlib.Path(guard.get("host", "")).resolve() != approved_socket:
        raise ValueError("guard config is not on the approved temporary socket")
    politics_manifest = json.loads((args.politics_prepared_dir / "reader-results.json").read_text())
    bls_manifest = json.loads((args.bls_prepared_dir / "bls-manifest.json").read_text())
    if politics_manifest.get("candidate_status") != "local_review_not_admitted" or bls_manifest.get("candidate_status") != "local_review_not_admitted":
        raise ValueError("this test only accepts local-review candidate inputs")
    for output in politics_manifest["outputs"].values():
        path = pathlib.Path(output["path"])
        if sha256(path) != output["sha256"]:
            raise ValueError("politics normalized input hash mismatch")
    bls_path = pathlib.Path(bls_manifest["output"]["path"])
    if sha256(bls_path) != bls_manifest["output"]["sha256"]:
        raise ValueError("BLS normalized input hash mismatch")

    app_scripts = args.app_root / "scripts"
    sys.path.insert(0, str(app_scripts))
    os.environ["PGHOST"] = guard["host"]
    os.environ["PGPORT"] = str(guard["port"])
    os.environ["PGUSER"] = "atlas_reader"
    os.environ["ATLAS_READER_V2_DATABASE"] = guard["dbname"]
    os.environ["ATLAS_CD119_GEOJSON"] = str(args.boundary_geojson)
    os.environ["ATLAS_CD119_GEOJSON_SHA256"] = args.boundary_geojson_sha256
    import atlas_data

    access = atlas_data.query("SELECT json_build_object('user',current_user,'read_only',current_setting('transaction_read_only'))", database=args.database)
    if access != {"user": "atlas_reader", "read_only": "on"}:
        raise AssertionError("adapter did not connect read-only as the restricted user")

    national = atlas_data.query("""SELECT json_build_object(
      'pep',(SELECT json_agg(json_build_object('year',period_year,'value',value,'quality',quality_status,
        'sha256',source_sha256,'url',source_url,'retrieved_at',retrieved_at)) FROM usa_atlas.reader_observation
        WHERE dataset_id='pep_population' AND field_id='01.01:pep_population_total' AND geo_type='nation' AND geo_id='US' AND period_year IN (2023,2024)),
      'irs',(SELECT json_build_object('value',value,'quality',quality_status,'numerator',raw_estimate,
        'denominator',raw_denominator,'denominator_value',denominator_value,'release',source_release)
        FROM usa_atlas.reader_observation WHERE dataset_id='irs_agi' AND field_id='07.01:derived:per-resident'
          AND geo_type='nation' AND geo_id='US' AND period_year=2023),
      'cancer',(SELECT json_build_object('value',value,'quality',quality_status,'numerator',raw_estimate,
        'denominator',raw_denominator,'denominator_value',denominator_value,'release',source_release)
        FROM usa_atlas.reader_observation WHERE dataset_id='cancer' AND field_id='11.01'
          AND geo_type='nation' AND geo_id='US' AND period_year=2023))""", database=args.database)
    pep_rows = national["pep"]
    pep_by_year = {int(row["year"]):row for row in pep_rows}
    if (set(pep_by_year) != {2023,2024} or str(pep_by_year[2023]["value"]) != "336755052" or
            str(pep_by_year[2024]["value"]) != "340003797" or any(r["quality"] != "observed" for r in pep_rows) or
            any(r["sha256"] != "6436d4f6972d415caf14cb20776807bc031fc9f1bfc9d6ff26055d592a2b0230" for r in pep_rows) or
            datetime.fromisoformat(pep_by_year[2023]["retrieved_at"]).astimezone(timezone.utc).isoformat() != "2026-10-26T10:58:12+00:00"):
        raise AssertionError("native national PEP rows are missing or not source-hash bound")
    irs, cancer = national["irs"], national["cancer"]
    if (irs["quality"] != "observed" or Decimal(irs["denominator"]) != Decimal("336755052") or
            abs(Decimal(irs["value"]) - Decimal(irs["numerator"]) * 1000 / Decimal(irs["denominator"])) > Decimal("0.00000001")):
        raise AssertionError("national IRS per-resident income did not use native same-year PEP denominator")
    if (cancer["quality"] != "observed" or Decimal(cancer["numerator"]) != Decimal("1941540") or
            Decimal(cancer["denominator"]) != Decimal("336755052") or
            abs(Decimal(cancer["value"]) - Decimal(cancer["numerator"]) / Decimal(cancer["denominator"]) * 100000) > Decimal("0.000001")):
        raise AssertionError("national cancer rate did not use native same-year PEP denominator")
    mode_expected = politics_manifest["coverage_2024"]["president"]
    mode_evidence = atlas_data.query("""SELECT json_build_object(
      'contest_count',(SELECT count(*) FROM usa_atlas.election_contest WHERE office='president' AND election_year=2024 AND result_mode='UNSPECIFIED'),
      'blank_mode_values',(SELECT coalesce(array_agg(DISTINCT source_mode_values[1]),ARRAY[]::text[]) FROM usa_atlas.election_contest
        WHERE office='president' AND election_year=2024 AND result_mode='UNSPECIFIED'),
      'validity',(SELECT json_agg(DISTINCT quality_status) FROM usa_atlas.election_candidate
        WHERE contest_id IN (SELECT contest_id FROM usa_atlas.election_contest WHERE office='president' AND election_year=2024 AND result_mode='UNSPECIFIED')),
      'reasons',(SELECT json_agg(DISTINCT unnest_reason) FROM (SELECT unnest(quarantine_reasons) AS unnest_reason FROM usa_atlas.election_contest
        WHERE office='president' AND election_year=2024 AND result_mode='UNSPECIFIED') q))""", database=args.database)
    if (mode_evidence["contest_count"] != mode_expected["unspecified_mode_contests"] or
            mode_evidence["blank_mode_values"] != [""] or "source_mode_unspecified" not in mode_evidence["reasons"] or
            mode_evidence["validity"] != ["observed"]):
        raise AssertionError("unspecified election modes lost raw provenance or incorrectly changed source-value validity")

    monthly = atlas_data.reader_v2_unemployment_period("month", 2025, 1)
    annual = atlas_data.reader_v2_unemployment_period("annual", 2025)
    october = atlas_data.reader_v2_unemployment_period("month", 2025, 10)
    ca_jan_source = find_record(bls_path, lambda r: r["geo_id"] == "06" and r["field_id"] == "03.06:unemployment_rate" and r["source_period_code"] == "2025-M01")
    ca_annual_source = find_record(bls_path, lambda r: r["geo_id"] == "06" and r["field_id"] == "03.06:unemployment_rate" and r["source_period_code"] == "2025-M13")
    ca_oct_source = find_record(bls_path, lambda r: r["geo_id"] == "06" and r["field_id"] == "03.06:unemployment_rate" and r["source_period_code"] == "2025-M10")
    def observed_for(result, source_geo_id):
        return next(row for row in result["observations"] if row["sourceGeoId"] == source_geo_id)
    if monthly["period"] != "2025-M01" or monthly["periodStatus"] != "observed" or observed_for(monthly, "06")["value"] != ca_jan_source["value"]:
        raise AssertionError("CA January value/period differs from verified BLS input")
    if annual["period"] != "2025-M13" or annual["periodType"] != "annual" or annual["month"] is not None or observed_for(annual, "06")["value"] != ca_annual_source["value"]:
        raise AssertionError("CA annual M13 was not selected as an annual observation")
    if october["period"] != "2025-M10" or october["periodStatus"] != "missing" or ca_oct_source["quality_status"] != "missing" or observed_for(october, "06")["value"] is not None:
        raise AssertionError("October source gap was not retained as missing")
    coverage = {kind: sum(row["geoType"] == kind for row in monthly["observations"]) for kind in ("state", "county")}
    observed_coverage = {kind: sum(row["geoType"] == kind and row["qualityState"] == "observed"
                                   for row in monthly["observations"]) for kind in ("state", "county")}
    october_statuses = {row["qualityState"] for row in october["observations"]}
    if coverage != {"state": 51, "county": 3144} or observed_coverage != {"state": 51, "county": 3143}:
        raise AssertionError("BLS state/county coverage differs from prepared source")
    if october_statuses != {"missing"}:
        raise AssertionError("BLS October source gap was converted to a numeric observation")

    aian = atlas_data.reader_v2_observations("aian_broad_share", "multi_year", 2024, "state_and_county")
    aian_us = atlas_data.reader_v2_observations("aian_broad_share", "multi_year", 2024, "nation")
    us_expected = find_record(pathlib.Path(politics_manifest["outputs"]["aian_us"]["path"]), lambda r: r["geo_id"] == "US")
    ca_expected = find_record(pathlib.Path(politics_manifest["outputs"]["aian_state"]["path"]), lambda r: r["geo_id"] == "06")
    if len(aian["observations"]) != 3275 or len(aian_us["observations"]) != 1 or int(aian_us["observations"][0]["count"]) != int(us_expected["raw_estimate"]):
        raise AssertionError("AIAN API omitted/changed state/county coverage or native US source row")
    if next(r for r in aian["observations"] if r["sourceGeoId"] == "06")["value"] != ca_expected["value"]:
        raise AssertionError("AIAN CA value differs from the prepared source row")

    senate = atlas_data.reader_v2_observations("election_senate_2024", "cycle", 2024, "state", "DEMOCRAT")
    ks = next(row for row in senate["observations"] if row["id"] == "20")
    if ks["qualityState"] != "no_election" or ks["value"] is not None:
        raise AssertionError("Kansas Senate status was not explicit no-election")

    president = atlas_data.reader_v2_observations("election_president_2024", "cycle", 2024, "county", "DEMOCRAT")
    pres_votes, pres_total = source_party_share(args.politics_input_dir / "normalized/president_county_2000_2024.csv", "president", "06037", "DEMOCRAT")
    la = next(row for row in president["observations"] if row["id"] == "06037")
    if la["votes"] != pres_votes or la["totalVotes"] != pres_total or abs(la["value"] - 100 * pres_votes / pres_total) > 1e-12:
        raise AssertionError("President LA County selected-party share differs from source candidatevotes/totalvotes")

    house = atlas_data.reader_v2_observations("election_house_2024", "cycle", 2024, "congressional_district", "DEMOCRAT")
    house_votes, house_total = source_party_share(args.politics_input_dir / "normalized/house_district_1976_2024.csv", "house", "0606", "DEMOCRAT")
    cd06 = next(row for row in house["observations"] if row["id"] == "0606")
    if cd06["votes"] != house_votes or cd06["totalVotes"] != house_total or abs(cd06["value"] - 100 * house_votes / house_total) > 1e-12:
        raise AssertionError("House CD06 share differs from source candidatevotes/totalvotes")
    if cd06["boundaryVintage"] != 2024 or cd06["congressSession"] != "119":
        raise AssertionError("House response is not pinned to Census CD119")
    boundary = atlas_data.reader_v2_cd119_boundary()
    if not boundary["available"] or boundary["featureCount"] != 435:
        raise AssertionError("app adapter did not accept the pinned 435 voting CD119 geometries")

    catalog = atlas_data.reader_v2_catalog()
    required = {"01.04":"acs-2024-5year", "12.01":"dataverse-VOQCHQ-v20",
                "12.02":"dataverse-PEJ5QU-v8", "12.03":"prepared-mirror-IG0UN2-v15"}
    for metric in catalog["metrics"]:
        if metric["catalogFieldId"] in required and metric["sourceRelease"] != required[metric["catalogFieldId"]]:
            raise AssertionError("catalog source release mismatch")
    print(json.dumps({"status":"PASS","database":args.database,"read_only_user":"atlas_reader",
        "candidate_status":"local_review","unemployment":{"CA_M01":ca_jan_source["value"],"CA_M13":ca_annual_source["value"],
        "M10":"missing","state_count":coverage["state"],"county_count":coverage["county"],
        "observed_counties":observed_coverage["county"],"october_missing_rows":len(october["observations"])},
        "aian":{"state_county_rows":len(aian["observations"]),"US_count":us_expected["raw_estimate"],"CA_share":ca_expected["value"]},
        "senate_20":ks["qualityState"],"president_06037_share":la["value"],
        "house_0606_share":cd06["value"],"cd119_voting_boundaries":boundary["featureCount"],
        "native_us_pep":{"2023":pep_by_year[2023]["value"],"2024":pep_by_year[2024]["value"]},
        "national_irs_per_resident":irs["value"],"national_cancer_rate":cancer["value"],
        "president_unspecified_mode_contests":mode_evidence["contest_count"]},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard-config", required=True, type=pathlib.Path)
    parser.add_argument("--database", required=True)
    parser.add_argument("--app-root", required=True, type=pathlib.Path)
    parser.add_argument("--politics-input-dir", required=True, type=pathlib.Path)
    parser.add_argument("--politics-prepared-dir", required=True, type=pathlib.Path)
    parser.add_argument("--bls-prepared-dir", required=True, type=pathlib.Path)
    parser.add_argument("--boundary-geojson", required=True, type=pathlib.Path)
    parser.add_argument("--boundary-geojson-sha256", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
