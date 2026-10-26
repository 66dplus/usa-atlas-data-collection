"""Prepare reader-v2 review files from pinned local research inputs; never admit or write a database."""
import argparse
import csv
import hashlib
import json
import pathlib
import shutil
import subprocess
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

POLITICS_FILES = {
    "president": ("normalized/president_county_2000_2024.csv", ",", "d862f565ad7ac09b234f1481db91c3aa46948192bffe6b85df5d0b8b9e01400e", 94151, "12.01", "dataverse-VOQCHQ-v20", "raw/president_county_2000_2024.csv", "9299583148f5f8264baf50b5d929c260699c46d915909b13ea3c3850918946f8"),
    "senate": ("normalized/senate_state_1976_2024.csv", ",", "1807fb552728edd5e1a425bb6a3d4d3e602c1edfb51fe05e16e75a08463313dc", 3945, "12.02", "dataverse-PEJ5QU-v8", "raw/senate_state_1976_2024.csv", "d4492e286046f73b111cf5706ee02be4c305897898317818afd06c0ac8a464e0"),
    # Parse the canonical prepared CSV, not malformed raw mirror quoting; retain both hashes.
    "house": ("normalized/house_district_1976_2024.csv", ",", "cc311bfc9a09ca94859c5e6f92b7cd0f2f16cdee9534ee9eed9f549a1e4c5940", 33805, "12.03", "prepared-mirror-IG0UN2-v15", "raw/house_district_1976_2024.csv", "bd0690fbcd753e45edb40810c99d1b8afbb0de928aa54bff1b227c615d69c163"),
}
ACS_FILES = {
    "us": ("raw/acs_2024_5yr_aian_us.csv", "2ddcd3a7d26bb15901fd4c8d0c391c5a56357332cad0c15510f3ae0fd914b243", 1),
    "state": ("raw/acs_2024_5yr_aian_state.csv", "e86128465aa3ad35629c18062d381cb72132505cecaa5268443058f4ba363301", 52),
    "county": ("raw/acs_2024_5yr_aian_county.csv", "ffbff1bf70d6cdd8af1e399f43e890a80349a53e9b3541bd1dd5b06e7e6c76a1", 3222),
}
BOUNDARY_ZIP_SHA256 = "2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a"
BOUNDARY_SOURCE_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_cd119_500k.zip"
FIELD_IDS = {"aian": "01.04", "president": "12.01", "senate": "12.02", "house": "12.03"}
COLLECTOR_VERSION = "politics-preparation-2.1.0"
CONTRACT_VERSION = "2.0.0-candidate"
SOURCE_URL = {
    "president": "https://doi.org/10.7910/DVN/VOQCHQ",
    "senate": "https://doi.org/10.7910/DVN/PEJ5QU",
    "house": "https://doi.org/10.7910/DVN/IG0UN2",
}
AGGREGATE_LABELS = {"TOTAL VOTES CAST", "UNDERVOTES", "UNDER VOTES", "OVERVOTES", "OVER VOTES"}


def sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strict_int(value):
    if value is None or not str(value).strip():
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return int(number) if number.is_finite() and number == number.to_integral_value() else None


def flag(value):
    return str(value or "false").strip().lower() in {"true", "1", "yes"}


def write_jsonl(path, rows):
    with pathlib.Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def read_csv_rows(path, delimiter=","):
    """Parse a genuine CSV stream; source fields containing commas stay in their column."""
    with pathlib.Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
        if not reader.fieldnames or any(not name for name in reader.fieldnames):
            raise ValueError("CSV header is missing or malformed")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("CSV row width does not match its header")
    return rows, list(reader.fieldnames)


def norm_party(original, candidate_kind):
    if candidate_kind == "source_aggregate":
        return None
    raw = (original or "").strip().upper()
    if raw in {"DEMOCRAT", "DEMOCRATIC", "DEMOCRATIC-FARMER-LABOR", "DFL", "DEMOCRATIC PARTY"}:
        return "DEMOCRAT"
    if raw in {"REPUBLICAN", "GOP", "REPUBLICAN PARTY"}:
        return "REPUBLICAN"
    if raw in {"", "NA", "N/A"} and candidate_kind == "ballot_or_other":
        return "OTHER"
    if raw in {"", "NA", "N/A"}:
        return None
    return raw


