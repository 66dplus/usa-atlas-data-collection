#!/usr/bin/env python3
"""Fetch Census PEP single-age county files and derive an auditable 1-4 denominator table.

The Census release is one static CSV per state/territory code (not a paginated
API). Requests are sequential and bounded; successful raw files are reused on
subsequent runs. This module does not reconstruct suppressed death counts.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "census-pep-v2025-syasex"
RECEIPTS = ROOT / "http-receipts.jsonl"
LANDING = "https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html"
LAYOUT = "https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/CC-EST2025-SYASEX.pdf"
BASE = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/asrh"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
TIMEOUT_SECONDS = 45
USER_AGENT = "USAAtlasResearch/1.0 (public aggregate health data collection)"

STATE_FIPS = ["01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "44", "45", "46", "47", "48", "49", "50", "51", "53", "54", "55", "56"]
YEAR_TO_CALENDAR = {"2": 2020, "3": 2021, "4": 2022, "5": 2023, "6": 2024}


def now():
    return datetime.now(timezone.utc).isoformat()


def append_receipt(record):
    with RECEIPTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def fetch_file(state_fips, refresh=False):
    name = f"cc-est2025-syasex-{state_fips}.csv"
    url = f"{BASE}/{name}"
    target = RAW / name
    if target.exists() and not refresh:
        # Only treat an existing file as resumable when a successful receipt
        # binds this exact requested URL to its current content hash.
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        receipts = []
        if RECEIPTS.exists():
            for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
                try:
                    receipt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if receipt.get("name") == name and receipt.get("status") == "downloaded":
                    receipts.append(receipt)
        if receipts and receipts[-1].get("sha256") == digest:
            return receipts[-1]

    record = {"name": name, "requested_url": url, "method": "GET",
              "params": {"state_fips": state_fips, "vintage": 2025},
              "started_at": now(), "max_response_bytes": MAX_FILE_BYTES,
              "timeout_seconds": TIMEOUT_SECONDS, "user_agent": USER_AGENT}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    payload = bytearray()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            record.update(url=response.geturl(), http_status=response.status,
                          content_type=response.headers.get("Content-Type"),
                          last_modified=response.headers.get("Last-Modified"),
                          etag=response.headers.get("ETag"))
            if response.status != 200:
                raise RuntimeError(f"unexpected HTTP status {response.status}")
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_FILE_BYTES:
                    raise ValueError("response exceeded per-file byte cap")
        prefix = payload[:512].decode("utf-8-sig", "replace").lstrip().replace('"', "")
        if not prefix.startswith("SUMLEV,STATE,COUNTY,"):
            raise ValueError("response did not begin with the expected PEP CSV header")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".part")
        temp.write_bytes(payload)
        temp.replace(target)
        record.update(status="downloaded", bytes=len(payload),
                      sha256=hashlib.sha256(payload).hexdigest(),
                      path=str(target.relative_to(ROOT)))
    except urllib.error.HTTPError as exc:
        body = exc.read(64 * 1024)
        record.update(http_status=exc.code, error=f"HTTPError: {exc.reason}",
                      error_body_bytes=len(body),
                      error_body_sha256=hashlib.sha256(body).hexdigest(), status="error")
    except Exception as exc:
        record.update(error=f"{type(exc).__name__}: {exc}",
                      partial_bytes=len(payload), status="error")
    record["finished_at"] = now()
    append_receipt(record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def fetch_all(refresh=False):
    RAW.mkdir(parents=True, exist_ok=True)
    total = 0
    outcomes = []
    for state_fips in STATE_FIPS:
        record = fetch_file(state_fips, refresh=refresh)
        outcomes.append(record)
        if record.get("status") == "downloaded":
            total += record.get("bytes", 0)
        elif record.get("path"):
            total += (ROOT / record["path"]).stat().st_size
        if total > MAX_TOTAL_BYTES:
            raise RuntimeError("aggregate response byte cap exceeded")
        time.sleep(0.15)
    return outcomes


def parse_downloads():
    """Create a compact age 1-4 population file; preserve per-year estimates."""
    receipt_by_name = {}
    if RECEIPTS.exists():
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "downloaded":
                receipt_by_name[rec["name"]] = rec
    output = ROOT / "child-age-bands" / "census-pep-2025-age1-4-population.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    keys = set()
    duplicate_keys = []
    missing_state_files = []
    for state_fips in STATE_FIPS:
        name = f"cc-est2025-syasex-{state_fips}.csv"
        path = RAW / name
        if not path.exists() or name not in receipt_by_name:
            missing_state_files.append(state_fips)
            continue
        rec = receipt_by_name[name]
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"SUMLEV", "STATE", "COUNTY", "STNAME", "CTYNAME", "YEAR", "AGE", "TOT_POP"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError(f"unexpected Census file layout in {name}: {reader.fieldnames}")
            for row in reader:
                if row.get("SUMLEV") != "050" or row.get("STATE") != state_fips:
                    continue
                if row.get("AGE") not in {"1", "2", "3", "4"} or row.get("YEAR") not in YEAR_TO_CALENDAR:
                    continue
                county_fips = str(row.get("COUNTY") or "").zfill(3)
                if not re.fullmatch(r"\d{3}", county_fips):
                    continue
                geoid = state_fips + county_fips
                year = YEAR_TO_CALENDAR[row["YEAR"]]
                age = int(row["AGE"])
                key = (geoid, year, age)
                if key in keys:
                    duplicate_keys.append(key)
                    continue
                keys.add(key)
                pop_text = row.get("TOT_POP", "")
                population = int(pop_text) if pop_text.isdigit() else None
                rows.append({
                    "geography_level": "county", "geoid": geoid,
                    "source_geoid": geoid, "state_fips": state_fips,
                    "county_fips": county_fips, "geography_name": row.get("CTYNAME"),
                    "state_name": row.get("STNAME"), "year": year, "age": age,
                    "age_group": "1-4", "population": population,
                    "source_release": "U.S. Census Bureau County PEP Vintage 2025 CC-EST2025-SYASEX",
                    "boundary_vintage": "2025-01-01 county boundaries",
                    "estimate_date": f"July 1, {year}",
                    "source_file": f"raw/census-pep-v2025-syasex/{name}",
                    "source_sha256": rec["sha256"], "source_url": rec["url"],
                    "source_methodology_url": LANDING,
                    "source_file_layout_url": LAYOUT,
                    "value_status": "numeric" if population is not None else "source_missing",
                })
    if duplicate_keys:
        raise ValueError(f"duplicate source geography/year/age keys: {len(duplicate_keys)}")
    fields = list(rows[0]) if rows else ["geography_level", "geoid", "source_geoid", "state_fips", "county_fips", "geography_name", "state_name", "year", "age", "age_group", "population", "source_release", "boundary_vintage", "estimate_date", "source_file", "source_sha256", "source_url", "source_methodology_url", "source_file_layout_url", "value_status"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "created_at": now(), "release": "Census PEP Vintage 2025, CC-EST2025-SYASEX",
        "years": sorted(set(YEAR_TO_CALENDAR.values())), "ages": [1, 2, 3, 4],
        "expected_state_fips": STATE_FIPS, "state_files_used": sorted({r["state_fips"] for r in rows}),
        "missing_state_fips": missing_state_files, "geography_rows": len({r["geoid"] for r in rows}),
        "geography_fips": sorted({r["geoid"] for r in rows}),
        "county_year_age_rows": len(rows), "duplicate_keys": duplicate_keys,
        "output": str(output.relative_to(ROOT)),
        "methodology_url": LANDING, "file_layout_url": LAYOUT,
        "limitation": "Population estimates use Census county-equivalent boundaries as of 2025-01-01. The CDC WONDER death extract uses its source FIPS; unmatched or changed county geographies are not crosswalked or assigned. The denominator is the sum of five July 1 age-specific resident population estimates per county.",
    }
    (ROOT / "child-age-bands" / "census-pep-2025-coverage.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["geography_rows", "county_year_age_rows", "missing_state_fips", "output"]}, ensure_ascii=False))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="fetch missing official Census PEP state CSV files")
    parser.add_argument("--refresh", action="store_true", help="re-download all 51 official CSV files")
    parser.add_argument("--normalize", action="store_true", help="build the compact age 1-4 population denominator table")
    args = parser.parse_args()
    if not (args.fetch or args.refresh or args.normalize):
        parser.error("use --fetch, --refresh, or --normalize")
    if args.fetch or args.refresh:
        fetch_all(refresh=args.refresh)
    if args.normalize:
        parse_downloads()


if __name__ == "__main__":
    main()
