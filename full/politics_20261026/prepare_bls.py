"""Normalize an explicitly pinned local BLS LAUS 2025 NSA collection for reader-v2."""
import argparse
import csv
import hashlib
import json
import pathlib

MEASURES = {
    "03": ("unemployment_rate", "03.06:unemployment_rate", "unemployment", "%"),
    "04": ("unemployed", "03.06:unemployed", "unemployment_components", "persons"),
    "05": ("employed", "03.06:employed", "unemployment_components", "persons"),
    "06": ("labor_force", "03.06:labor_force", "unemployment_components", "persons"),
}
SOURCE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
SOURCE_RELEASE = "laus-nsa-2025"
SOURCE_VERSION = "laus-nsa-2025-v2"


def digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_period(period_type, period, raw_code):
    if period_type == "annual" and raw_code == "M13" and period == "2025":
        return "annual", 2025, None, 2025, 2025, "2025-M13"
    if period_type == "monthly" and raw_code in {"M%02d" % month for month in range(1, 13)}:
        year, month = period.split("-")
        if int(year) != 2025 or int(month) != int(raw_code[1:]):
            raise ValueError("BLS month columns disagree")
        return "monthly", 2025, int(month), 2025, 2025, "2025-" + raw_code
    raise ValueError("unexpected BLS period identity")