def candidate_kind(row):
    name = " ".join((row.get("candidate") or "").strip().upper().replace("_", " ").split())
    if name in AGGREGATE_LABELS:
        return "source_aggregate"
    if flag(row.get("writein")) or name in {"WRITEIN", "WRITE IN", "SCATTER", "NONE OF THESE, CANDIDATES", "OTHER"}:
        return "ballot_or_other"
    return "candidate" if name else "unclassified"


def load_boundary(args, outdir):
    if args.boundary_zip:
        source = pathlib.Path(args.boundary_zip)
        source_hash = sha256(source)
        if source_hash != BOUNDARY_ZIP_SHA256:
            raise ValueError("boundary ZIP failed pinned Census source hash")
        target = outdir / "boundary" / "cd119.geojson"
        target.parent.mkdir(parents=True, exist_ok=True)
        ogr = shutil.which("ogr2ogr")
        if not ogr:
            raise ValueError("ogr2ogr is required to convert pinned CD119 boundary input")
        subprocess.run([ogr, "-f", "GeoJSON", str(target), "/vsizip/" + str(source), "-t_srs", "EPSG:4326"], check=True, capture_output=True, text=True)
        geo_path = target
        provenance = {"source_zip_sha256": source_hash, "source_url": BOUNDARY_SOURCE_URL}
    else:
        source = pathlib.Path(args.boundary_geojson)
        if sha256(source) != args.boundary_geojson_sha256:
            raise ValueError("boundary GeoJSON failed exact trusted SHA-256")
        geo_path = outdir / "boundary" / "cd119.geojson"
        geo_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, geo_path)
        provenance = {"trusted_geojson_sha256": args.boundary_geojson_sha256, "source_url": BOUNDARY_SOURCE_URL}
    data = json.loads(geo_path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection" or len(data.get("features", [])) != 441:
        raise ValueError("CD119 geometry must have the verified 441-feature FeatureCollection shape")
    by_id = {}
    for feature in data["features"]:
        props = feature.get("properties", {})
        geoid, state, district = (str(props.get(k, "")) for k in ("GEOID", "STATEFP", "CD119FP"))
        if not feature.get("geometry") or len(geoid) != 4 or geoid != state + district or geoid in by_id:
            raise ValueError("invalid or duplicate CD119 identity")
        if str(props.get("CDSESSN")) != "119":
            raise ValueError("unexpected CD119 Congress session")
        geom_sha = hashlib.sha256(json.dumps(feature["geometry"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        by_id[geoid] = {"feature": feature, "state_fips": state, "district_code": district, "is_at_large": district == "00", "is_nonvoting": district == "98", "geometry_sha256": geom_sha}
    if "1198" not in by_id or "1100" in by_id or not any(row["is_at_large"] for row in by_id.values()):
        raise ValueError("CD119 source IDs lack expected DC delegate or state at-large features")
    feature_path = outdir / "boundary_features.jsonl"
    write_jsonl(feature_path, [{"geo_id": geoid, "boundary_vintage": 2024, "congress_session": "119", **by_id[geoid]} for geoid in sorted(by_id)])
    manifest = {"boundary_vintage": 2024, "congress_session": "119", "source": provenance, "geojson_sha256": sha256(geo_path), "feature_count": len(by_id), "features": [{"geo_id": geoid, "state_fips": row["state_fips"], "district_code": row["district_code"], "is_at_large": row["is_at_large"], "is_nonvoting": row["is_nonvoting"], "geometry_sha256": row["geometry_sha256"]} for geoid, row in sorted(by_id.items())]}
    (outdir / "cd119_geometry_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return by_id, {"path": str(geo_path), "sha256": sha256(geo_path), "features": len(by_id), "features_jsonl_path": str(feature_path), "features_jsonl_sha256": sha256(feature_path), "source": provenance}


def house_geo(row, boundary_ids):
    state = str(int(row["state_fips"])).zfill(2)
    district_number = strict_int(row.get("district"))
    if district_number is None:
        raise ValueError("House district ID is not numeric")
    raw_code = str(district_number).zfill(2)
    # MEDSL encodes a single-seat state and DC as district 0; Census identifies DC as 1198.
    geoid = "1198" if state == "11" and raw_code == "00" else state + raw_code
    exact = boundary_ids.get(geoid)
    if exact is None:
        return {"geography_type": "congressional_district", "geo_id": geoid, "state_fips": state, "district_code": geoid[-2:], "boundary_vintage": None, "congress_session": None, "is_at_large": False, "seat_type": "unresolved", "geography_mapping_status": "vintage_unresolved"}
    return {"geography_type": "congressional_district", "geo_id": geoid, "state_fips": state, "district_code": exact["district_code"], "boundary_vintage": 2024, "congress_session": "119", "is_at_large": exact["is_at_large"], "seat_type": "nonvoting_delegate" if exact["is_nonvoting"] else "voting_district", "geography_mapping_status": "mapped"}


def election_geo(row, office, boundary_ids):
    if office == "president":
        geoid = str(row["county_fips"]).zfill(5)
        return {"geography_type": "county", "geo_id": geoid, "state_fips": geoid[:2], "district_code": None, "boundary_vintage": None, "congress_session": None, "is_at_large": False, "seat_type": None, "geography_mapping_status": "mapped"}
    if office == "senate":
        state = str(int(row["state_fips"])).zfill(2)
        return {"geography_type": "state", "geo_id": state, "state_fips": state, "district_code": None, "boundary_vintage": None, "congress_session": None, "is_at_large": False, "seat_type": None, "geography_mapping_status": "mapped"}
    if strict_int(row.get("year")) == 2024 and str(row.get("stage", "GEN")).upper() == "GEN" and not flag(row.get("special")):
        geography = house_geo(row, boundary_ids)
        if geography["geography_mapping_status"] != "mapped":
            raise ValueError("2024 general House district does not match a pinned CD119 geometry ID")
        return geography
    geo = house_geo(row, {})
    geo.update({"boundary_vintage": None, "congress_session": None, "is_at_large": False, "seat_type": "unresolved", "geography_mapping_status": "vintage_unresolved"})
    return geo


def make_contest_key(row, office, boundary_ids, release):
    geo = election_geo(row, office, boundary_ids)
    year = strict_int(row.get("year"))
    raw_stage = (row.get("stage") or "GENERAL").strip().upper() if office != "president" else "GENERAL"
    stage = "general" if raw_stage in {"GEN", "GENERAL"} else raw_stage.lower()
    raw_mode = (row.get("mode") or "").strip().upper()
    return (office, year, geo["geography_type"], geo["geo_id"], geo["boundary_vintage"], geo["congress_session"], stage, flag(row.get("special")), flag(row.get("runoff")), raw_mode or "UNSPECIFIED", release, str(row.get("version") or ""))


def adjudicate_contest(rows, expected_source_rows=None, source_complete=False):
    """Validate source values independently from party aggregation; return reviewable party totals."""
    reasons = []
    totals = [row["source_total_votes"] for row in rows]
    distinct_totals = set(totals)
    denominator = next(iter(distinct_totals)) if len(distinct_totals) == 1 else None
    if denominator is None:
        reasons.append("inconsistent_or_invalid_totalvotes")
    elif denominator <= 0:
        reasons.append("nonpositive_contest_denominator")
    if any(row["source_value_status"] != "observed" for row in rows):
        reasons.append("invalid_candidatevotes_or_totalvotes")
    if not source_complete or expected_source_rows is None or len(rows) != expected_source_rows:
        reasons.append("candidate_partition_incomplete")
    candidates = [row for row in rows if row["candidate_kind"] != "source_aggregate"]
    counts = Counter((row["candidate_label"].strip().upper(), row["party_normalized"]) for row in candidates)
    by_candidate = defaultdict(list)
    for row in candidates:
        by_candidate[row["candidate_label"].strip().upper()].append(row)
    for label, matched in by_candidate.items():
        parties = {row["party_normalized"] for row in matched}
        if len(parties) > 1 and not all(row["fusion_ticket"] or row["candidate_kind"] == "ballot_or_other" for row in matched):
            reasons.append("ambiguous_cross_party_candidate")
    for key, count in counts.items():
        dupes = [row for row in candidates if (row["candidate_label"].strip().upper(), row["party_normalized"]) == key]
        if count > 1 and not all(row["candidate_kind"] == "ballot_or_other" for row in dupes):
            reasons.append("repeated_candidate_party_row")
    party_totals = defaultdict(int)
    for row in candidates:
        if row["party_normalized"] is None:
            reasons.append("unclassified_party")
        elif row["candidate_votes"] is not None:
            party_totals[row["party_normalized"]] += row["candidate_votes"]
    if denominator is not None and sum(party_totals.values()) > denominator:
        reasons.append("candidate_votes_exceed_contest_total")
    return {"status": "quarantined" if reasons else "validated", "reasons": sorted(set(reasons)), "denominator": denominator, "party_totals": dict(party_totals)}


def adjudicate_mode(rows, mode, expected_source_rows=None, source_complete=False):
    if mode == "UNSPECIFIED":
        return {"status":"quarantined", "reasons":["source_mode_unspecified"], "denominator":None, "party_totals":{}}
    if mode != "TOTAL":
        return {"status":"excluded_subtotal", "reasons":["subtotal_not_added_to_TOTAL"], "denominator":None, "party_totals":{}}
    return adjudicate_contest(rows, expected_source_rows=expected_source_rows, source_complete=source_complete)


def selected_party_value(adjudication, party):
    if adjudication["status"] != "validated" or not adjudication["denominator"]:
        return None, None
    votes = adjudication["party_totals"].get(party, 0)
    return votes, votes / adjudication["denominator"]


def prepare_elections(input_dir, outdir, boundary_ids):
    candidates_out, contests_out, shares_out = [], [], []
    source_inventory, counts, source_coverage_rows = {}, {}, {}
    for office, (relative, delimiter, expected_hash, expected_rows, field_id, release, raw_relative, raw_hash) in POLITICS_FILES.items():
        source_path = input_dir / relative
        if sha256(source_path) != expected_hash:
            raise ValueError("{} prepared data hash mismatch".format(office))
        rows, headers = read_csv_rows(source_path, delimiter)
        if len(rows) != expected_rows:
            raise ValueError("{} row count mismatch: {}".format(office, len(rows)))
        raw_path = input_dir / raw_relative
        if sha256(raw_path) != raw_hash:
            raise ValueError("{} original source hash mismatch".format(office))
        source_provenance_status = {"president": "official_metadata_checksum_and_size_match", "senate": "official_direct_download_size_and_sha256_match_metadata_md5_processed_file_difference", "house": "mirror_unverified_local_review_only"}[office]
        eligible = office != "house"
        source_inventory[office] = {"path": str(source_path), "prepared_sha256": expected_hash, "raw_source_path": str(raw_path), "raw_source_sha256": raw_hash, "row_count": len(rows), "columns": headers, "source_release": release, "source_status": source_provenance_status, "production_eligible": eligible}
        groups = defaultdict(list)
        source_coverage_rows[office] = []
        for rownum, source_row in enumerate(rows, 1):
            geo = election_geo(source_row, office, boundary_ids)
            if strict_int(source_row.get("year")) == 2024:
                source_coverage_rows[office].append({"geo_id":geo["geo_id"],"mapping":geo["geography_mapping_status"],
                    "mode":(source_row.get("mode") or "").strip().upper() or "<BLANK>"})
            kind = candidate_kind(source_row)
            party_original = (source_row.get("party_detailed") or source_row.get("party_simplified")) if office == "senate" else source_row.get("party")
            normalized = norm_party(party_original, kind)
            candidate = (source_row.get("candidate") or "").strip()
            candidate_votes = strict_int(source_row.get("candidatevotes"))
            total_votes = strict_int(source_row.get("totalvotes"))
            value_status = "observed" if candidate_votes is not None and total_votes is not None and candidate_votes >= 0 and total_votes >= 0 else "invalid"
            key = make_contest_key(source_row, office, boundary_ids, release)
            canonical_dataset = {"president":"election_president_2024", "senate":"election_senate_2024", "house":"election_house_2024"}[office]
            candidate_row = {"source_row_id": str(rownum), "field_id": field_id, "dataset_id": canonical_dataset, "office": office, "election_year": strict_int(source_row.get("year")), **geo, "candidate_label": candidate, "candidate_kind": kind, "party_original": party_original, "party_normalized": normalized, "candidatevotes_raw": source_row.get("candidatevotes"), "totalvotes_raw": source_row.get("totalvotes"), "candidate_votes": candidate_votes, "source_total_votes": total_votes, "source_version": str(source_row.get("version") or ""), "stage": key[6], "source_stage": (source_row.get("stage") or "GENERAL").strip(), "is_special": key[7], "is_runoff": key[8], "result_mode": key[9], "source_mode_raw": source_row.get("mode"), "write_in": flag(source_row.get("writein")), "fusion_ticket": flag(source_row.get("fusion_ticket")), "source_value_status": value_status, "quality_status": value_status, "source_status": source_provenance_status, "source_release": release, "source_sha256": raw_hash, "source_url": SOURCE_URL[office], "prepared_input_sha256": expected_hash, "candidate_status": "local_review", "source_record": source_row}
            groups[key].append(candidate_row)
        office_contests = []
        for key, group in groups.items():
            result = adjudicate_mode(group, key[9], expected_source_rows=len(group), source_complete=True)
            geo = {name: group[0][name] for name in ("geography_type", "geo_id", "state_fips", "district_code", "boundary_vintage", "congress_session", "is_at_large", "seat_type", "geography_mapping_status")}
            contest_id = hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()[:32]
            canonical_dataset = {"president":"election_president_2024", "senate":"election_senate_2024", "house":"election_house_2024"}[office]
            summary = {"contest_id": contest_id, "field_id": field_id, "catalog_field_id": field_id, "dataset_id": canonical_dataset, **geo, "office": office, "election_year": key[1], "stage": key[6], "source_stage_values": sorted({(row.get("source_stage") or "GENERAL") for row in group}), "source_mode_values": sorted({row.get("source_mode_raw") or "" for row in group}), "is_special": key[7], "is_runoff": key[8], "result_mode": key[9], "source_release": release, "source_version": key[11], "reported_total_votes": result["denominator"], "reported_total_votes_raw_values": sorted({row["totalvotes_raw"] for row in group if row["totalvotes_raw"] is not None}), "party_aggregation_status": result["status"], "quarantine_reasons": result["reasons"], "quality_status": "observed" if result["denominator"] is not None else "missing", "source_status": source_provenance_status, "source_sha256": raw_hash, "source_url": SOURCE_URL[office], "prepared_input_sha256": expected_hash, "production_eligible": eligible, "candidate_status": "local_review", "row_count": len(group), "methodology_note": "Selected-party candidatevotes divided by contest totalvotes. Completeness is grounded in the pinned full prepared-file hash and all source rows assigned once to this contest; repeated candidate totalvotes are provenance, never added. TOTAL mode only; known aggregate rows such as undervotes remain source rows and are excluded from candidate party totals. Unspecified source modes remain quarantined pending publisher semantics."}
            office_contests.append(summary)
            for row in group:
                row["contest_id"] = contest_id
                row["aggregation_quarantine_reasons"] = result["reasons"]
                candidates_out.append(row)
            if key[9] == "TOTAL":
                party_totals = result["party_totals"]
                if result["status"] == "validated":
                    party_totals.setdefault("DEMOCRAT", 0)
                    party_totals.setdefault("REPUBLICAN", 0)
                all_parties = set(party_totals) | {"DEMOCRAT", "REPUBLICAN"}
                for party in sorted(all_parties):
                    votes, share = selected_party_value(result, party)
                    shares_out.append({"contest_id": contest_id, "field_id": field_id, "dataset_id": canonical_dataset, "office": office, "election_year": key[1], "geography_type": key[2], "geo_id": key[3], "boundary_vintage": key[4], "congress_session": key[5], "stage": key[6], "is_special": key[7], "is_runoff": key[8], "result_mode": "TOTAL", "party_normalized": party, "party_votes": votes, "reported_total_votes": result["denominator"], "share_all_votes": share, "quality_status": "observed" if result["status"] == "validated" else "missing", "party_aggregation_status": result["status"], "source_release": release, "source_status": source_provenance_status, "source_sha256": raw_hash, "source_url": SOURCE_URL[office], "production_eligible": eligible, "candidate_status": "local_review"})
        contests_out.extend(office_contests)
        total_contests = [c for c in office_contests if c["result_mode"] == "TOTAL"]
        counts[office] = {"source_rows": len(rows), "contest_mode_groups": len(office_contests), "validated_total_contests": sum(c["party_aggregation_status"] == "validated" for c in total_contests), "quarantined_total_contests": sum(c["party_aggregation_status"] == "quarantined" for c in total_contests), "unspecified_mode_contests": sum(c["result_mode"] == "UNSPECIFIED" for c in office_contests)}
    # Official 2024 Senate Class I schedule: emit explicit no-election versus missing state records.
    class_i = {"AZ", "CA", "CT", "DE", "FL", "HI", "IN", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NJ", "NM", "NY", "ND", "OH", "PA", "RI", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"}
    state_fips = {"AL":1,"AK":2,"AZ":4,"AR":5,"CA":6,"CO":8,"CT":9,"DE":10,"FL":12,"GA":13,"HI":15,"ID":16,"IL":17,"IN":18,"IA":19,"KS":20,"KY":21,"LA":22,"ME":23,"MD":24,"MA":25,"MI":26,"MN":27,"MS":28,"MO":29,"MT":30,"NE":31,"NV":32,"NH":33,"NJ":34,"NM":35,"NY":36,"NC":37,"ND":38,"OH":39,"OK":40,"OR":41,"PA":42,"RI":44,"SC":45,"SD":46,"TN":47,"TX":48,"UT":49,"VT":50,"VA":51,"WA":53,"WV":54,"WI":55,"WY":56}
    senate_source, _, _, _, _, senate_release, _, _ = POLITICS_FILES["senate"]
    senate_rows, _ = read_csv_rows(input_dir / senate_source)
    observed = defaultdict(list)
    for source_row in senate_rows:
        if strict_int(source_row.get("year")) != 2024:
            continue
        key = make_contest_key(source_row, "senate", boundary_ids, senate_release)
        observed[key[3]].append(key)
    availability = []
    for postal, fips in sorted(state_fips.items(), key=lambda pair: pair[1]):
        geoid = str(fips).zfill(2)
        if postal not in class_i:
            availability.append({"field_id": "12.02", "dataset_id": "election_senate_2024", "office": "senate", "election_year": 2024, "geography_type": "state", "geo_id": geoid, "boundary_vintage": None, "congress_session": None, "stage": "general", "is_special": False, "is_runoff": False, "quality_status": "no_election", "source_release": senate_release, "reason": "No 2024 regular Class I race and no 2024 special contest on the official Senate schedule.", "candidate_status": "local_review"})
        elif not observed.get(geoid):
            availability.append({"field_id": "12.02", "dataset_id": "election_senate_2024", "office": "senate", "election_year": 2024, "geography_type": "state", "geo_id": geoid, "boundary_vintage": None, "congress_session": None, "stage": "general", "is_special": False, "is_runoff": False, "quality_status": "missing", "source_release": senate_release, "reason": "Official schedule has a Class I race but prepared source has no 2024 candidate rows.", "candidate_status": "local_review"})
        else:
            for key in sorted(set(observed[geoid])):
                availability.append({"field_id": "12.02", "dataset_id": "election_senate_2024", "office": "senate", "election_year": 2024, "geography_type": "state", "geo_id": geoid, "boundary_vintage": None, "congress_session": None, "stage": key[6], "is_special": key[7], "is_runoff": key[8], "quality_status": "observed", "source_release": senate_release, "reason": "2024 candidate source rows present; aggregation validity is recorded on the separate contest row.", "candidate_status": "local_review"})
    availability_path = outdir / "election_availability.jsonl"
    write_jsonl(availability_path, availability)
    coverage = {}
    for office, rows in source_coverage_rows.items():
        contests_2024 = [r for r in contests_out if r["office"] == office and r["election_year"] == 2024]
        office_availability = [r for r in availability if r["office"] == office and r["election_year"] == 2024]
        mode_rows, mode_geos = Counter(), defaultdict(set)
        mapping_geos = set()
        for row in rows:
            mode_rows[row["mode"]] += 1
            mode_geos[row["mode"]].add(row["geo_id"])
            if row["mapping"] != "mapped":
                mapping_geos.add(row["geo_id"])
        total_contests = [r for r in contests_2024 if r["result_mode"] == "TOTAL"]
        all_source_geos = {r["geo_id"] for r in rows}
        total_source_geos = mode_geos.get("TOTAL",set())
        nonblank_mode_geos = set.union(*(g for mode,g in mode_geos.items() if mode != "<BLANK>")) if any(mode != "<BLANK>" for mode in mode_geos) else set()
        other_modes_geos = set.union(*(g for mode,g in mode_geos.items() if mode not in ("TOTAL","<BLANK>"))) if any(mode not in ("TOTAL","<BLANK>") for mode in mode_geos) else set()
        other_than_vote_center = set.union(*(g for mode,g in mode_geos.items() if mode not in ("TOTAL","<BLANK>","VOTE CENTER"))) if any(mode not in ("TOTAL","<BLANK>","VOTE CENTER") for mode in mode_geos) else set()
        coverage[office] = {
            "source_rows":len(rows), "source_geographies":len({r["geo_id"] for r in rows}),
            "source_mode_row_counts":dict(sorted(mode_rows.items())),
            "explicit_total_geographies":len(mode_geos.get("TOTAL",set())),
            "validated_total_contests":sum(r["party_aggregation_status"] == "validated" for r in total_contests),
            "quarantined_total_contests":sum(r["party_aggregation_status"] == "quarantined" for r in total_contests),
            "geographies_with_unspecified_mode":len(mode_geos.get("<BLANK>",set())),
            "blank_only_geographies":len(mode_geos.get("<BLANK>",set()) - nonblank_mode_geos),
            "vote_center_only_geographies":len(mode_geos.get("VOTE CENTER",set()) - (total_source_geos | mode_geos.get("<BLANK>",set()) | other_than_vote_center)),
            "unspecified_mode_contests":sum(r["result_mode"] == "UNSPECIFIED" for r in contests_2024),
            "geographies_without_explicit_total":len(all_source_geos - total_source_geos),
            "geographies_without_total_but_with_other_mode":len(other_modes_geos - total_source_geos),
            "geographies_with_other_source_modes":len(other_modes_geos),
            "nonmapping_source_geographies":len(mapping_geos),
            "availability_by_quality":dict(Counter(r["quality_status"] for r in office_availability)),
            "unspecified_mode_disposition":"quarantined; raw blank mode preserved; publisher semantics have not been verified; no party share or zero inferred",
        }
    outputs = {}
    for filename, rows in (("election_candidates.jsonl", candidates_out), ("election_contests.jsonl", contests_out), ("election_party_results.jsonl", shares_out), ("election_availability.jsonl", availability)):
        path = outdir / filename
        write_jsonl(path, rows)
        outputs[filename] = {"path": str(path), "sha256": sha256(path), "rows": len(rows)}
    return source_inventory, counts, coverage, outputs


def parse_acs(row, level, contract):
    geo_type, geo_id = {"us": ("nation", "US"), "state": ("state", str(row.get("state", "")).zfill(2)), "county": ("county", str(row.get("state", "")).zfill(2) + str(row.get("county", "")).zfill(3))}[level]
    raw_n, raw_nm = row.get("B02010_001E"), row.get("B02010_001M")
    raw_d, raw_dm = row.get("B01003_001E"), row.get("B01003_001M")
    n, denominator = strict_int(raw_n), strict_int(raw_d)
    special = {"-999999999", "-888888888", "-666666666"}
    if raw_n in special or raw_d in special:
        value_status, value = "suppressed", None
    elif n is None or denominator is None or n < 0 or denominator <= 0:
        value_status, value = "invalid", None
    else:
        value_status, value = "observed", round(n / denominator * 100, 8)
    mapping = "nonmapping_geography" if geo_type == "county" and geo_id in set(contract["nonmapping_source_geoids"]) else "mapped"
    quality = mapping if value_status == "observed" and mapping != "mapped" else value_status
    return {"observation_id": "aian-{}-{}-2020-2024".format(geo_type, geo_id), "dataset_id": "aian_broad_share", "field_id": "01.04:aian_share", "catalog_field_id": "01.04", "geo_id": geo_id, "geo_type": geo_type, "state_fips": geo_id[:2] if geo_type != "nation" else None, "district_code": None, "boundary_vintage": None, "congress_session": None, "is_at_large": False, "period_kind": "multi_year", "period_year": 2024, "period_month": None, "period_start_year": 2020, "period_end_year": 2024, "source_period_code": "2020-2024", "value": value, "unit": "percent", "quality_status": quality, "source_value_status": value_status, "geography_mapping_status": mapping, "raw_estimate": raw_n, "raw_estimate_moe": raw_nm, "raw_denominator": raw_d, "raw_denominator_moe": raw_dm, "denominator_value": denominator, "source": "U.S. Census Bureau ACS 2024 5-year", "source_release": "acs-2024-5year", "source_url": "https://api.census.gov/data/2024/acs/acs5", "source_sha256": None, "methodology_note": "B02010_001E / B01003_001E * 100 from the same ACS 2024 5-year product. Broad AIAN race includes all Hispanic origins and overlapping race responses. No derived share MOE.", "candidate_status": "local_review", "retrieved_at": "2026-10-25T11:36:37.121506+00:00"}


def prepare_aian(input_dir, outdir, contract):
    sources, outputs, all_rows = {}, {}, []
    for level, (relative, expected, expected_rows) in ACS_FILES.items():
        source = input_dir / relative
        if sha256(source) != expected:
            raise ValueError("ACS {} hash mismatch".format(level))
        rows, _ = read_csv_rows(source)
        if len(rows) != expected_rows:
            raise ValueError("ACS {} row count mismatch".format(level))
        normalized = []
        for source_row in rows:
            row = parse_acs(source_row, level, contract)
            row["source_sha256"] = expected
            normalized.append(row)
        output = outdir / "aian_{}.jsonl".format(level)
        write_jsonl(output, normalized)
        sources[level] = {"path": str(source), "sha256": expected, "rows": len(rows)}
        outputs[level] = {"path": str(output), "sha256": sha256(output), "rows": len(normalized)}
        all_rows.extend(normalized)
    combined = outdir / "reader_observations.jsonl"
    write_jsonl(combined, all_rows)
    outputs["reader_observations"] = {"path": str(combined), "sha256": sha256(combined), "rows": len(all_rows)}
    return sources, outputs


def validate_county_contract(path):
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("matching_rule") != "exact five-digit GEOID only; no allocation or predecessor geography substitutions":
        raise ValueError("unrecognized county geography contract")
    if len(contract.get("nonmapping_source_geoids", [])) != 11 or len(set(contract["nonmapping_source_geoids"])) != 11:
        raise ValueError("county geography contract must list 11 unique nonmapping source IDs")
    return contract


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=pathlib.Path, help="Prepared politics-native input root")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path, help="New/empty output directory; existing generated data is preserved")
    parser.add_argument("--county-geography-contract", required=True, type=pathlib.Path)
    boundary = parser.add_mutually_exclusive_group(required=True)
    boundary.add_argument("--boundary-zip", type=pathlib.Path)
    boundary.add_argument("--boundary-geojson", type=pathlib.Path)
    parser.add_argument("--boundary-geojson-sha256", help="Exact trusted SHA-256 required with --boundary-geojson")
    args = parser.parse_args(argv)
    if args.boundary_geojson and not args.boundary_geojson_sha256:
        parser.error("--boundary-geojson-sha256 is required with --boundary-geojson")
    outdir = args.output_dir.resolve()
    if outdir.exists() and any(outdir.iterdir()):
        parser.error("output directory must be new or empty")
    outdir.mkdir(parents=True, exist_ok=True)
    contract = validate_county_contract(args.county_geography_contract)
    boundary_ids, boundary_inventory = load_boundary(args, outdir)
    election_sources, election_counts, election_coverage, election_outputs = prepare_elections(args.input_dir, outdir, boundary_ids)
    aian_sources, aian_outputs = prepare_aian(args.input_dir, outdir, contract)
    inventory = {"candidate_status": "local_review_not_admitted", "collector_version": COLLECTOR_VERSION, "reader_contract_version": CONTRACT_VERSION, "field_ids": FIELD_IDS, "observation_releases": {key: value[5] for key, value in POLITICS_FILES.items()}, "source_status": {"president": "public metadata checksum/size match", "senate": "public direct-download size and SHA-256 verified; public metadata MD5 describes a distinct processed serialization", "house": "mirror original byte identity unverified; local review only; not production eligible"}, "sources": {"elections": election_sources, "aian": aian_sources}, "counts": election_counts, "coverage_2024": election_coverage, "outputs": {**election_outputs, **{"aian_{}".format(k): v for k, v in aian_outputs.items()}}, "boundary": boundary_inventory, "county_geography_contract_sha256": sha256(args.county_geography_contract), "controls": {"AIAN_US_7990799": "prepared source control only, not independent verification", "zero_policy": "party zero only for validated complete TOTAL contest; missing/no-election/quarantine remain NULL", "denominator_policy": "totalvotes repeated by source row is retained, checked for consistency, and stored once per contest", "unspecified_election_mode": "preserved as raw source mode and quarantined unless publisher semantics are independently verified"}}
    inventory_path = outdir / "reader-results.json"
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(outdir), "inventory": str(inventory_path), "inventory_sha256": sha256(inventory_path), "counts": election_counts}, indent=2))

if __name__ == "__main__":
    main()
