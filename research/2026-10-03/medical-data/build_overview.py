#!/usr/bin/env python3
"""Index separate medical research bundles without mixing their schemas."""
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def build():
    core = load("coverage.json")
    child = load("child-county/coverage-local.json")
    additional = load("additional-surveillance/coverage.json")
    hiv_preliminary = load("hiv-preliminary/coverage.json")
    combined = []
    for metric in load("metric-inventory.json")["metrics"]:
        combined.append({
            "bundle": "core", "metric_id": metric["metric_id"],
            "period": "|".join(metric["periods"]), "release": "source_specific",
            "universe_or_age_group": metric.get("definition"),
            "finest_collected": metric["finest_collected"],
            "county_numeric_rows": metric.get("county_numeric_rows", 0),
            "state_numeric_rows": metric.get("state_numeric_rows", 0),
            "source_state_numeric_rows": metric.get("state_numeric_rows", 0),
            "country_numeric_rows": 0,
            "unit": metric.get("unit"), "source_urls": "|".join(metric["source_urls"]),
            "record_path": "normalized/observations.csv", "reason_missing": metric["reason_missing"],
        })
    numeric = Counter()
    child_rows = Counter()
    examples = {}
    with (ROOT / "child-county/observations.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["release"], row["metric_id"])
            child_rows[key] += 1
            numeric[key] += row["value_status"] == "numeric"
            examples.setdefault(key, row)
    for (release, metric_id), row in sorted(examples.items()):
        combined.append({
            "bundle": "child-county", "metric_id": metric_id,
            "period": row["period"], "release": release,
            "universe_or_age_group": row["age_group"], "finest_collected": "county",
            "county_numeric_rows": numeric[(release, metric_id)],
            "state_numeric_rows": 0,
            "source_state_numeric_rows": child["series"][release]["state_numeric_rates"],
            "country_numeric_rows": 0,
            "unit": row["unit"], "source_urls": row["source_url"],
            "record_path": "child-county/observations.csv",
            "reason_missing": "Published suppressed/blank cells and source geography vintage retained. State rows remain in raw; under18 and under20 are distinct definitions.",
        })
    for metric in additional["metric_coverage"]:
        source_periods = metric["periods"]
        release = "CDC STI surveillance 2024 provisional" if metric["metric_id"].startswith(("sti_", "syphilis_")) else "CDC TB reporting-area table 2024"
        combined.append({
            "bundle": "additional-surveillance", "metric_id": metric["metric_id"],
            "period": "|".join(source_periods), "release": release,
            "universe_or_age_group": metric.get("definition"),
            "finest_collected": metric.get("finest_collected"),
            "county_numeric_rows": metric.get("county_numeric_rows", 0),
            "state_numeric_rows": metric.get("state_numeric_rows", 0),
            "source_state_numeric_rows": metric.get("state_numeric_rows", 0),
            "country_numeric_rows": metric.get("country_numeric_rows", 0),
            "unit": "|".join(metric.get("units", [])),
            "source_urls": "|".join(metric.get("source_urls", [])),
            "record_path": "additional-surveillance/observations.csv",
            "reason_missing": metric.get("reason_missing"),
        })
    hiv_counts = Counter()
    with (ROOT / "hiv-preliminary/observations.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["value_status"] == "numeric":
                hiv_counts[row["geography_level"]] += 1
    combined.append({
        "bundle": "hiv-preliminary", "metric_id": hiv_preliminary["metric_id"],
        "period": "2025|2026-01_to_2026-06",
        "release": "CDC EHE preliminary diagnoses through June 2026",
        "universe_or_age_group": "Reported HIV diagnoses among persons aged 13 years and older; date of diagnosis; residence at diagnosis",
        "finest_collected": "selected county/county-equivalent (EHE priority jurisdictions) and San Juan Municipio",
        "county_numeric_rows": hiv_counts["county"],
        "municipality_numeric_rows": hiv_counts["municipality"],
        "state_numeric_rows": hiv_counts["state"],
        "source_state_numeric_rows": hiv_counts["state"],
        "territory_numeric_rows": hiv_counts["territory"],
        "country_numeric_rows": hiv_counts["national"] + hiv_counts["national_plus_territories"] + hiv_counts["territory_group"],
        "unit": "reported_diagnoses",
        "source_urls": "https://stacks.cdc.gov/view/cdc/260354|https://stacks.cdc.gov/view/cdc/260354/cdc_260354_DS1.xlsx",
        "record_path": "hiv-preliminary/observations.csv",
        "reason_missing": "2026 covers January-June only and is preliminary. County values exist only for selected EHE areas; other Census county equivalents are explicitly listed as not in this release. No rates, denominators, tract, or block-group values are provided.",
    })
    with (ROOT / "all-metric-inventory.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(dict.fromkeys(key for row in combined for key in row))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(combined)
    overview = {
        "created_at": datetime.now(timezone.utc).isoformat(), "production_admitted": False,
        "core": {"observations": core["observations"], "numeric": core["numeric"],
                 "missing_or_suppressed": core["missing_or_suppressed"], "inventory_metrics": core["metrics"],
                 "records": "normalized/observations.csv", "coverage": "coverage.json"},
        "child_county": {"county_observations": sum(child_rows.values()), "county_numeric": sum(numeric.values()),
                         "state_rows": "retained_in_raw_not_normalized", "records": "child-county/observations.csv",
                         "coverage": "child-county/coverage-local.json",
                         "series": [{key: series[key] for key in ["age_group", "period", "county_numeric_rates", "state_numeric_rates"]} for series in child["series"].values()]},
        "additional_surveillance": {
            "observations": additional["records"], "numeric": additional["numeric"],
            "missing_or_suppressed": additional["missing_or_suppressed"],
            "inventory_metrics": additional["metrics"],
            "records": "additional-surveillance/observations.csv",
            "coverage": "additional-surveillance/coverage.json",
            "no_county_values": True,
            "source_limitations": additional["source_limitations"],
        },
        "hiv_preliminary": {
            "observations": hiv_preliminary["records"], "numeric": hiv_preliminary["numeric"],
            "missing_or_suppressed": hiv_preliminary["missing_or_suppressed"],
            "metric_id": hiv_preliminary["metric_id"],
            "records": "hiv-preliminary/observations.csv",
            "coverage": "hiv-preliminary/coverage.json",
            "source_limitations": hiv_preliminary["source_limitations"],
        },
        "combined_inventory": "all-metric-inventory.csv",
        "combined_unique_metric_ids": len({m["metric_id"] for m in combined}),
        "numeric_observation_cells_across_bundles": core["numeric"] + sum(numeric.values()) + additional["numeric"] + hiv_preliminary["numeric"],
        "note": "Observation cells across metrics/periods/geographies are not unique patients or a pooled disease total. Core, observed child-county, additional-surveillance, and preliminary-HIV bundle schemas and age/period/geography ranges remain explicit.",
    }
    (ROOT / "research-overview.json").write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metric_ids": overview["combined_unique_metric_ids"], "numeric_cells": overview["numeric_observation_cells_across_bundles"]}))


if __name__ == "__main__":
    build()
