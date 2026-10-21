#!/usr/bin/env python3
"""Build the approved 2017-2021 housing-stock artifact from ACS 5-year data."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import sys
import urllib.parse
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect  # noqa: E402


CONTRACT_PATH = HERE / "housing-stock-2021-contract.json"
METRICS_PATH = HERE / "housing-stock-2021-metrics.json"
OUTPUT_PATH = HERE / "normalized" / "housing_stock_2021.jsonl.gz"
MANIFEST_PATH = HERE / "normalized" / "housing_stock_2021.manifest.json"
RAW_DIR = HERE / "raw" / "housing_stock_2021"
SENTINELS = {-555555555, -222222222, -333333333, -666666666, -888888888, -999999999}


def as_number(value: object) -> int | float | None:
    text = str(value).strip()
    if text in {"", "**", "null", "None", "N"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number in SENTINELS:
        return None
    return int(number) if number.is_integer() else number


def save_raw(name: str, payload: bytes) -> dict:
    cleaned = collect.safety.sanitize_data(json.loads(payload))
    encoded = (json.dumps(cleaned, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    compressed = gzip.compress(encoded, compresslevel=6, mtime=0)
    path = RAW_DIR / f"{name}.json.gz"
    collect.atomic_write(path, compressed)
    return {
        "path": str(path.relative_to(HERE)),
        "sha256": collect.sha256(compressed),
        "bytes": len(compressed),
    }


def fetch_table(session: collect.Session, url: str, name: str) -> tuple[list[list[str]], dict]:
    payload = session.request(url)
    artifact = save_raw(name, payload)
    table = json.loads(payload)
    if not isinstance(table, list) or not table or not all(isinstance(row, list) for row in table):
        raise collect.CollectionError("census_schema_error")
    return table, artifact


def fetch_universes(session: collect.Session, contract: dict) -> tuple[dict, list[dict]]:
    checks = {}
    raw_inputs = []
    base = contract["source_selector"]
    for table_id, expected in contract["source_tables"].items():
        url = f"{base}/groups/{table_id}.json"
        payload = session.request(url)
        raw_inputs.append(save_raw(f"group-{table_id}", payload))
        metadata = json.loads(payload)
        variable = metadata.get("variables", {}).get(f"{table_id}_001E", {})
        actual = {
            "concept": variable.get("concept"),
            "universe": variable.get("universe"),
        }
        passed = (
            actual["concept"] == expected["concept"]
            and actual["universe"] == expected["universe"]
        )
        checks[table_id] = {
            **actual,
            "expected_concept": expected["concept"],
            "expected_universe": expected["universe"],
            "pass": passed,
        }
        if not passed:
            raise collect.CollectionError(f"universe_mismatch:{table_id}")
    return checks, raw_inputs


def query_url(contract: dict, key: str, geo_type: str) -> str:
    params = {
        "get": "NAME," + ",".join(contract["source_variables"]),
        "key": key,
    }
    if geo_type == "nation":
        params["for"] = "us:1"
    elif geo_type == "state":
        params["for"] = "state:*"
    elif geo_type == "county":
        params["for"] = "county:*"
    else:
        raise ValueError(geo_type)
    return contract["source_selector"] + "?" + urllib.parse.urlencode(params)


def parse_rows(table: list[list[str]], contract: dict, geo_type: str,
               source_url: str) -> tuple[list[dict], list[str]]:
    header = table[0]
    required = {"NAME", *contract["source_variables"]}
    missing_header = sorted(required - set(header))
    if missing_header:
        raise collect.CollectionError("missing_header:" + ",".join(missing_header))
    index = {name: position for position, name in enumerate(header)}
    excluded = set(contract["excluded_state_fips"])
    records = []
    missing_geographies = []
    for row in table[1:]:
        state = row[index["state"]] if "state" in index else None
        if geo_type in {"state", "county"} and state in excluded:
            continue
        if geo_type == "nation":
            geo_id = "US"
        elif geo_type == "state":
            geo_id = state
        else:
            geo_id = state + row[index["county"]]
        source_values = {}
        missing = []
        for variable in contract["source_variables"]:
            number = as_number(row[index[variable]])
            source_values[variable] = number
            if number is None:
                missing.append(variable)
        record = {
            "schema_version": 1,
            "artifact_id": contract["contract_id"],
            "geo_id": geo_id,
            "geo_type": geo_type,
            "geo_name": row[index["NAME"]],
            "catalog_field_id": contract["parent_catalog_field_id"],
            "year": contract["acs_year"],
            "period": contract["period"],
            "display_period": contract["display_period"],
            "source": contract["source"],
            "source_release": contract["source_release"],
            "source_url": collect.safety.canonical_url(source_url),
            "source_fields": list(contract["source_variables"]),
            "source_values": source_values,
        }
        if missing:
            missing_geographies.append(geo_id)
            record["missing_source_fields"] = missing
        records.append(record)
    return records, missing_geographies


def aggregate_alaska(records: list[dict], contract: dict) -> dict | None:
    spec = contract["alaska_aggregation"]
    source_ids = spec["source_geo_ids"]
    by_id = {record["geo_id"]: record for record in records if record["geo_type"] == "county"}
    missing = [geo_id for geo_id in source_ids if geo_id not in by_id]
    if missing:
        raise collect.CollectionError("alaska_sources_missing:" + ",".join(missing))
    sources = [by_id[geo_id] for geo_id in source_ids]
    values = {}
    for variable in contract["source_variables"]:
        parts = [record["source_values"][variable] for record in sources]
        if variable.endswith("E"):
            values[variable] = sum(parts)
        else:
            values[variable] = math.sqrt(sum(part * part for part in parts))
    aggregated = {
        "schema_version": 1,
        "artifact_id": contract["contract_id"],
        "geo_id": spec["target_geo_id"],
        "geo_type": "county",
        "geo_name": spec["target_name"],
        "catalog_field_id": contract["parent_catalog_field_id"],
        "year": contract["acs_year"],
        "period": contract["period"],
        "display_period": contract["display_period"],
        "source": contract["source"],
        "source_release": contract["source_release"],
        "source_url": sources[0]["source_url"],
        "source_fields": list(contract["source_variables"]),
        "source_values": values,
        "alaska_aggregation": {
            "source_geo_ids": source_ids,
            "source_names": spec["source_names"],
            "estimate_method": spec["estimate_method"],
            "moe_method": spec["moe_method"],
            "share_method": spec["share_method"],
            "geometry_check": spec["geometry_check"],
        },
    }
    kept = [record for record in records if record["geo_id"] not in source_ids]
    kept.append(aggregated)
    records[:] = kept
    return aggregated


def add_counts_and_metrics(record: dict, indicators: list[dict]) -> None:
    values = record["source_values"]
    record["counts"] = {
        "total_housing_units": {
            "estimate": values["B25001_001E"],
            "moe": values["B25001_001M"],
        },
        "occupied_housing_units": {
            "estimate": values["B25002_002E"],
            "moe": values["B25002_002M"],
        },
        "vacant_housing_units": {
            "estimate": values["B25002_003E"],
            "moe": values["B25002_003M"],
        },
        "owner_occupied_housing_units": {
            "estimate": values["B25003_002E"],
            "moe": values["B25003_002M"],
        },
        "renter_occupied_housing_units": {
            "estimate": values["B25003_003E"],
            "moe": values["B25003_003M"],
        },
    }
    metrics = {}
    for indicator in indicators:
        numerator = values[indicator["numerator"]]
        denominator = values[indicator["denominator"]]
        if denominator is None or denominator <= 0:
            raise collect.CollectionError(f"nonpositive_denominator:{record['geo_id']}")
        shared = {
            "label": indicator["label"],
            "unit": indicator["unit"],
            "value": round(numerator / denominator * 100, 4),
            "numerator": numerator,
            "denominator": denominator,
            "numerator_moe": values[indicator["numeratorMoe"]],
            "denominator_moe": values[indicator["denominatorMoe"]],
            "method": indicator["method"],
            "decimals": indicator["decimals"],
            "min_denominator": indicator["minDenominator"],
        }
        metrics[indicator["id"]] = shared
    record["metrics"] = metrics


def validate_records(records: list[dict], contract: dict, indicators: list[dict]) -> dict:
    expected = contract["expected_counts"]
    counts = Counter(record["geo_type"] for record in records)
    failures = []
    missing = []
    rounded_share_deviations = []
    for record in records:
        if record.get("missing_source_fields"):
            missing.append({"geo_id": record["geo_id"], "fields": record["missing_source_fields"]})
            continue
        values = record["source_values"]
        checks = {
            "housing_totals_agree": values["B25001_001E"] == values["B25002_001E"],
            "occupied_plus_vacant": values["B25002_002E"] + values["B25002_003E"] == values["B25002_001E"],
            "tenure_total_equals_occupied": values["B25003_001E"] == values["B25002_002E"],
            "owner_plus_renter": values["B25003_002E"] + values["B25003_003E"] == values["B25003_001E"],
        }
        for name, passed in checks.items():
            if not passed:
                failures.append({"geo_id": record["geo_id"], "check": name})
        for variable in contract["source_variables"]:
            if variable.endswith("M") and values[variable] is not None and values[variable] < 0:
                failures.append({"geo_id": record["geo_id"], "check": "negative_moe", "field": variable})
        share_sum = sum(record["metrics"][indicator["id"]]["value"] for indicator in indicators)
        if abs(share_sum - 100.0) > 0.001:
            failures.append({"geo_id": record["geo_id"], "check": "share_sum", "value": share_sum})
        rounded_share_deviations.append(
            abs(sum(round(record["metrics"][indicator["id"]]["value"], 1) for indicator in indicators) - 100.0)
        )
    us = next((record for record in records if record["geo_type"] == "nation"), None)
    count_fields = [
        "total_housing_units", "occupied_housing_units", "vacant_housing_units",
        "owner_occupied_housing_units", "renter_occupied_housing_units",
    ]
    county_counts_match = {}
    state_counts_match = {}
    if us is not None:
        for field in count_fields:
            county_sum = sum(
                record["counts"][field]["estimate"]
                for record in records if record["geo_type"] == "county"
            )
            state_sum = sum(
                record["counts"][field]["estimate"]
                for record in records if record["geo_type"] == "state"
            )
            county_counts_match[field] = county_sum == us["counts"][field]["estimate"]
            state_counts_match[field] = state_sum == us["counts"][field]["estimate"]
            if not county_counts_match[field]:
                failures.append({"geo_id": "US", "check": "county_counts_sum", "field": field})
            if not state_counts_match[field]:
                failures.append({"geo_id": "US", "check": "state_counts_sum", "field": field})
    county_ids = {record["geo_id"] for record in records if record["geo_type"] == "county"}
    state_ids = {record["geo_id"] for record in records if record["geo_type"] == "state"}
    checks = {
        "counts": {key: counts.get(key, 0) for key in expected},
        "counts_match": all(counts.get(key, 0) == value for key, value in expected.items()),
        "puerto_rico_rows": sum(
            1 for record in records
            if record["geo_type"] in {"state", "county"} and record["geo_id"].startswith("72")
        ),
        "connecticut_counties": sum(1 for geo_id in county_ids if geo_id.startswith("09")),
        "alaska_counties": sum(1 for geo_id in county_ids if geo_id.startswith("02")),
        "alaska_split_sources_present": bool({"02063", "02066"} & county_ids),
        "alaska_02261_present": "02261" in county_ids,
        "nation_present": "US" in {record["geo_id"] for record in records},
        "county_counts_match_us": county_counts_match,
        "state_counts_match_us": state_counts_match,
        "max_rounded_share_deviation": max(rounded_share_deviations) if rounded_share_deviations else None,
        "missing": missing,
        "failures": failures,
    }
    if missing or failures:
        raise collect.CollectionError(
            "validation_failed:" + json.dumps({"missing": missing, "failures": failures[:20]})
        )
    if not checks["counts_match"] or checks["puerto_rico_rows"]:
        raise collect.CollectionError("validation_failed:geography_counts")
    if checks["alaska_split_sources_present"] or not checks["alaska_02261_present"]:
        raise collect.CollectionError("validation_failed:alaska_aggregation")
    return checks


def validate_boundaries(records: list[dict], manifest_path: Path) -> dict:
    manifest = collect.load_json(manifest_path)
    root = manifest_path.parent
    boundary_ids = set()
    for state in manifest["states"]:
        collection = collect.load_json(root / f"{state['id']}.json")
        boundary_ids.update(feature["id"] for feature in collection["features"])
    artifact_ids = {
        record["geo_id"] for record in records if record["geo_type"] == "county"
    }
    missing = sorted(boundary_ids - artifact_ids)
    extra = sorted(artifact_ids - boundary_ids)
    result = {
        "manifest": str(manifest_path),
        "boundary_states": len(manifest["states"]),
        "boundary_counties": len(boundary_ids),
        "artifact_counties": len(artifact_ids),
        "missing": missing,
        "extra": extra,
        "pass": not missing and not extra and len(boundary_ids) == len(artifact_ids),
    }
    if not result["pass"]:
        raise collect.CollectionError("boundary_mismatch")
    return result


def county_stats(records: list[dict], indicators: list[dict]) -> dict:
    counties = [record for record in records if record["geo_type"] == "county"]
    result = {}
    for indicator in indicators:
        values = [record["metrics"][indicator["id"]]["value"] for record in counties]
        low = min(counties, key=lambda record: record["metrics"][indicator["id"]]["value"])
        high = max(counties, key=lambda record: record["metrics"][indicator["id"]]["value"])
        result[indicator["id"]] = {
            "min": round(min(values), 4),
            "median": round(statistics.median(values), 4),
            "max": round(max(values), 4),
            "min_geo": {"geo_id": low["geo_id"], "geo_name": low["geo_name"]},
            "max_geo": {"geo_id": high["geo_id"], "geo_name": high["geo_name"]},
        }
    return result


def sample_geography(records: list[dict], geo_id: str, indicators: list[dict]) -> dict:
    record = next(record for record in records if record["geo_id"] == geo_id)
    return {
        "geo_id": record["geo_id"],
        "geo_name": record["geo_name"],
        "counts": record["counts"],
        "metrics": {
            indicator["id"]: record["metrics"][indicator["id"]]
            for indicator in indicators
        },
    }


def build_report(records: list[dict], contract: dict, indicators: list[dict],
                 checks: dict, universes: dict, raw_inputs: list[dict],
                 session_metrics: dict, artifact: dict,
                 boundary_validation: dict | None = None) -> dict:
    counties = [record for record in records if record["geo_type"] == "county"]
    eligible = [
        record for record in counties
        if 1000 <= record["counts"]["total_housing_units"]["estimate"] <= 5000
    ]
    owner_id = "02.07:owner_occupied_share_all_units"
    vacant_id = "02.07:vacant_share_all_units"
    high_owner = max(eligible, key=lambda record: record["metrics"][owner_id]["value"])
    high_vacant = max(eligible, key=lambda record: record["metrics"][vacant_id]["value"])
    alaska = next(record for record in counties if record["geo_id"] == "02261")
    us = next(record for record in records if record["geo_type"] == "nation")
    alaska_values = {
        "owner": alaska["metrics"][owner_id]["value"],
        "renter": alaska["metrics"]["02.07:renter_occupied_share_all_units"]["value"],
        "vacant": alaska["metrics"][vacant_id]["value"],
    }
    return {
        "county_share_stats": county_stats(records, indicators),
        "samples": {
            "san_francisco": sample_geography(records, "06075", indicators),
            "los_angeles": sample_geography(records, "06037", indicators),
            "high_owner_rural": {
                "rule": "county total housing units 1,000-5,000 (rural proxy)",
                "geo_id": high_owner["geo_id"],
                "geo_name": high_owner["geo_name"],
                "total_housing_units": high_owner["counts"]["total_housing_units"],
                "owner_share": high_owner["metrics"][owner_id]["value"],
            },
            "high_vacancy": {
                "rule": "county total housing units 1,000-5,000 (rural proxy)",
                "geo_id": high_vacant["geo_id"],
                "geo_name": high_vacant["geo_name"],
                "total_housing_units": high_vacant["counts"]["total_housing_units"],
                "vacant_share": high_vacant["metrics"][vacant_id]["value"],
            },
        },
        "nation": {
            "geo_id": us["geo_id"],
            "counts": us["counts"],
            "metrics": {
                indicator["id"]: us["metrics"][indicator["id"]]
                for indicator in indicators
            },
        },
        "alaska_02261": {
            "geo_id": alaska["geo_id"],
            "geo_name": alaska["geo_name"],
            "counts": alaska["counts"],
            "shares": alaska_values,
            "source_geo_ids": contract["alaska_aggregation"]["source_geo_ids"],
            "geometry_check": contract["alaska_aggregation"]["geometry_check"],
        },
        "api_validation": {
            "county_rows": checks["counts"]["county"],
            "state_rows": checks["counts"]["state"],
            "nation_rows": checks["counts"]["nation"],
            "missing_estimate_or_moe": len(checks["missing"]),
            "arithmetic_or_share_failures": len(checks["failures"]),
            "puerto_rico_rows": checks["puerto_rico_rows"],
            "connecticut_counties": checks["connecticut_counties"],
            "alaska_counties_after_aggregation": checks["alaska_counties"],
            "source_response_rows": checks["response_rows"],
            "release_counties_before_aggregation": checks["release_counties_before_aggregation"],
            "county_counts_equal_us": all(checks["county_counts_match_us"].values()),
            "state_counts_equal_us": all(checks["state_counts_match_us"].values()),
            "max_rounded_share_deviation": checks["max_rounded_share_deviation"],
        },
        "universes": universes,
        "boundary_validation": boundary_validation,
        "raw_inputs": raw_inputs,
        "requests": session_metrics,
        "artifact": artifact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--metrics", type=Path, default=METRICS_PATH)
    parser.add_argument("--boundary-manifest", type=Path, default=None)
    args = parser.parse_args()
    collect.safety.load_credentials()
    key = os.getenv("CENSUS_API_KEY")
    if not key:
        raise collect.CollectionError("credential_required:CENSUS_API_KEY")
    contract = collect.load_json(args.contract)
    metrics = collect.load_json(args.metrics)
    if contract["source_variables"] != [
        variable
        for table in contract["source_tables"].values()
        for variable in table["variables"]
    ]:
        raise collect.CollectionError("source_variable_order_mismatch")
    retrieved_at = collect.now()
    session = collect.Session("census_acs", calibration=False)
    universes, raw_inputs = fetch_universes(session, contract)
    records = []
    response_rows = {}
    for geo_type, name in (("nation", "us"), ("state", "states"), ("county", "counties")):
        url = query_url(contract, key, geo_type)
        table, artifact = fetch_table(session, url, name)
        raw_inputs.append(artifact)
        response_rows[geo_type] = len(table) - 1
        parsed, missing = parse_rows(table, contract, geo_type, url)
        if missing:
            raise collect.CollectionError("missing_source_values:" + json.dumps(missing))
        records.extend(parsed)
    source_counties = len([record for record in records if record["geo_type"] == "county"])
    aggregate_alaska(records, contract)
    for record in records:
        add_counts_and_metrics(record, metrics["indicators"])
    checks = validate_records(records, contract, metrics["indicators"])
    checks["response_rows"] = response_rows
    checks["release_counties_before_aggregation"] = source_counties
    boundary_validation = (
        validate_boundaries(records, args.boundary_manifest)
        if args.boundary_manifest is not None else None
    )
    records.sort(key=lambda record: ({"nation": 0, "state": 1, "county": 2}[record["geo_type"]], record["geo_id"]))
    encoded = b"".join(
        (json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        for record in records
    )
    compressed = gzip.compress(encoded, compresslevel=6, mtime=0)
    collect.atomic_write(OUTPUT_PATH, compressed)
    artifact = {
        "path": str(OUTPUT_PATH.relative_to(HERE)),
        "sha256": collect.sha256(compressed),
        "bytes": len(compressed),
        "rows": len(records),
        "uncompressed_bytes": len(encoded),
        "record_grain": contract["artifact"]["record_grain"],
    }
    report = build_report(
        records, contract, metrics["indicators"], checks, universes,
        raw_inputs, session.metrics(), artifact, boundary_validation,
    )
    manifest = {
        "schema_version": 1,
        "artifact_id": contract["contract_id"],
        "status": "pass",
        "generated_at": retrieved_at,
        "retrieved_at": retrieved_at,
        "contract_id": contract["contract_id"],
        "source": contract["source"],
        "source_release": contract["source_release"],
        "period": contract["period"],
        "display_period": contract["display_period"],
        "source_selector": contract["source_selector"],
        "geography": {
            "nation": checks["counts"]["nation"],
            "state": checks["counts"]["state"],
            "county": checks["counts"]["county"],
            "excluded_state_fips": contract["excluded_state_fips"],
            "boundary_vintage": "2017",
        },
        "alaska_aggregation_note": metrics["indicators"][0]["method"].split(" 100. ", 1)[-1],
        "indicators": metrics["indicators"],
        "artifact": artifact,
        "report": report,
    }
    collect.write_json(MANIFEST_PATH, manifest)
    print(json.dumps({
        "status": "pass",
        "artifact": artifact,
        "manifest": str(MANIFEST_PATH.relative_to(HERE)),
        "api_validation": report["api_validation"],
        "alaska_02261": report["alaska_02261"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "fail", "reason": collect.safe_reason(error)}), file=sys.stderr)
        raise SystemExit(1)