def normalize(observed_path, missingness_path, results_path, output_dir,
              expected_observed_sha256, expected_missingness_sha256, expected_results_sha256):
    observed_path = pathlib.Path(observed_path).resolve()
    missingness_path = pathlib.Path(missingness_path).resolve()
    results_path = pathlib.Path(results_path).resolve()
    output_dir = pathlib.Path(output_dir).resolve()
    if digest(observed_path) != expected_observed_sha256:
        raise ValueError("BLS prepared observations hash mismatch")
    if digest(missingness_path) != expected_missingness_sha256:
        raise ValueError("BLS missingness hash mismatch")
    if digest(results_path) != expected_results_sha256:
        raise ValueError("BLS collection results hash mismatch")
    result_manifest = json.loads(results_path.read_text())
    result = result_manifest["result"]
    if (result.get("completedBatchCount") != 256 or result.get("batchCount") != 256 or
            result.get("pendingSeriesCount") != 0 or result.get("seriesCount") != 12780 or
            result.get("observedRows") != 153312 or result.get("missingnessRows") != 12828):
        raise ValueError("BLS collection is not the reviewed completed full run")
    if result.get("status") != "partial":
        raise ValueError("BLS source gaps must remain classified as partial")

    series_provenance = {}
    for artifact in result.get("rawArtifacts", []):
        raw_path = pathlib.Path(artifact["path"])
        if not raw_path.is_file() or digest(raw_path) != artifact["sha256"]:
            raise ValueError("a referenced BLS raw response is missing or corrupt")
        payload = json.loads(raw_path.read_text())
        response_series = payload.get("Results", {}).get("series", [])
        if not response_series:
            response_series = payload.get("results", {}).get("series", [])
        for series in response_series:
            series_id = series.get("seriesID") or series.get("seriesId")
            if series_id:
                series_provenance[series_id] = artifact

    rows = []
    latest_retrieved = None
    with observed_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            code = row["measure_code"]
            if code not in MEASURES:
                raise ValueError("unexpected LAUS measure code")
            metric, field_id, dataset_id, unit = MEASURES[code]
            artifact = series_provenance.get(row["series_id"])
            if artifact is None:
                raise ValueError("BLS series lacks a verified raw response reference")
            kind, year, month, start, end, source_period = canonical_period(
                row["period_type"], row["period"], row["bls_period_code"])
            quality = "observed" if row["status"] == "observed" and row["value"] not in ("", "-") else "missing"
            value = float(row["value"]) if quality == "observed" else None
            if value is not None and (value < 0 or (unit == "%" and value > 100)):
                quality, value = "invalid", None
            if row["geo_type"] not in ("state", "county"):
                raise ValueError("unexpected BLS geography type")
            rows.append({
                "dataset_id": dataset_id, "field_id": field_id, "catalog_field_id": "03.06",
                "geo_id": row["geo_id"], "geo_type": row["geo_type"],
                "state_fips": row["geo_id"][:2], "district_code": None,
                "boundary_vintage": None, "congress_session": None, "is_at_large": False,
                "period_kind": kind, "period_year": year, "period_month": month,
                "period_start_year": start, "period_end_year": end,
                "source_period_code": source_period, "value": value, "unit": unit,
                "quality_status": quality,
                "source_value_status": "observed" if quality == "observed" else quality,
                "geography_mapping_status": "mapped", "raw_estimate": row["raw_value"],
                "raw_estimate_moe": None, "raw_denominator": None, "raw_denominator_moe": None,
                "denominator_value": None, "source": "bls_laus", "source_release": SOURCE_RELEASE,
                "source_url": SOURCE_URL, "source_sha256": artifact["sha256"],
                "methodology_note": "BLS LAUS 2025 not seasonally adjusted; series=" + row["series_id"] +
                    "; measure=" + metric + "; source_period=" + row["bls_period_code"] +
                    ("; footnote=" + row["footnote"] if row["footnote"] else ""),
                "retrieved_at": artifact["retrievedAt"], "source_series_id": row["series_id"],
                "source_measure_code": code, "source_period_raw": row["bls_period_code"],
                "source_status": row["status"], "source_version": SOURCE_VERSION,
            })
    if len(rows) != result["observedRows"]:
        raise ValueError("observed row count does not match completed collection report")

    for line in missingness_path.read_text().splitlines():
        source = json.loads(line)
        code = source["measure_code"]
        if code not in MEASURES:
            raise ValueError("unexpected missing LAUS measure code")
        metric, field_id, dataset_id, unit = MEASURES[code]
        artifact = series_provenance.get(source["series_id"])
        if artifact is None:
            raise ValueError("BLS missing series lacks a verified raw response reference")
        kind, year, month, start, end, source_period = canonical_period(
            source["period_type"], source["period"], source["bls_period_code"])
        rows.append({
            "dataset_id": dataset_id, "field_id": field_id, "catalog_field_id": "03.06",
            "geo_id": source["geo_id"], "geo_type": source["geo_type"],
            "state_fips": source["geo_id"][:2], "district_code": None,
            "boundary_vintage": None, "congress_session": None, "is_at_large": False,
            "period_kind": kind, "period_year": year, "period_month": month,
            "period_start_year": start, "period_end_year": end,
            "source_period_code": source_period, "value": None, "unit": unit,
            "quality_status": "missing", "source_value_status": "missing",
            "geography_mapping_status": "mapped", "raw_estimate": source.get("raw_value"),
            "raw_estimate_moe": None, "raw_denominator": None, "raw_denominator_moe": None,
            "denominator_value": None, "source": "bls_laus", "source_release": SOURCE_RELEASE,
            "source_url": SOURCE_URL, "source_sha256": artifact["sha256"],
            "methodology_note": "BLS LAUS 2025 NSA explicit source gap; series=" + source["series_id"] +
                "; measure=" + metric + "; source_period=" + source["bls_period_code"] +
                "; source_status=" + source["status"] + "; footnote=" + source.get("footnote", ""),
            "retrieved_at": artifact["retrievedAt"], "source_series_id": source["series_id"],
            "source_measure_code": code, "source_period_raw": source["bls_period_code"],
            "source_status": source["status"], "source_version": SOURCE_VERSION,
        })
    if len(rows) != result["observedRows"] + result["missingnessRows"]:
        raise ValueError("observed and missingness rows do not match collection report")

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "bls_observations.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            row["observation_id"] = "bls-" + hashlib.sha256(
                (row["dataset_id"] + "|" + row["field_id"] + "|" + row["geo_type"] + "|" +
                 row["geo_id"] + "|" + row["source_period_code"] + "|" + row["source_version"]).encode()
            ).hexdigest()
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    artifacts = result.get("rawArtifacts", [])
    manifest = {
        "candidate_status": "local_review_not_admitted", "source_release": SOURCE_RELEASE,
        "source_version": SOURCE_VERSION, "collector_version": result_manifest["executedSourceSha256"],
        "contract_version": "2.0.0-candidate", "source_code": "bls_laus",
        "seasonal_adjustment": "NSA", "source_url": SOURCE_URL,
        "source_status": "collection_complete_with_source_gaps",
        "input_hashes": {"observed_csv": expected_observed_sha256,
                         "missingness_jsonl": expected_missingness_sha256,
                         "collection_results": expected_results_sha256},
        "raw_artifact_hashes": sorted({a["sha256"] for a in artifacts}),
        "observed_row_count": result["observedRows"], "missingness_row_count": result["missingnessRows"],
        "normalized_row_count": len(rows), "output": {"path": str(output), "sha256": digest(output)},
        "measure_codes": {code: values[0] for code, values in MEASURES.items()},
        "annual_m13": "period_kind=annual, period_month=null, period_year=2025, source_period_code=2025-M13",
        "gaps": {"M10": 12776, "period_not_returned": 52},
        "nation_rate": "not synthesized; no national LAUS rate in this input",
    }
    manifest_path = output_dir / "bls-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-csv", required=True, type=pathlib.Path)
    parser.add_argument("--missingness-jsonl", required=True, type=pathlib.Path)
    parser.add_argument("--collection-results", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--expected-observed-sha256", required=True)
    parser.add_argument("--expected-missingness-sha256", required=True)
    parser.add_argument("--expected-results-sha256", required=True)
    args = parser.parse_args()
    print(normalize(args.observed_csv, args.missingness_jsonl, args.collection_results,
                    args.output_dir, args.expected_observed_sha256,
                    args.expected_missingness_sha256, args.expected_results_sha256))


if __name__ == "__main__":
    main()
