#!/usr/bin/env python3
"""Download and prepare scoped public data locally; never writes to a database.

The source bytes and generated tables are kept below ignored full/runtime. The
inventory is written to /tmp/usa-maps-data-flow-20261026/data-results.json.
It reads no credential files. When the parent injects approved provider keys
into the environment, BLS v2 and EIA calls use those values without logging or
persisting them in URLs, metadata, errors, or echoed response bodies.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pilot"))
import run_pilot as safety  # noqa: E402
RUNTIME = ROOT / "full/runtime/data_refresh_20261026"
INVENTORY = Path("/tmp/usa-maps-data-flow-20261026/data-results.json")
PUBLISHED_BEFORE_INVENTORY = Path("/tmp/usa-maps-data-flow-20261026/published-before/inventory.json")
SOURCES = json.loads((PACKAGE / "source_catalog.json").read_text(encoding="utf-8"))["sources"]
USER_AGENT = "usa-maps-local-data-refresh/2026.10.26 (public data preparation)"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
FBI_DOWNLOAD_CATALOG_URL = "https://cde.ucr.cjis.gov/LATEST/webapp/assets/JSON/downloads/downloads.json"
FBI_SIGNED_LOCATOR_URL = "https://cde.ucr.cjis.gov/LATEST/s3/signedurl?key=additional-datasets%2Fsrs%2Festimated_crimes_1979_2025.csv"
FBI_ANNUAL_SAFE_URL = "https://cde-prd-data.s3.us-gov-east-1.amazonaws.com/additional-datasets/srs/estimated_crimes_1979_2025.csv"
FBI_ANNUAL_RAW_SHA256 = "e7bf3de96b21d00fc10e9d60fee4d8257cba0a095ce5c5fc992047d46fb76486"
FBI_ANNUAL_RETRIEVED_AT = "2026-10-26T12:13:22.509127+00:00"
FBI_ANNUAL_COLUMNS = ("year", "state_abbr", "state_name", "population", "violent_crime", "homicide",
                      "rape_legacy", "rape_revised", "robbery", "aggravated_assault", "property_crime",
                      "burglary", "larceny", "motor_vehicle_theft", "caveats")
FBI_FIELD_COLUMNS = {"04.01": "homicide", "04.02": "violent_crime", "04.03": "robbery",
                     "04.04": "aggravated_assault", "04.05": "burglary", "04.06": "motor_vehicle_theft",
                     "04.07": "rape_revised"}
BLS_DAILY_LIMIT = 500
BLS_DAILY_BUDGET = 20
BLS_PLAN_VERSION = "laus-nsa-2025-v2"
FBI_STATES = [
    ("AL", "Alabama", "01"), ("AK", "Alaska", "02"), ("AZ", "Arizona", "04"),
    ("AR", "Arkansas", "05"), ("CA", "California", "06"), ("CO", "Colorado", "08"),
    ("CT", "Connecticut", "09"), ("DE", "Delaware", "10"), ("DC", "District of Columbia", "11"),
    ("FL", "Florida", "12"), ("GA", "Georgia", "13"), ("HI", "Hawaii", "15"),
    ("ID", "Idaho", "16"), ("IL", "Illinois", "17"), ("IN", "Indiana", "18"),
    ("IA", "Iowa", "19"), ("KS", "Kansas", "20"), ("KY", "Kentucky", "21"),
    ("LA", "Louisiana", "22"), ("ME", "Maine", "23"), ("MD", "Maryland", "24"),
    ("MA", "Massachusetts", "25"), ("MI", "Michigan", "26"), ("MN", "Minnesota", "27"),
    ("MS", "Mississippi", "28"), ("MO", "Missouri", "29"), ("MT", "Montana", "30"),
    ("NE", "Nebraska", "31"), ("NV", "Nevada", "32"), ("NH", "New Hampshire", "33"),
    ("NJ", "New Jersey", "34"), ("NM", "New Mexico", "35"), ("NY", "New York", "36"),
    ("NC", "North Carolina", "37"), ("ND", "North Dakota", "38"), ("OH", "Ohio", "39"),
    ("OK", "Oklahoma", "40"), ("OR", "Oregon", "41"), ("PA", "Pennsylvania", "42"),
    ("RI", "Rhode Island", "44"), ("SC", "South Carolina", "45"), ("SD", "South Dakota", "46"),
    ("TN", "Tennessee", "47"), ("TX", "Texas", "48"), ("UT", "Utah", "49"),
    ("VT", "Vermont", "50"), ("VA", "Virginia", "51"), ("WA", "Washington", "53"),
    ("WV", "West Virginia", "54"), ("WI", "Wisconsin", "55"), ("WY", "Wyoming", "56"),
]
STATE_NAMES = {abbr: (name, fips) for abbr, name, fips in FBI_STATES}
STATE_FIPS = {fips for _, _, fips in FBI_STATES}
BLS_MEASURES = {
    "03": ("unemployment_rate", "%"),
    "04": ("unemployed", "persons"),
    "05": ("employed", "persons"),
    "06": ("labor_force", "persons"),
}
FBI_OFFENSES = {
    "04.01": ("homicide", "Murders"),
    "04.02": ("violent-crime", "Violent crime"),
    "04.03": ("robbery", "Robbery"),
    "04.04": ("aggravated-assault", "Aggravated assault"),
    "04.05": ("burglary", "Burglary"),
    "04.06": ("motor-vehicle-theft", "Motor vehicle theft"),
    "04.07": ("rape", "Rape"),
}
FRESHNESS_PAGES = {
    "bls_laus_tables": "https://www.bls.gov/lau/tables.htm",
    "bls_laus_api_faq": "https://www.bls.gov/developers/api_faqs.htm",
    "bls_laus_annual_notice": "https://www.bls.gov/lau/launews1.htm",
    "acs_schedule": "https://www.census.gov/programs-surveys/acs/news/data-releases/2025/release-schedule.html",
    "places_release": "https://www.cdc.gov/places/current-release-notes/",
    "bea_rpp": "https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area",
    "irs_county_2023": "https://www.irs.gov/statistics/soi-tax-stats-county-data-2023",
    "uscs_technical_notes": "https://www.cdc.gov/united-states-cancer-statistics/technical-notes/",
    "hiv_release": "https://www.cdc.gov/hiv-data/nhss/hiv-diagnoses-deaths-prevalence.html",
    "wonder_mortality": "https://wonder.cdc.gov/wonder/help/mcd-expanded.html",
    "fbi_2025_release": "https://www.fbi.gov/news/press-releases/fbi-releases-2025-reported-crimes-in-the-nation-statistics",
    "eia_annual": "https://www.eia.gov/electricity/annual/",
    "census_pep_v2025": "https://www.census.gov/programs-surveys/popest/data/data-sets.2024.html",
}
DOWNLOADS = {
    "pep_county_totals": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
    "pep_county_age": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/asrh/cc-est2025-syasex.csv",
    "pep_national_age": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/national/asrh/nc-est2025-agesex-res.csv",
    "irs_county_2023": "https://www.irs.gov/pub/irs-soi/23incyallagi.csv",
    "eia_table_2025": "https://www.eia.gov/electricity/annual/table.php?t=epa_02_10.html",
    "hiv_tables_2024": "https://www.cdc.gov/hiv-data/media/files/2026/04/hiv_surveillance_data_release_tables_2024.xlsx",
    "bls_bulk_2025_forward": "https://download.bls.gov/pub/time.series/la/la.data.0.CurrentU25-29",
    "fbi_cde_download_catalog": FBI_DOWNLOAD_CATALOG_URL,
}
MEDICAL_RECEIPTS = {
    "cancer2023": ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.01/observations.jsonl",
    "hiv2024": ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.02/observations.jsonl",
    "childDeaths2024": ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.03/observations.jsonl",
}
MEDICAL_PUBLISHER_RAW = {
    "cancer2023": (ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.01/inputs/uscs-landing-incidence-raw.json",
                   "https://gis.cdc.gov/cancerapi/DataVizApi/GetJSON/LandingPageMapData_Inci", None, "CDC public domain"),
    "hiv2024": (ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.02/inputs/11.02-atlasplus-2024-replay-response-20261011T0156Z.json",
                "https://gis.cdc.gov/api/AtlasPlus/qtOutputData", None, "CDC public domain"),
    "childDeaths2024": (ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.03/inputs/11.03-cdc-wonder-D473F417-2024-state-age0-17-response-20261007T0456Z.html",
                        "https://wonder.cdc.gov/controller/saved/D158/D473F417", None, "CDC public-use data"),
}
MEDICAL_SOURCE_RECEIPTS = {
    "cancer2023": ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.01/inputs/uscs-landing-incidence-receipt.json",
    "hiv2024": ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.02/inputs/11.02-atlasplus-2024-fresh-replay-20261011T0156Z.json",
    "childDeaths2024": ROOT.parents[1] / "evidence/medical-import-20261011/final/wave-output/prepared/11.03/inputs/wonder-request-trace.json",
}
BLS_PARENT_FILENAMES = ("bls-laus-2025.csv", "bls-laus-2025-missingness.jsonl", "bls-laus-2025-coverage.csv")
BLS_PARENT_EXPECTED = {"batchCount": 256, "completedBatchCount": 256, "pendingSeriesCount": 0,
                       "observedRows": 153312, "missingnessRows": 12828, "seriesCount": 12780}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(content)
    temp.replace(path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode())


def request_bytes(url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
                  timeout: int = 90) -> tuple[bytes, int, dict[str, str]]:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=data, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read(), int(response.status), dict(response.headers.items())


def public_url(url: str) -> str:
    return safety.canonical_url(url)


def source_bytes_safe(payload: bytes) -> bool:
    """Reject provider output if it echoes any injected environment credential."""
    text = payload.decode("utf-8", errors="ignore")
    if "[REDACTED]" in safety.redact_text(text):
        return False
    for name in safety.CREDENTIAL_NAMES:
        secret = os.getenv(name, "")
        if not secret:
            continue
        variants = {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret),
                    urllib.parse.quote(secret, safe="/"), urllib.parse.quote_plus(secret, safe="")}
        if any(variant and variant in text for variant in variants):
            return False
    return True


def source_meta_path() -> Path:
    return RUNTIME / "state/source-artifacts.json"


def load_source_meta() -> dict[str, Any]:
    path = source_meta_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("artifacts"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"format": "data_refresh_source_inventory_v1", "artifacts": {}}


def download_file(source_id: str, url: str, relative_path: str,
                  license_note: str = "Official public source; source citation retained.") -> dict[str, Any]:
    meta = load_source_meta()
    path = RUNTIME / "raw" / relative_path
    record = meta["artifacts"].get(source_id)
    if path.exists() and record and record.get("sha256") == sha256_file(path):
        return {**record, "status": "reused_verified"}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    start = temp.stat().st_size if temp.exists() else 0
    headers = {"Range": f"bytes={start}-"} if start else {}
    retrieved_at = utc_now()
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT, **headers})
        with urlopen(request, timeout=180) as response:
            status = int(response.status)
            if status == 206 and start:
                mode = "ab"
            else:
                mode = "wb"
                start = 0
            with temp.open(mode) as out:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
            expected = response.headers.get("Content-Length")
            total = temp.stat().st_size
            if expected and status == 200 and total != int(expected):
                raise OSError("content_length_mismatch")
            if expected and status == 206:
                content_range = response.headers.get("Content-Range", "")
                match = re.search(r"/(\d+)$", content_range)
                if match and total != int(match.group(1)):
                    raise OSError("partial_download_incomplete")
        if not source_bytes_safe(temp.read_bytes()):
            temp.unlink(missing_ok=True)
            raise ValueError("response_contains_injected_secret")
        temp.replace(path)
        value = {
            "sourceId": source_id, "url": public_url(url), "path": str(path), "sha256": sha256_file(path),
            "bytes": path.stat().st_size, "retrievedAt": retrieved_at,
            "httpStatus": status, "contentType": response.headers.get("Content-Type"),
            "license": license_note, "status": "downloaded",
        }
    except HTTPError as error:
        value = {"sourceId": source_id, "url": public_url(url), "path": str(path), "attemptedAt": retrieved_at,
                 "httpStatus": error.code, "status": "blocked_http", "reason": f"http_{error.code}",
                 "license": license_note}
    except (URLError, TimeoutError, OSError, ValueError) as error:
        value = {"sourceId": source_id, "url": public_url(url), "path": str(path), "attemptedAt": retrieved_at,
                 "status": "unavailable", "reason": type(error).__name__, "license": license_note}
    meta["artifacts"][source_id] = value
    atomic_json(source_meta_path(), meta)
    return value


def download_fixed_sources() -> dict[str, Any]:
    metadata = {source["id"]: source for source in SOURCES}
    results: dict[str, Any] = {}
    fixed = [
        ("census-pep-county-totals-v2025", "pep_county_totals", "census/pep-v2025/co-est2025-alldata.csv"),
        ("census-pep-county-single-age-v2025", "pep_county_age", "census/pep-v2025/cc-est2025-syasex.csv"),
        ("census-pep-national-single-age-v2025", "pep_national_age", "census/pep-v2025/nc-est2025-agesex-res.csv"),
        ("irs-soi-county-2023", "irs_county_2023", "irs/23incyallagi.csv"),
        ("eia-epa-2-10", "eia_table_2025", "eia/epa-02-10.html"),
        ("cdc-hiv-2024-tables", "hiv_tables_2024", "cdc/hiv_surveillance_data_release_tables_2024.xlsx"),
        ("bls-laus-bulk", "bls_bulk_2025_forward", "bls/la.data.0.CurrentU25-29"),
        ("fbi-cde-srs-estimates-2025", "fbi_cde_download_catalog", "fbi/cde-download-catalog.json"),
    ]
    for source_id, key, relative in fixed:
        source = metadata[source_id]
        results[key] = download_file(source_id, DOWNLOADS[key], relative, source.get("license", ""))
        print(f"source {key}: {results[key]['status']}", flush=True)
    return results


def download_freshness_pages() -> dict[str, Any]:
    output = {}
    for name, url in FRESHNESS_PAGES.items():
        output[name] = download_file("freshness-page-" + name, url, f"pages/{name}.html",
                                     "Official publisher page snapshot; use the listed page citation.")
        print(f"page {name}: {output[name]['status']}", flush=True)
    return output


def safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "")
    if not cleaned or cleaned in {"-", "—", "NA", "N/A", "(X)"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        number = Decimal(cleaned)
        if number != number.to_integral_value():
            raise ValueError("non_integer_population")
        return int(number)


def read_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open("rb") as raw:
        has_utf8_bom = raw.read(3) == b"\xef\xbb\xbf"
    # Census county files include legacy Windows-1252 place names in otherwise
    # ordinary CSV. Preserve the original bytes; decode only for preparation.
    encoding = "utf-8-sig" if has_utf8_bom else "cp1252"
    with path.open("r", encoding=encoding, newline="") as stream:
        yield from csv.DictReader(stream)


def pep_year_for_source(year: str) -> str:
    # PEP's county single-age file uses YEAR=1 for 2020 through YEAR=6 for 2025.
    if year not in {"2023", "2024"}:
        raise ValueError("unsupported_pep_year")
    return str(int(year) - 2019)


def prepare_population() -> dict[str, Any]:
    totals_file = RUNTIME / "raw/census/pep-v2025/co-est2025-alldata.csv"
    age_file = RUNTIME / "raw/census/pep-v2025/cc-est2025-syasex.csv"
    national_age_file = RUNTIME / "raw/census/pep-v2025/nc-est2025-agesex-res.csv"
    needed = [totals_file, age_file, national_age_file]
    if not all(path.exists() for path in needed):
        return {"status": "blocked_inputs", "missing": [str(p) for p in needed if not p.exists()]}

    population: dict[tuple[str, str, str], dict[str, Any]] = {}
    county_totals: dict[tuple[str, str], int] = {}
    state_totals: dict[tuple[str, str], int] = {}
    national_totals: dict[str, int] = {}
    for row in read_csv(totals_file):
        state = row.get("STATE", "").zfill(2)
        county = row.get("COUNTY", "").zfill(3)
        sumlev = row.get("SUMLEV", "")
        if state not in STATE_FIPS and state != "00":
            continue
        for year in ("2023", "2024"):
            value = safe_int(row.get("POPESTIMATE" + year))
            if value is None:
                continue
            if state == "00" or sumlev == "010":
                national_totals[year] = value
            elif county == "000" or sumlev == "040":
                state_totals[(state, year)] = value
            elif sumlev == "050" or county != "000":
                county_totals[(state + county, year)] = value

    under18_counties: dict[tuple[str, str], int] = {}
    under13_counties: dict[tuple[str, str], int] = {}
    age_coverage: dict[tuple[str, str], set[int]] = {}
    under13_coverage: dict[tuple[str, str], set[int]] = {}
    for row in read_csv(age_file):
        state = row.get("STATE", "").zfill(2)
        county = row.get("COUNTY", "").zfill(3)
        if state not in STATE_FIPS:
            continue
        age = safe_int(row.get("AGE"))
        if age is None or not 0 <= age <= 17:
            continue
        fips = state + county
        for year in ("2023", "2024"):
            if row.get("YEAR") != pep_year_for_source(year):
                continue
            value = safe_int(row.get("TOT_POP"))
            if value is None:
                continue
            key = (fips, year)
            under18_counties[key] = under18_counties.get(key, 0) + value
            age_coverage.setdefault(key, set()).add(age)
            if age <= 12:
                under13_counties[key] = under13_counties.get(key, 0) + value
                under13_coverage.setdefault(key, set()).add(age)

    # The national age file has both-sex rows (SEX=0) and single-age values.
    national_under18: dict[str, int] = {}
    national_under13: dict[str, int] = {}
    national_age_coverage: dict[str, set[int]] = {}
    national_under13_coverage: dict[str, set[int]] = {}
    for row in read_csv(national_age_file):
        if row.get("SEX") != "0":
            continue
        age = safe_int(row.get("AGE"))
        if age is None or not 0 <= age <= 17:
            continue
        for year in ("2023", "2024"):
            value = safe_int(row.get("POPESTIMATE" + year))
            if value is None:
                continue
            national_under18[year] = national_under18.get(year, 0) + value
            national_age_coverage.setdefault(year, set()).add(age)
            if age <= 12:
                national_under13[year] = national_under13.get(year, 0) + value
                national_under13_coverage.setdefault(year, set()).add(age)

    expected_counties = {geo for geo, _ in county_totals}
    output_rows: list[dict[str, Any]] = []
    missing_counties: list[dict[str, Any]] = []
    age13_counties: dict[tuple[str, str], int] = {}
    for year in ("2023", "2024"):
        for fips in sorted(expected_counties):
            value = county_totals.get((fips, year))
            if value is None:
                missing_counties.append({"geo_id": fips, "year": year, "kind": "total_population"})
                continue
            output_rows.append({"geo_id": fips, "geo_type": "county", "year": year,
                                "population_kind": "total", "value": value,
                                "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                "aggregation": "source_county_estimate"})
            age_key = (fips, year)
            if age_coverage.get(age_key) == set(range(18)):
                output_rows.append({"geo_id": fips, "geo_type": "county", "year": year,
                                    "population_kind": "under_18", "value": under18_counties[age_key],
                                    "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                    "aggregation": "sum of single ages 0 through 17"})
            else:
                missing_counties.append({"geo_id": fips, "year": year, "kind": "under_18_population",
                                         "missingAges": sorted(set(range(18)) - age_coverage.get(age_key, set()))})
            if under13_coverage.get(age_key) == set(range(13)):
                age13 = value - under13_counties[age_key]
                if age13 >= 0:
                    age13_counties[age_key] = age13
                    output_rows.append({"geo_id": fips, "geo_type": "county", "year": year,
                                        "population_kind": "age_13_plus", "value": age13,
                                        "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                        "aggregation": "total population minus both-sex single ages 0 through 12"})
                else:
                    missing_counties.append({"geo_id": fips, "year": year, "kind": "age_13_plus_population",
                                             "reason": "subtraction_negative"})
            else:
                missing_counties.append({"geo_id": fips, "year": year, "kind": "age_13_plus_population",
                                         "missingAges": sorted(set(range(13)) - under13_coverage.get(age_key, set()))})

        for state, _name, _abbr in FBI_STATES:
            fips = STATE_NAMES[state][1]
            value = state_totals.get((fips, year))
            if value is None:
                member_values = [v for (geo, y), v in county_totals.items()
                                 if y == year and geo.startswith(fips)]
                if member_values:
                    value = sum(member_values)
                    method = "sum of county PEP total estimates; state total source row absent"
                else:
                    method = "missing source value"
            else:
                method = "source state estimate"
            if value is not None:
                output_rows.append({"geo_id": fips, "geo_type": "state", "year": year,
                                    "population_kind": "total", "value": value, "unit": "persons",
                                    "source_release": "Census PEP Vintage 2025", "aggregation": method})
            child_values = [v for (geo, y), v in under18_counties.items()
                            if y == year and geo.startswith(fips)]
            expected_state_counties = [geo for geo in expected_counties if geo.startswith(fips)]
            if len(child_values) == len(expected_state_counties) and expected_state_counties:
                output_rows.append({"geo_id": fips, "geo_type": "state", "year": year,
                                    "population_kind": "under_18", "value": sum(child_values),
                                    "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                    "aggregation": "sum of county single ages 0 through 17"})
            else:
                missing_counties.append({"geo_id": fips, "year": year, "kind": "state_under_18_population",
                                         "expectedCounties": len(expected_state_counties),
                                         "foundCounties": len(child_values)})
            age13_values = [v for (geo, y), v in age13_counties.items() if y == year and geo.startswith(fips)]
            if len(age13_values) == len(expected_state_counties) and expected_state_counties:
                output_rows.append({"geo_id": fips, "geo_type": "state", "year": year,
                                    "population_kind": "age_13_plus", "value": sum(age13_values),
                                    "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                    "aggregation": "sum of county age 13+ estimates"})
            else:
                missing_counties.append({"geo_id": fips, "year": year, "kind": "state_age_13_plus_population",
                                         "expectedCounties": len(expected_state_counties),
                                         "foundCounties": len(age13_values)})

        total_us = national_totals.get(year)
        if total_us is None:
            state_values = [state_totals.get((STATE_NAMES[abbr][1], year)) for abbr, _, _ in FBI_STATES]
            if all(value is not None for value in state_values):
                total_us = sum(value for value in state_values if value is not None)
                total_method = "sum of 50 state and DC PEP estimates; national row absent"
            else:
                total_method = "missing source value"
        else:
            total_method = "source U.S. estimate"
        if total_us is not None:
            output_rows.append({"geo_id": "US", "geo_type": "nation", "year": year,
                                "population_kind": "total", "value": total_us, "unit": "persons",
                                "source_release": "Census PEP Vintage 2025", "aggregation": total_method})
        if national_age_coverage.get(year) == set(range(18)):
            output_rows.append({"geo_id": "US", "geo_type": "nation", "year": year,
                                "population_kind": "under_18", "value": national_under18[year],
                                "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                "aggregation": "sum of national single ages 0 through 17"})
        else:
            missing_counties.append({"geo_id": "US", "year": year, "kind": "national_under_18_population",
                                     "missingAges": sorted(set(range(18)) - national_age_coverage.get(year, set()))})
        if national_under13_coverage.get(year) == set(range(13)) and total_us is not None:
            age13 = total_us - national_under13[year]
            if age13 >= 0:
                output_rows.append({"geo_id": "US", "geo_type": "nation", "year": year,
                                    "population_kind": "age_13_plus", "value": age13,
                                    "unit": "persons", "source_release": "Census PEP Vintage 2025",
                                    "aggregation": "total population minus national both-sex single ages 0 through 12"})
            else:
                missing_counties.append({"geo_id": "US", "year": year, "kind": "national_age_13_plus_population",
                                         "reason": "subtraction_negative"})
        else:
            missing_counties.append({"geo_id": "US", "year": year, "kind": "national_age_13_plus_population",
                                     "missingAges": sorted(set(range(13)) - national_under13_coverage.get(year, set()))})

    output_rows.sort(key=lambda row: (row["year"], row["population_kind"], row["geo_type"], row["geo_id"]))
    write_csv(RUNTIME / "prepared/population-2023-2024.csv", output_rows)
    write_jsonl(RUNTIME / "prepared/population-missingness.jsonl", missing_counties)
    return {
        "status": "complete" if not missing_counties else "partial",
        "countyGeographies": len(expected_counties),
        "preparedRows": len(output_rows),
        "missingnessRows": len(missing_counties),
        "missingnessPath": str(RUNTIME / "prepared/population-missingness.jsonl"),
        "output": str(RUNTIME / "prepared/population-2023-2024.csv"),
        "nationalUnder18Crosscheck": national_under18,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    if not rows:
        atomic_write(path, b"")
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    count = 0
    with temp.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    temp.replace(path)


class EiaTableParser(HTMLParser):
    """Collect table rows without a third-party HTML or spreadsheet library."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []
        self.all_rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.in_table = True
            self.rows = []
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_table and self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag in {"td", "th"}:
            self.current_row.append(" ".join(" ".join(self.current_cell).split()))
            self.in_cell = False
        elif self.in_row and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        elif tag == "table" and self.in_table:
            self.all_rows.extend(self.rows)
            self.in_table = False


def eia_number(value: str) -> Decimal | None:
    value = value.strip().replace(",", "")
    if not value or value in {"--", "—", "-", "N/A"}:
        return None
    return Decimal(value)


def fetch_eia_api() -> dict[str, Any]:
    """Fetch annual ALL-sector retail prices using only an injected EIA API key."""
    key = os.getenv("EIA_API_KEY")
    if not key:
        return {"status": "not_requested_no_environment_key"}
    params = [
        ("api_key", key), ("frequency", "annual"), ("data[0]", "price"),
        ("facets[sectorid][]", "ALL"), ("start", "2025"), ("end", "2025"),
        ("offset", "0"), ("length", "5000"),
    ]
    url = "https://api.eia.gov/v2/electricity/retail-sales/data/?" + urllib.parse.urlencode(params)
    path = RUNTIME / "raw/eia/electricity-retail-sales-2025-all.json"
    meta_path = path.with_suffix(".meta.json")
    retrieved_at = utc_now()
    try:
        payload, status, headers = request_bytes(url, timeout=90)
        if not source_bytes_safe(payload):
            return {"status": "blocked_secret_echo", "url": public_url(url), "attemptedAt": retrieved_at}
        atomic_write(path, payload)
        artifact = {"sourceId": "eia-retail-sales-api", "url": public_url(url), "path": str(path),
                    "sha256": sha256_bytes(payload), "bytes": len(payload), "retrievedAt": retrieved_at,
                    "httpStatus": status, "contentType": headers.get("Content-Type"),
                    "license": "Official EIA public statistics; source URL retained.",
                    "status": "downloaded", "credentialMode": "registered"}
        atomic_json(meta_path, artifact)
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {**artifact, "status": "downloaded_unparsed", "reason": "json_decode"}
        rows = data.get("response", {}).get("data")
        if not isinstance(rows, list):
            return {**artifact, "status": "downloaded_unparsed", "reason": "response_shape"}
        return {**artifact, "rowCount": len(rows)}
    except HTTPError as error:
        return {"sourceId": "eia-retail-sales-api", "url": public_url(url), "attemptedAt": retrieved_at,
                "httpStatus": error.code, "status": "blocked_http", "reason": f"http_{error.code}"}
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        return {"sourceId": "eia-retail-sales-api", "url": public_url(url), "attemptedAt": retrieved_at,
                "status": "unavailable", "reason": type(error).__name__}


def parse_eia_api(payload: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response = json.loads(payload.decode("utf-8")).get("response", {})
    source_rows = response.get("data", [])
    rows = []
    fips_by_abbr = {abbr: (name, fips) for abbr, name, fips in FBI_STATES}
    for item in source_rows:
        state = str(item.get("stateid", "")).upper()
        if state not in fips_by_abbr or str(item.get("period")) != "2025":
            continue
        if str(item.get("sectorid", "ALL")).upper() not in {"ALL", "ALL_SECTORS"}:
            continue
        name, fips = fips_by_abbr[state]
        price = item.get("price")
        value = eia_number(str(price)) if price is not None else None
        rows.append({"geo_id": fips, "geo_type": "state", "state": state, "state_name": name,
                     "year": "2025", "value": str(value) if value is not None else None,
                     "unit": str(item.get("price-units", "cents/kWh")), "sector": "ALL",
                     "source_release": "EIA Electric Power Annual 2025",
                     "source_url": "https://api.eia.gov/v2/electricity/retail-sales/data/",
                     "status": "observed" if value is not None else "source_missing"})
    by_geo = {row["geo_id"]: row for row in rows}
    if len(by_geo) != 51:
        raise ValueError(f"eia_state_coverage_{len(by_geo)}_of_51")
    ordered = [by_geo[fips] for _, _, fips in FBI_STATES]
    return ordered, {"stateRows": len(ordered),
                     "missingValueStates": [row["geo_id"] for row in ordered if row["value"] is None]}


def parse_eia_html(html: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parser = EiaTableParser()
    parser.feed(html)
    rows = []
    state_to_fips = {name.casefold(): (abbr, fips) for abbr, name, fips in FBI_STATES}
    state_to_fips["district of columbia"] = ("DC", "11")
    for cells in parser.all_rows:
        if len(cells) < 3:
            continue
        state = " ".join(cells[0].split()).casefold()
        if state not in state_to_fips:
            continue
        candidates = [eia_number(cell) for cell in cells[1:]]
        numeric = [candidate for candidate in candidates]
        if len(numeric) < 2:
            continue
        # Table 2.10 orders sector columns in pairs; the final pair is All Sectors.
        all_2025, all_2024 = numeric[-2], numeric[-1]
        abbr, fips = state_to_fips[state]
        rows.append({"geo_id": fips, "geo_type": "state", "state": abbr,
                     "state_name": FBI_STATES[[x[0] for x in FBI_STATES].index(abbr)][1],
                     "year": "2025", "value": str(all_2025) if all_2025 is not None else None,
                     "unit": "cents/kWh", "sector": "ALL", "source_release": "EIA Electric Power Annual 2025",
                     "source_url": DOWNLOADS["eia_table_2025"],
                     "status": "observed" if all_2025 is not None else "source_missing"})
    by_geo = {row["geo_id"]: row for row in rows}
    missing_states = sorted(set(fips for _, _, fips in FBI_STATES) - set(by_geo))
    if len(by_geo) != 51:
        raise ValueError(f"eia_state_coverage_{len(by_geo)}_of_51")
    return [by_geo[fips] for fips in sorted(by_geo)], {
        "stateRows": len(by_geo), "missingValueStates": [r["geo_id"] for r in rows if r["value"] is None],
        "statesWithoutRows": missing_states,
    }


def prepare_eia() -> dict[str, Any]:
    api_path = RUNTIME / "raw/eia/electricity-retail-sales-2025-all.json"
    if api_path.exists():
        try:
            rows, summary = parse_eia_api(api_path.read_bytes())
            out = RUNTIME / "prepared/eia-electricity-price-2025-all-sectors.csv"
            write_csv(out, rows)
            return {"status": "complete" if not summary["missingValueStates"] else "partial",
                    "sourceMode": "registered_api", "output": str(out), "rows": len(rows), **summary}
        except (OSError, ValueError, InvalidOperation) as error:
            return {"status": "downloaded_unparsed", "sourceMode": "registered_api",
                    "reason": type(error).__name__}
    path = RUNTIME / "raw/eia/epa-02-10.html"
    if not path.exists():
        return {"status": "blocked_input", "input": str(path)}
    try:
        rows, summary = parse_eia_html(path.read_text(encoding="utf-8", errors="replace"))
        out = RUNTIME / "prepared/eia-electricity-price-2025-all-sectors.csv"
        write_csv(out, rows)
        return {"status": "partial" if summary["missingValueStates"] else "complete",
                "output": str(out), "rows": len(rows), **summary}
    except (OSError, ValueError, InvalidOperation) as error:
        return {"status": "downloaded_unparsed", "reason": str(error)}


def prepare_eia_before_after() -> dict[str, Any]:
    """Compare hash-verified published ALL-sector 2024 observations with 2025 preparation."""
    inventory_path = PUBLISHED_BEFORE_INVENTORY
    current_path = RUNTIME / "prepared/eia-electricity-price-2025-all-sectors.csv"
    if not inventory_path.exists() or not current_path.exists():
        return {"status": "baseline_or_current_missing"}
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("manifestUnchanged") is not True or len(inventory.get("observations", [])) < 42:
        return {"status": "published_baseline_not_verified"}
    item = next((x for x in inventory.get("observations", []) if x.get("fieldId") == "08.05:sector_ALL"), None)
    if not item or item.get("period") != "2024" or not Path(item["path"]).exists():
        return {"status": "published_baseline_missing"}
    baseline_path = Path(item["path"])
    payload = baseline_path.read_bytes()
    if sha256_bytes(payload) != item.get("sha256"):
        raise ValueError("eia_published_baseline_hash_mismatch")
    snapshot = json.loads(payload)
    if snapshot.get("fieldId") != "08.05:sector_ALL" or snapshot.get("period") != "2024":
        raise ValueError("eia_published_baseline_identity_mismatch")
    state_by_fips = {fips: abbr for abbr, _name, fips in FBI_STATES}
    before = {}
    for row in snapshot.get("observations", []):
        source_geo = str(row.get("sourceGeoId") or row.get("id"))
        abbr = source_geo if source_geo in STATE_NAMES else state_by_fips.get(str(row.get("id")))
        if row.get("geoType") == "state" and abbr and row.get("value") is not None:
            before[abbr] = Decimal(str(row["value"]))
    current = {}
    for row in read_csv(current_path):
        abbr = row.get("state", "")
        if abbr and row.get("value") not in {None, ""}:
            current[abbr] = Decimal(row["value"])
    rank_before = {state: rank for rank, (state, _value) in enumerate(
        sorted(before.items(), key=lambda item: (-item[1], item[0])), 1)}
    rank_after = {state: rank for rank, (state, _value) in enumerate(
        sorted(current.items(), key=lambda item: (-item[1], item[0])), 1)}
    rows = []
    for abbr, name, fips in FBI_STATES:
        old, new = before.get(abbr), current.get(abbr)
        rows.append({"geo_id": fips, "state": abbr, "state_name": name, "sector": "ALL",
                     "before_year": "2024", "before_value_cents_per_kwh": str(old) if old is not None else None,
                     "before_rank_high_to_low": rank_before.get(abbr), "after_year": "2025",
                     "after_value_cents_per_kwh": str(new) if new is not None else None,
                     "after_rank_high_to_low": rank_after.get(abbr),
                     "change_cents_per_kwh": str(new - old) if old is not None and new is not None else None,
                     "status": "comparable_annual_all_sector" if old is not None and new is not None else "missing_source_value"})
    path = RUNTIME / "prepared/eia-2024-2025-before-after-ranks.csv"
    write_csv(path, rows)
    return {"status": "complete" if len(before) == 51 and len(current) == 51 else "partial",
            "baselineSource": str(baseline_path), "baselineSourceSha256": item["sha256"],
            "baselineRows": len(before), "preparedRows": len(current), "output": str(path)}


def _xlsx_rows(path: Path) -> list[list[str]]:
    """Read the first sheet of an OOXML workbook using only the standard library."""
    main_ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{main_ns}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{main_ns}t")))
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(f".//{main_ns}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{main_ns}c"):
            ref = cell.get("r", "")
            letters = re.match(r"([A-Z]+)", ref)
            if not letters:
                continue
            index = 0
            for char in letters.group(1):
                index = index * 26 + ord(char) - 64
            index -= 1
            kind = cell.get("t")
            value = cell.find(f"{main_ns}v")
            if kind == "s" and value is not None:
                text = shared[int(value.text or "0")]
            elif kind == "inlineStr":
                text = "".join(node.text or "" for node in cell.iter(f"{main_ns}t"))
            else:
                text = value.text if value is not None and value.text is not None else ""
            values[index] = text
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
    return rows


def parse_fbi_annual(path: Path) -> tuple[list[dict[str, str]], str]:
    raw_hash = sha256_file(path)
    with path.open("rb") as stream:
        prefix = stream.read(4)
    if prefix.startswith(b"PK"):
        rows = _xlsx_rows(path)
        if not rows:
            raise ValueError("fbi_annual_workbook_empty")
        headers = [value.strip() for value in rows[0]]
        records = [dict(zip(headers, row)) for row in rows[1:] if any(value.strip() for value in row)]
    else:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            records = list(csv.DictReader(stream))
        headers = list(records[0]) if records else []
    if tuple(headers) != FBI_ANNUAL_COLUMNS:
        raise ValueError("fbi_annual_unexpected_columns")
    normalized = []
    seen = set()
    expected = {abbr for abbr, _, _ in FBI_STATES}
    year_rows = [row for row in records if row.get("year", "").strip() == "2025"]
    footnote_text: dict[str, str] = {}
    for row in year_rows:
        caveat = (row.get("caveats", "") or "").strip()
        match = re.match(r"^(\d+)\s+(.+)$", caveat)
        if match:
            marker, text = match.groups()
            if marker in footnote_text and footnote_text[marker] != text:
                raise ValueError("fbi_annual_conflicting_footnote_text")
            footnote_text[marker] = text
    for row in year_rows:
        abbr = row.get("state_abbr", "").strip()
        source_name = row.get("state_name", "") or ""
        name = source_name.strip()
        marker_match = re.match(r"^(.*?)(\d+)$", name)
        marker = marker_match.group(2) if marker_match else ""
        if marker_match:
            name = marker_match.group(1).strip()
        caveat = (row.get("caveats", "") or "").strip()
        caveat_match = re.match(r"^(\d+)\s+(.+)$", caveat)
        marker_text = footnote_text.get(marker, "") if marker else ""
        if marker and not marker_text:
            raise ValueError("fbi_annual_unresolved_footnote_marker")
        if caveat_match and marker and caveat_match.group(1) != marker:
            raise ValueError("fbi_annual_footnote_marker_mismatch")
        if caveat_match and not marker:
            marker = caveat_match.group(1)
            marker_text = caveat_match.group(2)
        geo = abbr or "US"
        if geo in seen:
            raise ValueError("fbi_annual_duplicate_2025_geography")
        seen.add(geo)
        pop = safe_int(row.get("population", ""))
        if not pop:
            raise ValueError("fbi_annual_missing_population")
        normalized.append({**{column: (row.get(column, "") or "").strip() for column in FBI_ANNUAL_COLUMNS},
                           "state_abbr": abbr, "state_name": name, "source_state_name": source_name,
                           "source_footnote_marker": marker, "caveats": marker_text,
                           "population": str(pop)})
    if len(normalized) != 52 or seen != expected | {"US"} or not any(not r["state_abbr"] and r["state_name"] == "United States Total" for r in normalized):
        raise ValueError("fbi_annual_2025_geography_coverage_invalid")
    for row in normalized:
        for column in FBI_FIELD_COLUMNS.values():
            if row.get(column, "") and safe_int(row[column]) is None:
                raise ValueError("fbi_annual_invalid_count")
    return normalized, raw_hash


def acquire_fbi_annual_raw(download: bool = False, supplied_path: Path | None = None) -> dict[str, Any]:
    """Reuse/import verified raw bytes, or download through the public locator without retaining it."""
    target = RUNTIME / "raw/fbi/estimated_crimes_1979_2025.bin"
    retrieved_at = FBI_ANNUAL_RETRIEVED_AT
    if supplied_path is not None:
        payload = supplied_path.read_bytes()
        digest = sha256_bytes(payload)
        if digest != FBI_ANNUAL_RAW_SHA256:
            raise ValueError("fbi_annual_raw_hash_mismatch")
        atomic_write(target, payload)
    elif target.exists() and sha256_file(target) == FBI_ANNUAL_RAW_SHA256:
        pass
    elif download:
        # Never include the locator response or its signed URL in logs, metadata, or exceptions.
        try:
            locator_payload, status, _headers = request_bytes(FBI_SIGNED_LOCATOR_URL, timeout=45)
            if status != 200:
                raise ValueError("locator_status")
            locator = json.loads(locator_payload)
            signed = locator.get("awsFile") if isinstance(locator, dict) else None
            parsed = urllib.parse.urlsplit(signed or "")
            if parsed.scheme != "https" or parsed.netloc != "cde-prd-data.s3.us-gov-east-1.amazonaws.com" or parsed.path != "/additional-datasets/srs/estimated_crimes_1979_2025.csv":
                raise ValueError("locator_target_invalid")
            request = Request(signed, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=120) as response:
                payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise ValueError("fbi_annual_payload_over_limit")
                retrieved_at = utc_now()
            if sha256_bytes(payload) != FBI_ANNUAL_RAW_SHA256:
                raise ValueError("fbi_annual_raw_hash_mismatch")
            atomic_write(target, payload)
        except Exception as exc:
            # Prevent urllib exceptions from exposing signed query strings.
            raise ValueError("fbi_annual_public_download_failed:" + type(exc).__name__) from None
    else:
        return {"status": "source_missing", "sourceId": "fbi-srs-estimated-crimes-1979-2025"}
    digest = sha256_file(target)
    record = {"status": "downloaded" if download else "imported_verified", "sourceId": "fbi-srs-estimated-crimes-1979-2025",
              "path": str(target), "sha256": digest, "bytes": target.stat().st_size,
              "sourceUrl": FBI_ANNUAL_SAFE_URL, "retrievedAt": retrieved_at,
              "license": "FBI public-use data; source terms and attribution retained.",
              "formatObserved": "OOXML XLSX ZIP; catalog filename and HTTP content type say CSV"}
    meta = load_source_meta()
    meta["artifacts"][record["sourceId"]] = record
    atomic_json(source_meta_path(), meta)
    return record


def prepare_fbi_baseline_and_annual(raw_path: Path | None = None, download: bool = False) -> dict[str, Any]:
    """Prepare official 2025 annual counts/rates and contextual 2023 published rankings."""
    inventory_path = PUBLISHED_BEFORE_INVENTORY
    inventory = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else {"observations": []}
    states_by_fips = {fips: (abbr, name) for abbr, name, fips in FBI_STATES}
    values: dict[str, dict[str, Decimal]] = {}
    baseline_files = []
    for field in FBI_OFFENSES:
        field_id = f"{field}:derived"
        item = next((x for x in inventory.get("observations", []) if x.get("fieldId") == field_id), None)
        if not item or not Path(item["path"]).exists():
            continue
        if item.get("period") != "2023":
            continue
        payload = Path(item["path"]).read_bytes()
        if sha256_bytes(payload) != item.get("sha256"):
            raise ValueError("fbi_published_baseline_hash_mismatch")
        snapshot = json.loads(payload)
        if snapshot.get("fieldId") != field_id or snapshot.get("period") != "2023":
            raise ValueError("fbi_published_baseline_identity_mismatch")
        baseline_files.append({"fieldId": field_id, "path": item["path"], "sha256": item["sha256"]})
        for observation in snapshot.get("observations", []):
            state = observation.get("sourceGeoId") or observation.get("id")
            if observation.get("geoType") == "state" and state in states_by_fips:
                values.setdefault(field, {})[states_by_fips[state][0]] = Decimal(str(observation["value"]))
    raw_record = acquire_fbi_annual_raw(download, raw_path)
    if raw_record.get("status") == "source_missing":
        raise ValueError("fbi_annual_verified_input_required")
    official_rows, raw_hash = parse_fbi_annual(Path(raw_record["path"]))
    annual = []
    for source_row in official_rows:
        abbr = source_row["state_abbr"]
        fips = STATE_NAMES.get(abbr, (None, "US"))[1]
        for field_id, source_column in FBI_FIELD_COLUMNS.items():
            count = safe_int(source_row.get(source_column, ""))
            rate = Decimal(count) * Decimal(100000) / Decimal(source_row["population"]) if count is not None else None
            annual.append({"field_id": field_id + ":derived", "geo_type": "nation" if not abbr else "state",
                           "geo_id": fips, "state_abbr": abbr or "US", "state_name": source_row["state_name"],
                           "period": "2025", "period_type": "annual", "value": str(rate) if rate is not None else None,
                           "unit": "per 100,000", "numerator_count": count, "denominator_population": int(source_row["population"]),
                           "source_field": source_column, "source_adjustment": "official FBI SRS annual state estimate; rate computed from same-row FBI population",
                           "source_release": "FBI SRS Estimated Crimes 1979-2025 (August 2026)",
                           "source_url": FBI_ANNUAL_SAFE_URL, "retrieved_at": raw_record["retrievedAt"],
                           "source_sha256": raw_hash, "source_state_name": source_row["source_state_name"],
                           "source_footnote_marker": source_row["source_footnote_marker"],
                           "caveats": source_row.get("caveats", "")})
    annual_out = RUNTIME / "prepared/fbi-annual-estimates-2025.csv"
    write_csv(annual_out, annual)
    missing_rows = [{"field_id": row["field_id"], "state_abbr": row["state_abbr"], "period": "2025",
                     "source_field": row["source_field"], "status": "source_missing", "value": None,
                     "source_sha256": raw_hash} for row in annual if row["numerator_count"] is None]
    missing_out = RUNTIME / "prepared/fbi-annual-estimates-2025-missingness.jsonl"
    atomic_write(missing_out, b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in missing_rows))
    annual_ranks: dict[str, dict[str, int]] = {}
    for field_id in FBI_OFFENSES:
        eligible = [row for row in annual if row["field_id"] == field_id + ":derived" and row["geo_type"] == "state" and row["value"] is not None]
        annual_ranks[field_id] = {row["state_abbr"]: rank for rank, row in enumerate(
            sorted(eligible, key=lambda row: (-Decimal(row["value"]), row["state_abbr"])), 1)}
    rows = []
    for field, (slug, label) in FBI_OFFENSES.items():
        current = values.get(field, {})
        ranks = {state: rank for rank, (state, _value) in enumerate(
            sorted(current.items(), key=lambda item: (-item[1], item[0])), 1)}
        for abbr, name, fips in FBI_STATES:
            rows.append({"field_id": field, "offense": slug, "geo_id": fips, "state": abbr,
                         "state_name": name, "before_year": "2023", "before_value": str(current[abbr]) if abbr in current else None,
                         "before_rank_high_to_low": ranks.get(abbr), "after_year": "2025",
                         "after_annual_value": next((x["value"] for x in annual if x["field_id"] == field + ":derived" and x["state_abbr"] == abbr), None),
                         "after_annual_count": next((x["numerator_count"] for x in annual if x["field_id"] == field + ":derived" and x["state_abbr"] == abbr), None),
                         "after_annual_population": next((x["denominator_population"] for x in annual if x["field_id"] == field + ":derived" and x["state_abbr"] == abbr), None),
                         "after_annual_rank": annual_ranks[field].get(abbr),
                         "after_status": "official_2025_srs_annual_estimate_prepared",
                         "baselineMethod": "frozen 2023 published API rate for comparison only; source methodology says count / 2024 ACS population * 100000",
                         "comparisonCaveat": "2023 value is frozen published API evidence using count / 2024 ACS population; 2025 value uses FBI annual estimated count / FBI annual population. Cross-product ranks are context, not a direct trend series.",
                         "status": "cross_product_rank_context_only" if abbr in current else "baseline_missing_annual_after_prepared"})
    out = RUNTIME / "prepared/fbi-2023-baseline-2025-annual-ranks.csv"
    write_csv(out, rows)
    return {"status": "complete" if len(annual) == 364 else "partial", "baselineSource": str(inventory_path), "baselineSnapshots": baseline_files,
            "baselineObservations": sum(len(v) for v in values.values()),
            "baselineStateOffenseSeries": len(values), "annual2025Rows": len(annual), "nativeUSRows": sum(x["geo_type"] == "nation" for x in annual),
            "annualSource": raw_record, "annualOutput": str(annual_out), "annualMissingness": str(missing_out),
            "missingnessRows": len(missing_rows), "comparisonOutput": str(out),
            "rapeDefinition": "rape_revised source column; FBI revised definition; legacy rape is not substituted",
            "caveats": {row["state_abbr"]: row["caveats"] for row in official_rows if row["caveats"]}}


def income_per_resident(source_thousand_usd: Decimal, annual_population: int | None,
                        income_year: str, population_year: str) -> Decimal | None:
    if income_year != population_year:
        raise ValueError("income_population_year_mismatch")
    if annual_population is None or annual_population <= 0:
        return None
    return source_thousand_usd * Decimal(1000) / Decimal(annual_population)


def prepare_irs_income(population_result: dict[str, Any]) -> dict[str, Any]:
    path = RUNTIME / "raw/irs/23incyallagi.csv"
    pop_path = RUNTIME / "prepared/population-2023-2024.csv"
    if not path.exists() or not pop_path.exists():
        return {"status": "blocked_input", "missing": [str(p) for p in (path, pop_path) if not p.exists()]}
    try:
        population: dict[tuple[str, str, str], int] = {}
        for row in read_csv(pop_path):
            if row["year"] == "2023" and row["population_kind"] == "total" and row.get("value") not in {None, ""}:
                population[(row["geo_type"], row["geo_id"])] = int(row["value"])
        columns = {"STATEFIPS", "COUNTYFIPS", "agi_stub", "A00100"}
        sums: dict[str, Decimal] = {}
        state_names: dict[str, str] = {}
        row_count = 0
        county_bands: dict[str, set[str]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not columns.issubset(reader.fieldnames or ()):
                raise ValueError("irs_required_columns_missing")
            for row in reader:
                state = row["STATEFIPS"].strip().zfill(2)
                county = row["COUNTYFIPS"].strip().zfill(3)
                stub = row["agi_stub"].strip()
                if state not in STATE_FIPS or county == "000":
                    continue
                if stub not in {str(i) for i in range(1, 9)}:
                    continue
                value = Decimal(row["A00100"])
                if not value.is_finite():
                    raise ValueError("irs_nonfinite_a00100")
                fips = state + county
                sums[fips] = sums.get(fips, Decimal(0)) + value
                county_bands.setdefault(fips, set()).add(stub)
                row_count += 1
        if len(sums) != 3143:
            raise ValueError(f"irs_county_coverage_{len(sums)}_of_3143")
        incomplete_bands = [fips for fips, bands in county_bands.items()
                            if bands != {str(i) for i in range(1, 9)}]
        if incomplete_bands:
            raise ValueError(f"irs_incomplete_agi_bands_{len(incomplete_bands)}_counties")
        income_rows: list[dict[str, Any]] = []
        resident_rows: list[dict[str, Any]] = []
        missing_population: list[dict[str, Any]] = []
        # IRS A00100 source values are thousand USD; keep the exact source sum and conversion.
        state_income: dict[str, Decimal] = {}
        for fips, thousand_usd in sorted(sums.items()):
            state_income[fips[:2]] = state_income.get(fips[:2], Decimal(0)) + thousand_usd
            usd = thousand_usd * 1000
            income_rows.append({"geo_id": fips, "geo_type": "county", "year": "2023",
                                "field": "A00100", "source_value_thousand_usd": str(thousand_usd),
                                "value_usd": str(usd), "unit": "USD", "source_release": "IRS SOI County 2023",
                                "conversion": "source thousand_USD * 1000"})
            denominator = population.get(("county", fips))
            if denominator is None:
                missing_population.append({"geo_id": fips, "geo_type": "county", "year": "2023",
                                           "reason": "matching_year_population_not_available"})
            elif denominator > 0:
                resident_value = income_per_resident(thousand_usd, denominator, "2023", "2023")
                resident_rows.append({"geo_id": fips, "geo_type": "county", "year": "2023",
                                      "income_usd": str(usd), "population": denominator,
                                      "value": str(resident_value), "unit": "USD/person",
                                      "source_release": "IRS SOI County 2023; Census PEP Vintage 2025",
                                      "formula": "(A00100 thousand USD * 1000) / 2023 annual population"})
            else:
                missing_population.append({"geo_id": fips, "geo_type": "county", "year": "2023",
                                           "reason": "nonpositive_population"})
        for state in sorted(state_income):
            name = next((state_name for _, state_name, fips in FBI_STATES if fips == state), state)
            state_fips = state
            usd = state_income[state] * 1000
            income_rows.append({"geo_id": state_fips, "geo_type": "state", "year": "2023",
                                "field": "A00100", "source_value_thousand_usd": str(state_income[state]),
                                "value_usd": str(usd), "unit": "USD", "source_release": "IRS SOI County 2023",
                                "aggregation": "sum county A00100 bands 1-8; source state total excluded"})
            denominator = population.get(("state", state_fips))
            if denominator is None:
                missing_population.append({"geo_id": state_fips, "geo_type": "state", "year": "2023",
                                           "reason": "matching_year_population_not_available"})
            elif denominator > 0:
                resident_value = income_per_resident(state_income[state], denominator, "2023", "2023")
                resident_rows.append({"geo_id": state_fips, "geo_type": "state", "year": "2023",
                                      "income_usd": str(usd), "population": denominator,
                                      "value": str(resident_value), "unit": "USD/person",
                                      "source_release": "IRS SOI County 2023; Census PEP Vintage 2025",
                                      "formula": "(sum county A00100 thousand USD * 1000) / 2023 annual population"})
        national_thousand = sum(state_income.values(), Decimal(0))
        national_usd = national_thousand * 1000
        income_rows.append({"geo_id": "US", "geo_type": "nation", "year": "2023", "field": "A00100",
                            "source_value_thousand_usd": str(national_thousand), "value_usd": str(national_usd),
                            "unit": "USD", "source_release": "IRS SOI County 2023",
                            "aggregation": "sum county A00100 bands 1-8; state rows excluded"})
        national_population = population.get(("nation", "US"))
        if national_population and national_population > 0:
            resident_value = income_per_resident(national_thousand, national_population, "2023", "2023")
            resident_rows.append({"geo_id": "US", "geo_type": "nation", "year": "2023",
                                  "income_usd": str(national_usd), "population": national_population,
                                  "value": str(resident_value),
                                  "unit": "USD/person", "source_release": "IRS SOI County 2023; Census PEP Vintage 2025",
                                  "formula": "(sum county A00100 thousand USD * 1000) / 2023 annual population"})
        else:
            missing_population.append({"geo_id": "US", "geo_type": "nation", "year": "2023",
                                       "reason": "matching_year_population_not_available"})
        income_out = RUNTIME / "prepared/irs-agi-2023-usd.csv"
        per_person_out = RUNTIME / "prepared/irs-agi-per-resident-2023.csv"
        write_csv(income_out, income_rows)
        write_csv(per_person_out, resident_rows)
        write_jsonl(RUNTIME / "prepared/irs-agi-missing-denominators.jsonl", missing_population)
        return {"status": "complete" if not missing_population else "partial",
                "inputRowsUsed": row_count, "countyRows": len(sums), "stateRows": len(state_income),
                "preparedIncomeRows": len(income_rows), "preparedPerResidentRows": len(resident_rows),
                "missingDenominators": len(missing_population), "incomeOutput": str(income_out),
                "perResidentOutput": str(per_person_out)}
    except (OSError, ValueError, InvalidOperation, KeyError) as error:
        return {"status": "downloaded_unparsed", "reason": str(error)}


def prepare_existing_medical_rates() -> dict[str, Any]:
    """Recalculate reviewed 2024 rates from retained prepared counts and matching PEP denominators."""
    population_path = RUNTIME / "prepared/population-2023-2024.csv"
    if not population_path.exists():
        return {"status": "blocked_population_input"}
    metric = {"cancer2023": ("11.01", "total", "2023", "2023"),
              "hiv2024": ("11.02", "age_13_plus", "2024", "2024"),
              "childDeaths2024": ("11.03", "under_18", "2024", "2024")}
    denominators = {(row["geo_type"], row["geo_id"], row["year"], row["population_kind"]): int(row["value"])
                    for row in read_csv(population_path)}
    results = {}
    for name, source_path in MEDICAL_RECEIPTS.items():
        if not source_path.exists():
            results[name] = {"status": "retained_prepared_source_missing", "sourcePath": str(source_path)}
            continue
        payload = source_path.read_bytes()
        safe_name = {"cancer2023": "cancer-2023", "hiv2024": "hiv-2024",
                     "childDeaths2024": "child-deaths-under18-2024"}[name]
        raw_path = RUNTIME / f"raw/retained-prepared/{safe_name}.jsonl"
        atomic_write(raw_path, payload)
        publisher_source, publisher_url, publisher_retrieval_date, publisher_license = MEDICAL_PUBLISHER_RAW[name]
        publisher_receipt = None
        publisher_retrieval_date = None
        if publisher_source.exists():
            publisher_bytes = publisher_source.read_bytes()
            publisher_hash = sha256_bytes(publisher_bytes)
            receipt_path = MEDICAL_SOURCE_RECEIPTS[name]
            receipt_meta = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
            expected_source_hash = (receipt_meta.get("sha256") or receipt_meta.get("response_sha256")
                                    or receipt_meta.get("result_sha256"))
            if expected_source_hash and expected_source_hash != publisher_hash:
                raise ValueError("medical_publisher_raw_receipt_hash_mismatch")
            publisher_retrieval_date = (receipt_meta.get("retrieved_utc") or receipt_meta.get("attempted_at_utc")
                                        or receipt_meta.get("retrieved_at"))
            publisher_target = RUNTIME / "raw/retained-publisher" / (safe_name + publisher_source.suffix)
            atomic_write(publisher_target, publisher_bytes)
            publisher_receipt = {"sourceId": "retained-publisher-" + safe_name, "path": str(publisher_target),
                                 "originalLocalPath": str(publisher_source), "url": publisher_url,
                                 "sha256": publisher_hash, "bytes": len(publisher_bytes),
                                 "retrievedAt": publisher_retrieval_date, "retrievalReceiptPath": str(receipt_path),
                                 "retrievalReceiptSha256": sha256_file(receipt_path) if receipt_path.exists() else None,
                                 "license": publisher_license, "status": "copied_verified_original_publisher_receipt"}
        source_rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
        rows, missing = [], []
        for source in source_rows:
            field_id, kind, observation_year, denominator_year = metric[name]
            require_matching_year(observation_year, denominator_year)
            if source.get("year") != observation_year or source.get("geo_type") != "state":
                continue
            count = safe_int(str(source.get("value")))
            population = denominators.get(("state", source["geo_id"], denominator_year, kind))
            suppressed = name == "childDeaths2024" and count is not None and count <= 9
            if count is None or population is None or population <= 0 or suppressed:
                missing.append({"geo_id": source.get("geo_id"), "year": observation_year, "status":
                                "source_suppressed" if suppressed else "missing_count_or_matching_denominator"})
                continue
            rows.append({"geo_id": source["geo_id"], "geo_type": "state", "year": observation_year,
                         "field_id": field_id,
                         "value": str(Decimal(count) / Decimal(population) * Decimal(100000)),
                         "unit": "per 100,000", "numerator": count, "denominator": population,
                         "denominator_kind": kind, "denominator_year": denominator_year,
                         "source_adjustment": "crude; count divided by matching PEP population",
                         "source_period_type": "annual", "source_period": observation_year,
                         "source_release": source.get("source_release"), "source_url": source.get("source_url"),
                         "source_retrieved_at": source.get("retrieved_at"),
                         "source_input_sha256": sha256_bytes(payload), "status": "prepared_local"})
        # Only add national values present as actual publisher rows. Never sum states.
        if name == "cancer2023":
            if publisher_source.exists():
                raw_bytes = publisher_source.read_bytes()
                raw_data = json.loads(raw_bytes.decode("utf-8"))
                if isinstance(raw_data, str):
                    raw_data = json.loads(raw_data)
                publisher_rows = raw_data[0].get("LandingPageMapData_Inci", []) if raw_data else []
                us_rows = [entry for entry in publisher_rows if entry.get("YearID") == 1
                           and entry.get("GeoLocationID") == 1 and entry.get("CancerSiteID") == 1
                           and entry.get("DataTypeID") == 1 and entry.get("RaceID") == 1
                           and entry.get("SexID") == 1]
                if len(us_rows) == 1:
                    count = safe_int(str(us_rows[0].get("count")))
                    population = denominators.get(("nation", "US", "2023", "total"))
                    if count is not None and population:
                        rows.append({"geo_id": "US", "geo_type": "national", "year": "2023",
                                     "field_id": "11.01", "value": str(Decimal(count) / Decimal(population) * Decimal(100000)),
                                     "unit": "per 100,000", "numerator": count, "denominator": population,
                                     "denominator_kind": "total", "denominator_year": "2023",
                                     "source_adjustment": "crude; publisher US count divided by matching PEP population",
                                     "source_period_type": "annual", "source_period": "2023",
                                     "source_release": "USCS 2026 submission; 2023 incidence",
                                     "source_url": "https://gis.cdc.gov/Cancer/USCS/",
                                     "source_retrieved_at": publisher_retrieval_date,
                                     "source_snapshot_date": (publisher_retrieval_date[:10] if publisher_retrieval_date else None),
                                     "source_input_sha256": sha256_bytes(raw_bytes), "status": "prepared_local_publisher_national_count"})
        out = RUNTIME / f"prepared/{safe_name}-rates.csv"
        missingness_out = RUNTIME / f"prepared/{safe_name}-rates-missingness.jsonl"
        write_csv(out, rows)
        write_jsonl(missingness_out, missing)
        receipt = {"sourceId": "retained-prepared-" + safe_name, "path": str(raw_path),
                   "sha256": sha256_bytes(payload), "bytes": len(payload),
                   "retrievedAt": max((row.get("retrieved_at", "") for row in source_rows), default="") or None,
                   "status": "copied_verified_prepared_receipt", "sourceArtifactType": "prior_normalized_observations",
                   "originalLocalPath": str(source_path),
                   "license": "Prepared official-source-derived evidence; row-level source citations are retained."}
        atomic_json(raw_path.with_suffix(".meta.json"), receipt)
        results[name] = {"status": "complete" if len(rows) + len(missing) >= 51 else "partial",
                         "observedRows": len(rows), "missingnessRows": len(missing), "sourceReceipt": receipt,
                         "output": str(out), "outputSha256": sha256_file(out),
                         "missingnessOutput": str(missingness_out), "missingnessSha256": sha256_file(missingness_out),
                         "missingness": missing, "publisherRawReceipt": publisher_receipt}
    return results


def require_matching_year(event_year: str, denominator_year: str) -> None:
    if str(event_year) != str(denominator_year):
        raise ValueError("health_event_denominator_year_mismatch")


def import_completed_bls(source_dir: Path, results_path: Path) -> dict[str, Any]:
    """Import and verify the parent's completed BLS run without making requests."""
    wrapper = json.loads(results_path.read_text(encoding="utf-8"))
    result = wrapper.get("result", {})
    if any(result.get(key) != value for key, value in BLS_PARENT_EXPECTED.items()):
        raise ValueError("bls_parent_run_summary_mismatch")
    if result.get("credentialMode") != "registered" or result.get("status") != "partial":
        raise ValueError("bls_parent_run_not_expected_completed_source_gap_status")
    artifacts = result.get("rawArtifacts", [])
    if len(artifacts) != BLS_PARENT_EXPECTED["batchCount"]:
        raise ValueError("bls_parent_raw_artifact_count_mismatch")
    seen = set()
    provenance_by_series: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        path = Path(artifact["path"])
        meta_path = path.with_suffix(".meta.json")
        if artifact.get("status") not in {"downloaded", "reused_verified"}:
            raise ValueError("bls_parent_batch_not_successful")
        raw = path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        digest = sha256_bytes(raw)
        for key in ("sha256", "requestFingerprint", "queueHash", "planVersion"):
            if artifact.get(key) != meta.get(key):
                raise ValueError("bls_parent_batch_metadata_mismatch")
        if (digest != artifact.get("sha256") or meta.get("sha256") != digest
                or not meta.get("requestFingerprint") or not meta.get("queueHash")
                or meta.get("planVersion") != BLS_PLAN_VERSION):
            raise ValueError("bls_parent_batch_hash_or_plan_mismatch")
        seen.add(meta["requestFingerprint"])
        payload = json.loads(raw.decode("utf-8"))
        for series in payload.get("Results", {}).get("series", []):
            sid = series.get("seriesID")
            if sid:
                provenance_by_series[sid] = {"raw_sha256": digest, "retrieved_at": meta.get("retrievedAt"),
                                             "raw_artifact_path": str(path), "request_fingerprint": meta["requestFingerprint"],
                                             "queue_hash": meta["queueHash"], "plan_version": meta["planVersion"]}
    if len(seen) != BLS_PARENT_EXPECTED["batchCount"]:
        raise ValueError("bls_parent_batch_fingerprint_duplicate")
    receipts = []
    for filename in BLS_PARENT_FILENAMES:
        source = source_dir / filename
        content = source.read_bytes()
        expected_hash = {"bls-laus-2025.csv": "69d1129d1293086a782ea249b20fc2fe50768656f4755e483f787dc3334fad7c",
                         "bls-laus-2025-missingness.jsonl": "85407a19d28a6e02680c2d748c3f45b952368a27249a6c18b69a224c89cad97f",
                         "bls-laus-2025-coverage.csv": "d815de463916dd11685e5869b726961b69ed240325b614cca1de18bb912f56ef"}[filename]
        if sha256_bytes(content) != expected_hash:
            raise ValueError("bls_parent_prepared_hash_mismatch")
        target = RUNTIME / "prepared" / filename
        atomic_write(target, content)
        receipts.append({"path": str(target), "sha256": expected_hash, "bytes": len(content),
                         "sourcePath": str(source), "status": "copied_verified_prepared_artifact"})
    source_rows = list(read_csv(RUNTIME / "prepared/bls-laus-2025.csv"))
    enriched_rows = []
    for row in source_rows:
        provenance = provenance_by_series.get(row["series_id"])
        if not provenance:
            raise ValueError("bls_prepared_series_missing_raw_provenance")
        enriched_rows.append({**row, **provenance, "source_release": "BLS LAUS 2025 NSA; API v2; retrieved 2026-10-26",
                              "source_url": BLS_URL, "source_adjustment": "not seasonally adjusted (NSA)"})
    missing_path = source_dir / "bls-laus-2025-missingness.jsonl"
    missing = [json.loads(line) for line in missing_path.read_text(encoding="utf-8").splitlines() if line]
    loader_path = RUNTIME / "prepared/bls-laus-2025-loader.csv"
    write_csv(loader_path, enriched_rows)
    receipts.append({"path": str(loader_path), "sha256": sha256_file(loader_path), "bytes": loader_path.stat().st_size,
                     "status": "derived_loader_input_with_batch_provenance"})
    missing_enriched = []
    for row in missing:
        provenance = provenance_by_series.get(row["series_id"])
        if not provenance:
            raise ValueError("bls_missingness_series_missing_raw_provenance")
        missing_enriched.append({**row, **provenance, "source_release": "BLS LAUS 2025 NSA; API v2; retrieved 2026-10-26",
                                 "source_url": BLS_URL, "source_adjustment": "not seasonally adjusted (NSA)"})
    missing_loader_path = RUNTIME / "prepared/bls-laus-2025-loader-missingness.jsonl"
    write_jsonl(missing_loader_path, missing_enriched)
    m10 = sum(item.get("bls_period_code") == "M10" and item.get("status") == "source_missing"
              for item in missing)
    coverage = list(read_csv(RUNTIME / "prepared/bls-laus-2025-coverage.csv"))
    annual_count = sum(row.get("annualM13Present", "").lower() == "true" for row in coverage)
    if m10 != 12776 or annual_count != 12776 or len(coverage) != 12780:
        raise ValueError("bls_parent_prepared_semantic_counts_mismatch")
    return {**{key: result[key] for key in BLS_PARENT_EXPECTED},
            "status": "collection_complete_with_source_gaps", "credentialMode": "registered",
            "sourceCodeSha256": wrapper.get("executedSourceSha256"), "rawArtifacts": artifacts,
            "preparedArtifacts": receipts, "missingOctoberSeries": m10,
            "loaderInput": str(loader_path), "loaderInputSha256": sha256_file(loader_path),
            "loaderMissingnessInput": str(missing_loader_path),
            "loaderMissingnessSha256": sha256_file(missing_loader_path),
            "officialAnnualM13Series": annual_count,
            "sourceGaps": ["M10 absent for 12,776 series", "52 series have no returned periods"],
            "sourceResultPath": str(results_path),
            "note": "All 256 planned requests completed; publisher data are incomplete for stated gaps. Missing values are not filled."}


def bls_series_id(geo_type: str, geo_id: str, measure: str) -> str:
    if geo_type == "state":
        if len(geo_id) != 2 or geo_id not in STATE_FIPS:
            raise ValueError("invalid_state_fips")
        return f"LAUST{geo_id}{'0' * 11}{measure}"
    if geo_type == "county":
        if len(geo_id) != 5 or geo_id[:2] not in STATE_FIPS:
            raise ValueError("invalid_county_fips")
        return f"LAUCN{geo_id}{'0' * 8}{measure}"
    raise ValueError("unsupported_bls_geography")


def period_info(year: str, code: str) -> tuple[str, str]:
    if code == "M13":
        return year, "annual"
    match = re.fullmatch(r"M(0[1-9]|1[0-2])", code)
    if not match:
        raise ValueError("invalid_bls_period")
    return f"{year}-{match.group(1)}", "monthly"


def parse_bls_payload(payload: bytes, series_meta: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(payload.decode("utf-8"))
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("bls_request_not_succeeded")
    result = data.get("Results", {})
    series_rows = result.get("series", []) if isinstance(result, dict) else []
    values: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    returned: set[str] = set()
    for series in series_rows:
        sid = series.get("seriesID", "")
        meta = series_meta.get(sid)
        if not meta:
            continue
        returned.add(sid)
        returned_periods: set[str] = set()
        for row in series.get("data", []):
            if row.get("year") != "2025":
                continue
            code = row.get("period", "")
            period, period_type = period_info(row["year"], code)
            returned_periods.add(code)
            footnotes = [f.get("text", "") for f in row.get("footnotes", []) if f and f.get("text")]
            source_value = row.get("value")
            raw_value = "" if source_value is None else str(source_value)
            if raw_value.strip() in {"", "-", "—", "NA", "N/A"}:
                missing.append({**meta, "series_id": sid, "period": period, "period_type": period_type,
                                "bls_period_code": code, "value": None, "raw_value": raw_value,
                                "status": "source_missing", "footnote": " | ".join(footnotes)})
                continue
            numeric = Decimal(raw_value)
            values.append({**meta, "series_id": sid, "period": period, "period_type": period_type,
                           "bls_period_code": code, "value": str(numeric), "raw_value": raw_value,
                           "unit": BLS_MEASURES[meta["measure_code"]][1], "status": "observed",
                           "footnote": " | ".join(footnotes)})
        for code in [*(f"M{month:02d}" for month in range(1, 13)), "M13"]:
            if code in returned_periods:
                continue
            period, period_type = period_info("2025", code)
            missing.append({**meta, "series_id": sid, "period": period, "period_type": period_type,
                            "bls_period_code": code, "value": None, "raw_value": None,
                            "status": "period_not_returned", "footnote": ""})
    for sid, meta in series_meta.items():
        if sid not in returned:
            missing.append({**meta, "series_id": sid, "period": "2025", "period_type": "series",
                            "bls_period_code": None, "value": None, "raw_value": None,
                            "status": "series_not_returned", "footnote": ""})
    return values, missing


def bls_ledger_path() -> Path:
    return RUNTIME / "state/bls-request-ledger.json"


def load_bls_ledger() -> dict[str, Any]:
    path = bls_ledger_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("format") == "bls_request_ledger_v2":
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"format": "bls_request_ledger_v2", "days": {}}


def bls_batch_fingerprint(series: list[dict[str, str]], batch_number: int, batch_size: int) -> tuple[str, str]:
    ordered_ids = [item["series_id"] for item in series]
    queue_hash = sha256_bytes(json.dumps(ordered_ids, separators=(",", ":")).encode())
    request = {"planVersion": BLS_PLAN_VERSION, "queueHash": queue_hash, "batchNumber": batch_number,
               "batchSize": batch_size, "seriesIds": ordered_ids, "startyear": "2025", "endyear": "2025",
               "annualaverage": True, "adjustment": "NSA", "method": "BLS_v2_seriesid_batch"}
    return queue_hash, sha256_bytes(json.dumps(request, sort_keys=True, separators=(",", ":")).encode())


def fetch_bls_batch(batch_number: int, series: list[dict[str, str]],
                    budget: int, batch_size: int = 24, queue_hash: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    actual_queue_hash, fingerprint = bls_batch_fingerprint(series, batch_number, batch_size)
    queue_hash = queue_hash or actual_queue_hash
    raw_path = RUNTIME / f"raw/bls/plans/{queue_hash}/{fingerprint}.json"
    meta_path = raw_path.with_suffix(".meta.json")
    selected = {item["series_id"]: {k: v for k, v in item.items() if k != "series_id"} for item in series}
    retrieved_at = utc_now()
    if raw_path.exists() and meta_path.exists():
        try:
            raw = raw_path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if (meta.get("sha256") == sha256_bytes(raw) and meta.get("requestFingerprint") == fingerprint
                    and meta.get("queueHash") == queue_hash and meta.get("planVersion") == BLS_PLAN_VERSION):
                values, missing = parse_bls_payload(raw, selected)
                return values, missing, {**meta, "status": "reused_verified", "path": str(raw_path)}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    request_body = {"seriesid": [item["series_id"] for item in series],
                    "startyear": "2025", "endyear": "2025", "annualaverage": True}
    api_key = os.getenv("BLS_API_KEY")
    if api_key:
        request_body["registrationkey"] = api_key
    body = json.dumps(request_body).encode()
    try:
        payload, status, headers = request_bytes(BLS_URL, body,
                                                 {"Content-Type": "application/json"}, timeout=45)
        if not source_bytes_safe(payload):
            raise ValueError("provider_response_redacted_for_secret_safety")
        data = json.loads(payload.decode("utf-8"))
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise ValueError("provider_status_rejected")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(raw_path, payload)
        artifact = {"sourceId": "bls-laus-public-api-v2", "url": public_url(BLS_URL),
                    "path": str(raw_path), "sha256": sha256_bytes(payload), "bytes": len(payload),
                    "retrievedAt": retrieved_at, "httpStatus": status,
                    "contentType": headers.get("Content-Type"), "status": "downloaded",
                    "license": "BLS API terms apply; attribution and retrieval timestamp retained.",
                    "seriesCount": len(series), "credentialMode": "registered" if api_key else "public_no_key",
                    "queueHash": queue_hash, "requestFingerprint": fingerprint, "planVersion": BLS_PLAN_VERSION}
        atomic_json(meta_path, artifact)
        values, missing = parse_bls_payload(payload, selected)
        return values, missing, artifact
    except HTTPError as error:
        reason = "daily_limit_reached" if error.code == 429 else f"http_{error.code}"
        return [], [{"series_id": item["series_id"], "geo_id": item["geo_id"],
                     "geo_type": item["geo_type"], "measure_code": item["measure_code"],
                     "period": "2025", "period_type": "series", "value": None,
                     "status": reason, "footnote": ""} for item in series], {
                         "sourceId": "bls-laus-public-api-v2", "url": public_url(BLS_URL),
                         "attemptedAt": retrieved_at, "httpStatus": error.code,
                         "status": "blocked_http", "reason": reason,
                     }
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        return [], [{"series_id": item["series_id"], "geo_id": item["geo_id"],
                     "geo_type": item["geo_type"], "measure_code": item["measure_code"],
                     "period": "2025", "period_type": "series", "value": None,
                     "status": "request_failed", "footnote": ""} for item in series], {
                         "sourceId": "bls-laus-public-api-v2", "url": public_url(BLS_URL),
                         "attemptedAt": retrieved_at, "status": "unavailable",
                         "reason": type(error).__name__,
                     }


def load_population_for_bls() -> tuple[list[dict[str, Any]], dict[str, int]]:
    pop_path = RUNTIME / "prepared/population-2023-2024.csv"
    if not pop_path.exists():
        return [], {}
    geos = []
    pop2024: dict[str, int] = {}
    for row in read_csv(pop_path):
        if row.get("year") != "2024" or row.get("population_kind") != "total":
            continue
        if row.get("geo_type") == "state":
            geos.append({"geo_type": "state", "geo_id": row["geo_id"], "name": row["geo_id"]})
        elif row.get("geo_type") == "county":
            geos.append({"geo_type": "county", "geo_id": row["geo_id"], "name": row["geo_id"]})
            pop2024[row["geo_id"]] = int(row["value"])
    # Ensure exactly the 50 states and DC even if the source file omits summary rows.
    have_states = {row["geo_id"] for row in geos if row["geo_type"] == "state"}
    for _abbr, _name, fips in FBI_STATES:
        if fips not in have_states:
            geos.append({"geo_type": "state", "geo_id": fips, "name": _name})
    counties = {row["geo_id"]: row for row in geos if row["geo_type"] == "county"}
    geos = [row for row in geos if row["geo_type"] == "state"] + list(counties.values())
    return geos, pop2024


def make_bls_queue(geos: list[dict[str, Any]], pop2024: dict[str, int]) -> list[dict[str, str]]:
    states = sorted((geo for geo in geos if geo["geo_type"] == "state"), key=lambda geo: geo["geo_id"])
    counties = [geo for geo in geos if geo["geo_type"] == "county"]
    # Include at least one county from every state before taking remaining counties by population.
    largest_by_state: list[dict[str, Any]] = []
    for fips in sorted(STATE_FIPS):
        candidates = [geo for geo in counties if geo["geo_id"].startswith(fips)]
        if candidates:
            largest_by_state.append(max(candidates, key=lambda geo: pop2024.get(geo["geo_id"], 0)))
    first_ids = {geo["geo_id"] for geo in largest_by_state}
    remaining = sorted((geo for geo in counties if geo["geo_id"] not in first_ids),
                       key=lambda geo: (-pop2024.get(geo["geo_id"], 0), geo["geo_id"]))
    ordered = states + largest_by_state + remaining
    result = []
    for geo in ordered:
        for measure in BLS_MEASURES:
            result.append({"series_id": bls_series_id(geo["geo_type"], geo["geo_id"], measure),
                           "geo_id": geo["geo_id"], "geo_type": geo["geo_type"],
                           "measure_code": measure, "measure": BLS_MEASURES[measure][0]})
    return result


def collect_bls(max_queries: int) -> dict[str, Any]:
    geos, pop2024 = load_population_for_bls()
    if not geos:
        return {"status": "blocked_population_input"}
    queue = make_bls_queue(geos, pop2024)
    # Registered BLS v2 accepts up to 50 series per request; no-key mode stays below 25.
    batch_size = 50 if os.getenv("BLS_API_KEY") else 24
    batches = [queue[i:i + batch_size] for i in range(0, len(queue), batch_size)]
    ledger = load_bls_ledger()
    day = datetime.now(timezone.utc).date().isoformat()
    day_record = ledger["days"].setdefault(day, {"registeredQueriesUsed": 0, "unregisteredQueriesUsed": 0})
    registered = bool(os.getenv("BLS_API_KEY"))
    mode = "registered" if registered else "unregistered"
    budget_left = min(max_queries, max(0, BLS_DAILY_LIMIT - int(day_record.get("registeredQueriesUsed", 0)))) if registered else min(
        max_queries, max(0, BLS_DAILY_BUDGET - int(day_record.get("unregisteredQueriesUsed", 0))))
    ordered_queue_hash = sha256_bytes(json.dumps([item["series_id"] for item in queue], separators=(",", ":")).encode())
    plan_id = sha256_bytes(f"{BLS_PLAN_VERSION}:{ordered_queue_hash}:{batch_size}".encode())[:20]
    checkpoint_path = RUNTIME / f"state/bls-checkpoint-{plan_id}.json"
    checkpoint = {}
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checkpoint = {}
    done = set(checkpoint.get("completedBatchNumbers", [])) if (
        checkpoint.get("queueHash") == ordered_queue_hash and checkpoint.get("planVersion") == BLS_PLAN_VERSION
        and checkpoint.get("batchSize") == batch_size) else set()
    raw_values: list[dict[str, Any]] = []
    raw_missing: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    requests_this_run = 0
    stopped = False
    for number, batch in enumerate(batches):
        if number in done:
            # Load only the completed batch needed for deterministic regenerated outputs.
            _qhash, fingerprint = bls_batch_fingerprint(batch, number, batch_size)
            raw_path = RUNTIME / f"raw/bls/plans/{ordered_queue_hash}/{fingerprint}.json"
            meta_path = raw_path.with_suffix(".meta.json")
            if raw_path.exists() and meta_path.exists():
                expected = {item["series_id"]: {k: v for k, v in item.items() if k != "series_id"} for item in batch}
                try:
                    payload = raw_path.read_bytes()
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if (meta.get("sha256") == sha256_bytes(payload) and meta.get("requestFingerprint") == fingerprint
                            and meta.get("queueHash") == ordered_queue_hash and meta.get("planVersion") == BLS_PLAN_VERSION):
                        values, missing = parse_bls_payload(payload, expected)
                        raw_values.extend(values)
                        raw_missing.extend(missing)
                        artifacts.append({**meta, "status": "reused_verified", "path": str(raw_path)})
                        continue
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    pass
            done.remove(number)
        if requests_this_run >= budget_left:
            stopped = True
            break
        values, missing, artifact = fetch_bls_batch(number, batch, budget_left, batch_size, ordered_queue_hash)
        requests_this_run += 1
        counter = "registeredQueriesUsed" if registered else "unregisteredQueriesUsed"
        day_record[counter] = int(day_record.get(counter, 0)) + 1
        atomic_json(bls_ledger_path(), ledger)
        if artifact.get("status") in {"downloaded", "reused_verified"}:
            done.add(number)
            atomic_json(checkpoint_path, {"format": "bls_checkpoint_v2", "completedBatchNumbers": sorted(done),
                                         "totalBatches": len(batches), "queueHash": ordered_queue_hash,
                                         "planVersion": BLS_PLAN_VERSION, "batchSize": batch_size, "updatedAt": utc_now()})
        else:
            stopped = True
        raw_values.extend(values)
        raw_missing.extend(missing)
        artifacts.append(artifact)
        print(f"BLS batch {number + 1}/{len(batches)}: {artifact['status']} ({len(batch)} series)", flush=True)
        if artifact.get("reason") == "daily_limit_reached":
            break
    write_csv(RUNTIME / "prepared/bls-laus-2025.csv", raw_values)
    write_jsonl(RUNTIME / "prepared/bls-laus-2025-missingness.jsonl", raw_missing)
    monthly_coverage: dict[str, set[str]] = {}
    annual_coverage: set[str] = set()
    for row in raw_values:
        if row["period_type"] == "monthly":
            monthly_coverage.setdefault(row["series_id"], set()).add(row["bls_period_code"])
        elif row["bls_period_code"] == "M13":
            annual_coverage.add(row["series_id"])
    coverage_rows = []
    requested_ids = {row["series_id"] for row in raw_values + raw_missing}
    for item in queue:
        sid = item["series_id"]
        if sid not in requested_ids:
            continue
        periods = monthly_coverage.get(sid, set())
        expected = {f"M{month:02d}" for month in range(1, 13)}
        coverage_rows.append({"geo_type": item["geo_type"], "geo_id": item["geo_id"],
                              "measure_code": item["measure_code"], "series_id": sid,
                              "monthlyPeriodsPresent": len(periods),
                              "missingPeriods": ",".join(sorted(expected - periods)),
                              "annualM13Present": sid in annual_coverage,
                              "status": "complete" if len(periods) == 12 else "partial_or_source_missing"})
    write_csv(RUNTIME / "prepared/bls-laus-2025-coverage.csv", coverage_rows)
    states_returned = {row["geo_id"] for row in raw_values if row["geo_type"] == "state"}
    counties_returned = {row["geo_id"] for row in raw_values if row["geo_type"] == "county"}
    return {
        "status": ("partial" if stopped or len(done) < len(batches) else
                   "collection_complete_with_source_gaps" if raw_missing else "complete"),
        "seriesCount": len(queue), "batchCount": len(batches), "completedBatchCount": len(done),
        "queriesThisRun": requests_this_run, "dailyNoKeyLimit": BLS_DAILY_LIMIT,
        "dailyBudget": None if registered else BLS_DAILY_BUDGET,
        "registeredQueriesRecorded": day_record.get("registeredQueriesUsed", 0),
        "unregisteredQueriesRecorded": day_record.get("unregisteredQueriesUsed", 0),
        "credentialMode": "registered" if registered else "public_no_key",
        "statesWithReturnedObservations": len(states_returned), "countiesWithReturnedObservations": len(counties_returned),
        "observedRows": len(raw_values), "missingnessRows": len(raw_missing),
        "pendingSeriesCount": max(0, len(queue) - sum(len(batches[n]) for n in done)),
        "rawArtifacts": artifacts,
        "outputs": [str(RUNTIME / "prepared/bls-laus-2025.csv"),
                    str(RUNTIME / "prepared/bls-laus-2025-missingness.jsonl"),
                    str(RUNTIME / "prepared/bls-laus-2025-coverage.csv")],
        "note": "M13 is retained as annual. M01-M12 are not averaged to create M13. Missing periods remain missing.",
    }


def fbi_raw_path(state: str, offense: str) -> Path:
    return RUNTIME / f"raw/fbi/2025/{state}-{offense}.json"


def fbi_response_rows(payload: bytes, state: str, offense_id: str, offense_slug: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(payload.decode("utf-8"))
    offenses = data.get("offenses", {})
    if not isinstance(offenses, dict):
        raise ValueError("fbi_offenses_object_missing")
    state_name = STATE_NAMES[state][0]
    found: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for family, unit in (("actuals", "offenses"), ("rates", "per_100000")):
        records = offenses.get(family, {})
        if not isinstance(records, dict):
            continue
        matching = [(label, periods) for label, periods in records.items()
                    if label.casefold() == (state_name + " offenses").casefold()]
        if not matching:
            missing.append({"geo_id": state, "geo_type": "state", "field_id": offense_id,
                            "year": "2025", "unit": unit, "status": "source_series_missing",
                            "source_field": family})
            continue
        for _label, periods in matching:
            if not isinstance(periods, dict):
                continue
            for period in (f"{month:02d}-2025" for month in range(1, 13)):
                value = periods.get(period)
                if value in (None, "", "-", "--"):
                    missing.append({"geo_id": state, "geo_type": "state", "field_id": offense_id,
                                    "year": "2025", "period": "2025-" + period[:2], "unit": unit,
                                    "status": "source_missing", "source_field": family})
                else:
                    found.append({"geo_id": state, "geo_type": "state", "field_id": offense_id,
                                  "offense": offense_slug, "year": "2025", "period": "2025-" + period[:2],
                                  "period_type": "monthly", "source_value": str(value), "unit": unit,
                                  "source_field": family, "source_release": "FBI CDE 2025",
                                  "status": "observed"})
    return found, missing


def collect_fbi(max_items: int, delay_seconds: float = 0.12) -> dict[str, Any]:
    checkpoint_path = RUNTIME / "state/fbi-checkpoint.json"
    checkpoint = {}
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checkpoint = {}
    done = set(checkpoint.get("completed", []))
    jobs = [(state, offense_id, slug) for state, _, _ in FBI_STATES
            for offense_id, (slug, _label) in FBI_OFFENSES.items()]
    new_jobs = 0
    attempts = 0
    artifacts = []
    values: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for state, offense_id, slug in jobs:
        job_id = f"{state}/{slug}"
        path = fbi_raw_path(state, slug)
        if job_id in done and path.exists():
            payload = path.read_bytes()
            values_part, missing_part = fbi_response_rows(payload, state, offense_id, slug)
            values.extend(values_part)
            missing.extend(missing_part)
            meta_path = path.with_suffix(".meta.json")
            prior_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            prior_meta.setdefault("license", "FBI public crime statistics; source citation retained.")
            if meta_path.exists():
                atomic_json(meta_path, prior_meta)
            artifacts.append({**prior_meta, "path": str(path), "sha256": sha256_file(path),
                              "bytes": path.stat().st_size, "sourceId": "fbi-cde-state",
                              "status": "reused_verified"})
            continue
        if attempts >= max_items:
            continue
        attempts += 1
        url = (f"https://cde.ucr.cjis.gov/LATEST/summarized/state/{state}/{slug}"
               f"?from=01-2025&to=12-2025&type=totals")
        meta_path = path.with_suffix(".meta.json")
        retrieved_at = utc_now()
        try:
            payload, status, headers = request_bytes(url, timeout=45)
            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data.get("offenses"), dict):
                raise ValueError("fbi_response_shape_invalid")
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, payload)
            artifact = {"sourceId": "fbi-cde-state", "url": url, "path": str(path),
                        "sha256": sha256_bytes(payload), "bytes": len(payload), "retrievedAt": retrieved_at,
                        "httpStatus": status, "contentType": headers.get("Content-Type"), "status": "downloaded",
                        "license": "FBI public crime statistics; source citation retained."}
            atomic_json(meta_path, artifact)
            artifacts.append(artifact)
            part_values, part_missing = fbi_response_rows(payload, state, offense_id, slug)
            values.extend(part_values)
            missing.extend(part_missing)
            new_jobs += 1
            done.add(job_id)
            atomic_json(checkpoint_path, {"format": "fbi_checkpoint_v1", "completed": sorted(done),
                                         "totalJobs": len(jobs), "updatedAt": utc_now()})
            if new_jobs % 25 == 0:
                print(f"FBI jobs {len(done)}/{len(jobs)}", flush=True)
            time.sleep(delay_seconds)
        except HTTPError as error:
            artifacts.append({"sourceId": "fbi-cde-state", "url": url, "attemptedAt": retrieved_at,
                              "httpStatus": error.code, "status": "blocked_http", "reason": f"http_{error.code}"})
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            artifacts.append({"sourceId": "fbi-cde-state", "url": url, "attemptedAt": retrieved_at,
                              "status": "unavailable", "reason": type(error).__name__})
    # Rebuild all completed jobs, not only newly requested jobs, so resume is stable.
    values = []
    missing = []
    artifact_by_path = {item.get("path"): item for item in artifacts}
    for state, offense_id, slug in jobs:
        path = fbi_raw_path(state, slug)
        if not path.exists():
            continue
        payload = path.read_bytes()
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        if meta.get("sha256") != sha256_bytes(payload):
            missing.append({"geo_id": state, "geo_type": "state", "field_id": offense_id,
                            "year": "2025", "status": "raw_hash_mismatch"})
            continue
        part_values, part_missing = fbi_response_rows(payload, state, offense_id, slug)
        values.extend(part_values)
        missing.extend(part_missing)
    write_csv(RUNTIME / "prepared/fbi-cde-2025-state-monthly.csv", values)
    write_jsonl(RUNTIME / "prepared/fbi-cde-2025-state-missingness.jsonl", missing)
    complete_series = {(row["geo_id"], row["field_id"], row["source_field"]) for row in values}
    return {
        "status": "complete" if len(done) == len(jobs) and not missing else "partial",
        "expectedJobs": len(jobs), "completedJobs": len(done), "newJobsThisRun": new_jobs,
        "attemptedJobsThisRun": attempts, "observedMonthlyRows": len(values), "missingnessRows": len(missing),
        "stateOffenseSeriesObserved": len(complete_series), "pendingJobs": len(jobs) - len(done),
        "rawArtifacts": artifacts,
        "outputs": [str(RUNTIME / "prepared/fbi-cde-2025-state-monthly.csv"),
                    str(RUNTIME / "prepared/fbi-cde-2025-state-missingness.jsonl")],
        "note": "Raw FBI source series are monthly. Annual totals/rates are not synthesized unless all 12 source months are observed and an explicit preparation rule is reviewed.",
    }


def artifact_summary() -> list[dict[str, Any]]:
    meta = load_source_meta()
    result = []
    for key, row in sorted(meta.get("artifacts", {}).items()):
        if row.get("status") == "downloaded" and row.get("path") and Path(row["path"]).exists():
            current_hash = sha256_file(Path(row["path"]))
            result.append({**row, "hashVerifiedAtInventory": current_hash == row.get("sha256")})
        else:
            result.append(row)
    return result


def write_runtime_matrix(results: dict[str, Any]) -> str:
    matrix = json.loads((PACKAGE / "definition_matrix.json").read_text(encoding="utf-8"))
    artifacts = artifact_summary()
    for source in results.get("fixedSources", {}).values():
        if isinstance(source, dict):
            artifacts.append(source)
    for source in results.get("freshnessPageSnapshots", {}).values():
        if isinstance(source, dict):
            artifacts.append(source)
    for name in ("eiaKeyedApi", "blsUnemployment", "fbiCrime"):
        result = results.get(name, {})
        if isinstance(result, dict):
            artifacts.extend(item for item in result.get("rawArtifacts", []) if isinstance(item, dict))
            if result.get("sourceId"):
                artifacts.append(result)
    fbi_annual_source = results.get("fbiAnnualComparison", {}).get("annualSource")
    if isinstance(fbi_annual_source, dict):
        artifacts.append(fbi_annual_source)
    for result in results.get("existingMedicalRates", {}).values():
        if isinstance(result, dict) and isinstance(result.get("sourceReceipt"), dict):
            artifacts.append(result["sourceReceipt"])
        if isinstance(result, dict) and isinstance(result.get("publisherRawReceipt"), dict):
            artifacts.append(result["publisherRawReceipt"])
    page_aliases = {
        "acs-release-schedule": "freshness-page-acs_release_schedule",
        "bls-laus-public-api-v2": "freshness-page-bls_laus_tables",
        "eia-retail-sales-api": "freshness-page-eia_annual",
        "places-current-release": "freshness-page-places_release",
        "bea-rpp-release": "freshness-page-bea_rpp",
        "irs-soi-county-2023": "irs-soi-county-2023",
        "uscs-release": "freshness-page-uscs_technical_notes",
        "hiv-release-page": "freshness-page-hiv_release",
        "wonder-mortality-release": "freshness-page-wonder_mortality",
        "fbi-2025-release": "freshness-page-fbi_2025_release",
        "eia-2025-release": "freshness-page-eia_annual",
        "census-pep-v2025-release": "freshness-page-census_pep_v2025",
        "fitness-recreation-centers-per-capita": "",
    }
    source_fallbacks = {"eia-retail-sales-api": ["eia-epa-2-10"],
                        "hiv-release-page": ["cdc-hiv-2024-tables"]}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        if artifact.get("sourceId"):
            by_source.setdefault(artifact["sourceId"], []).append(artifact)
    prepared_status = {
        "unemployment": results.get("blsUnemployment", {}).get("status"),
        "adjusted-gross-income-agi": results.get("irsIncome", {}).get("status"),
        "electricity-price": results.get("eia", {}).get("status"),
    }
    for selection, key in (("all-cancer-new-cases", "cancer2023"),
                           ("new-hiv-diagnoses", "hiv2024"),
                           ("deaths-under-18", "childDeaths2024")):
        prepared_status[selection] = results.get("existingMedicalRates", {}).get(key, {}).get("status")
    for row in matrix["rows"]:
        candidates = list(by_source.get(row.get("sourceId"), []))
        if row.get("sourceId") == "fbi-cde-state":
            candidates.extend(by_source.get("fbi-srs-estimated-crimes-1979-2025", []))
        for fallback in source_fallbacks.get(row.get("sourceId"), []):
            candidates.extend(by_source.get(fallback, []))
        alias = page_aliases.get(row.get("sourceId"))
        if alias:
            candidates.extend(by_source.get(alias, []))
        candidates = [item for item in candidates if item.get("retrievedAt")]
        if candidates:
            latest = max(candidates, key=lambda item: item["retrievedAt"])
            row["retrievedAt"] = latest["retrievedAt"]
            row["retrievalDate"] = latest["retrievedAt"][:10]
            row["retrievalKind"] = "official_page_snapshot" if str(latest.get("sourceId", "")).startswith("freshness-page-") else "data_artifact"
        support = []
        for support_id in row.get("supportingSources", []):
            support_candidates = [item for item in by_source.get(support_id, []) if item.get("retrievedAt")]
            if support_candidates:
                latest_support = max(support_candidates, key=lambda item: item["retrievedAt"])
                support.append({"sourceId": support_id, "retrievedAt": latest_support["retrievedAt"],
                                "retrievalDate": latest_support["retrievedAt"][:10]})
        row["supportingRetrievals"] = support
        status = prepared_status.get(row["selectionId"])
        if row.get("sourceId") in {"fbi-cde-state", "fbi-srs-estimated-crimes-1979-2025"} and "fbiCrime" in results:
            fbi_status = results.get("fbiAnnualComparison", {}).get("status")
            status = ("annual_source_prepared_local_review_only" if fbi_status == "complete"
                      else "monthly_source_kept_separate_annual_source_unavailable")
        if (row.get("sourceId") == "bls-laus-public-api-v2"
                and results.get("blsUnemployment", {}).get("status") == "collection_complete_with_source_gaps"):
            status = "collection_complete_with_source_gaps"
        if status == "annual_source_prepared_local_review_only":
            row["status"] = status
        elif status == "monthly_source_kept_separate_annual_source_unavailable":
            row["status"] = status
        elif status == "monthly_source_series_complete_annual_values_not_synthesized":
            row["status"] = status
        elif status == "collection_complete_with_source_gaps":
            row["status"] = status
        elif status in {"complete", "partial", "downloaded_unparsed", "blocked_input", "blocked_population_input"}:
            row["status"] = f"local_preparation_{status}"
        elif row["selectionId"] == "new-hiv-diagnoses":
            artifact = next((item for item in candidates if item.get("sourceId") == "cdc-hiv-2024-tables"), None)
            if artifact and artifact.get("status") in {"downloaded", "reused_verified"}:
                row["status"] = "source_file_downloaded_extraction_pending"
        elif row.get("status") == "freshness_reviewed_collection_pending":
            row["status"] = "freshness_reviewed_latest_suitable_release_retained"
    path = RUNTIME / "prepared/definition_matrix.json"
    atomic_json(path, matrix)
    return str(path)


def prepare_published_before_after() -> dict[str, Any]:
    """Compare frozen published API observations to locally prepared outputs by geography."""
    inventory_path = PUBLISHED_BEFORE_INVENTORY
    if not inventory_path.exists():
        return {"status": "published_before_inventory_missing"}
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("manifestUnchanged") is not True or len(inventory.get("observations", [])) < 42:
        return {"status": "published_before_inventory_not_verified"}
    inputs = {
        "02.10": ("02.10", "bea-rpp-state-2024.csv", "value", "2024", "2024"),
        "11.01:derived": ("11.01", "cancer-2023-rates.csv", "value", "2023", "2023"),
        "11.02:derived": ("11.02", "hiv-2024-rates.csv", "value", "2024", "2024"),
        "11.03:derived": ("11.03", "child-deaths-under18-2024-rates.csv", "value", "2024", "2024"),
        "07.01:derived:per-resident": ("07.01:derived:per-resident", "irs-agi-per-resident-2023.csv", "value", "2023", "2023"),
        "07.01:derived:total": ("07.01:derived:total", "irs-agi-2023-usd.csv", "value_usd", "2023", "2023"),
        "08.05:sector_ALL": ("08.05:sector_ALL", "eia-electricity-price-2025-all-sectors.csv", "value", "2025", "2024"),
    }
    reports = []
    for field_id, (file_stub, current_file, value_column, year, before_year) in inputs.items():
        before_path = next((Path(item["path"]) for item in inventory["observations"]
                            if json.loads(Path(item["path"]).read_text(encoding="utf-8")).get("fieldId") == field_id), None)
        current_path = RUNTIME / "prepared" / current_file
        if before_path is None:
            reports.append({"fieldId": field_id, "status": "baseline_or_prepared_file_missing"})
            continue
        before_entry = next(item for item in inventory["observations"] if Path(item["path"]) == before_path)
        if sha256_file(before_path) != before_entry.get("sha256"):
            raise ValueError("published_before_snapshot_hash_mismatch")
        before_data = json.loads(before_path.read_text(encoding="utf-8"))
        if before_data.get("fieldId") != field_id or str(before_data.get("period")) != before_year:
            raise ValueError("published_before_snapshot_identity_mismatch")
        before = {str(row.get("sourceGeoId") or row.get("id")): Decimal(str(row["value"]))
                  for row in before_data.get("observations", []) if row.get("value") is not None}
        retained_same_release = (field_id == "02.10" and not current_path.exists()
                                 and before_data.get("sourceRelease") == "BEA-SARPP-2024-release-2026-02-19")
        if not current_path.exists() and not retained_same_release:
            reports.append({"fieldId": field_id, "status": "baseline_or_prepared_file_missing"})
            continue
        after = (before.copy() if retained_same_release else
                 {(row.get("state") if field_id.startswith("08.05") else row.get("geo_id")): Decimal(row[value_column])
                  for row in read_csv(current_path)
                  if (row.get("state") if field_id.startswith("08.05") else row.get("geo_id"))
                  and row.get(value_column) not in {None, ""}})
        old_ranks = {geo: rank for rank, (geo, _v) in enumerate(sorted(before.items(), key=lambda p: (-p[1], p[0])), 1)}
        new_ranks = {geo: rank for rank, (geo, _v) in enumerate(sorted(after.items(), key=lambda p: (-p[1], p[0])), 1)}
        rows = []
        for geo in sorted(set(before) | set(after)):
            rows.append({"field_id": field_id, "geo_id": geo, "before_value": str(before[geo]) if geo in before else None,
                         "before_rank": old_ranks.get(geo), "after_value": str(after[geo]) if geo in after else None,
                         "after_rank": new_ranks.get(geo),
                         "change": str(after[geo] - before[geo]) if geo in before and geo in after else None,
                         "status": "both_values_available" if geo in before and geo in after else "value_missing_on_one_side"})
        out = RUNTIME / "prepared" / ("before-after-" + file_stub.replace(":", "-") + ".csv")
        write_csv(out, rows)
        missing_geographies = sorted(set(before) - set(after))
        report_status = ("freshness_verified_same_release" if retained_same_release else
                         "complete" if rows and not missing_geographies else "partial_with_source_missing_geographies")
        reports.append({"fieldId": field_id, "status": report_status,
                        "beforeRows": len(before), "afterRows": len(after), "comparisonRows": len(rows),
                        "missingAfterGeographies": missing_geographies,
                        "comparisonMode": "retained_snapshot_same_release" if retained_same_release else "source_before_vs_prepared_after",
                        "output": str(out), "beforeSnapshotSha256": sha256_file(before_path)})
    return {"status": "reviewed_with_declared_geography_gaps" if reports else "partial",
            "manifestRelease": inventory.get("release"), "manifestSourceCommit": inventory.get("sourceCommit"),
            "comparisonEvidenceOnly": True, "fields": reports}


def write_inventory(results: dict[str, Any]) -> None:
    from full.data_refresh_20261026.consolidate_inventory import row_count, validate_output_bindings, _walk_result_outputs
    INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    artifacts = artifact_summary()
    for name in ("eiaKeyedApi", "blsUnemployment", "fbiCrime"):
        result = results.get(name, {})
        if not isinstance(result, dict):
            continue
        if result.get("sourceId"):
            artifacts.append(result)
        artifacts.extend(item for item in result.get("rawArtifacts", []) if isinstance(item, dict))
    for source_group in (results.get("fixedSources", {}), results.get("freshnessPageSnapshots", {})):
        if isinstance(source_group, dict):
            artifacts.extend(item for item in source_group.values() if isinstance(item, dict))
    fbi_annual_source = results.get("fbiAnnualComparison", {}).get("annualSource")
    if isinstance(fbi_annual_source, dict):
        artifacts.append(fbi_annual_source)
    for result in results.get("existingMedicalRates", {}).values():
        if isinstance(result, dict) and isinstance(result.get("sourceReceipt"), dict):
            artifacts.append(result["sourceReceipt"])
        if isinstance(result, dict) and isinstance(result.get("publisherRawReceipt"), dict):
            artifacts.append(result["publisherRawReceipt"])
    unique_artifacts = {}
    for artifact in artifacts:
        identity = (artifact.get("sourceId"), artifact.get("path"), artifact.get("url"),
                    artifact.get("retrievedAt") or artifact.get("attemptedAt"))
        unique_artifacts[identity] = artifact
    packet = {
        "format": "usa_maps_local_data_refresh_inventory_v1",
        "collectorVersion": "2026.10.26.2",
        "readerContractVersion": "1.0.0",
        "sourceReleaseVersions": "Publisher releases are separate; see source_catalog.json and freshness_review.json.",
        "generatedAt": utc_now(),
        "worktree": str(ROOT),
        "runtimePath": str(RUNTIME),
        "admissionStatus": "not_admitted; no database access or writes performed",
        "sourceArtifacts": list(unique_artifacts.values()),
        "preparedArtifacts": [{"path": str(path), "bytes": path.stat().st_size,
                               "sha256": sha256_file(path), "rowCount": row_count(path),
                               "artifactType": "locally_prepared_or_imported"}
                              for path in sorted((RUNTIME / "prepared").glob("*")) if path.is_file()],
        "definitionMatrix": results.get("definitionMatrixPath"),
        "results": results,
        "ready": False,
        "readinessReason": "This is collection preparation. Any partial source, unresolved coverage, or pending denominator remains not ready for admission.",
    }
    artifact_by_path = {item["path"]: item for item in packet["preparedArtifacts"]}
    bindings = []
    for address, output_path, _parent, declared_hash in _walk_result_outputs(results):
        path = Path(output_path).resolve()
        artifact = artifact_by_path.get(str(path))
        if not artifact:
            raise ValueError("inventory_result_output_not_in_runtime_prepared_manifest")
        if declared_hash and declared_hash != artifact["sha256"]:
            raise ValueError("inventory_result_output_hash_mismatch")
        bindings.append({"resultField": address, "path": str(path), "sha256": artifact["sha256"],
                         "rowCount": artifact["rowCount"]})
    packet["resultOutputBindings"] = bindings
    validate_output_bindings(packet)
    atomic_json(INVENTORY, packet)


def run(max_bls_queries: int, max_fbi_items: int, include_page_snapshots: bool = True,
        runtime_dir: str | Path | None = None, inventory_path: str | Path | None = None,
        bls_prepared_dir: Path | None = None, bls_results_path: Path | None = None,
        fbi_annual_raw: Path | None = None, download_fbi_annual: bool = False) -> dict[str, Any]:
    global RUNTIME, INVENTORY
    if runtime_dir is not None:
        RUNTIME = Path(runtime_dir).expanduser().resolve()
    if inventory_path is not None:
        INVENTORY = Path(inventory_path).expanduser().resolve()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"preflight": json.loads((Path("/tmp/usa-maps-data-flow-20261026/preflight.json")).read_text())
                               if Path("/tmp/usa-maps-data-flow-20261026/preflight.json").exists() else None}
    results["fixedSources"] = download_fixed_sources()
    results["eiaKeyedApi"] = fetch_eia_api()
    if include_page_snapshots:
        results["freshnessPageSnapshots"] = download_freshness_pages()
    results["population"] = prepare_population()
    results["eia"] = prepare_eia()
    results["eiaBeforeAfter"] = prepare_eia_before_after()
    results["irsIncome"] = prepare_irs_income(results["population"])
    results["existingMedicalRates"] = prepare_existing_medical_rates()
    if bool(bls_prepared_dir) != bool(bls_results_path):
        raise ValueError("both_bls_import_paths_required")
    results["blsUnemployment"] = (import_completed_bls(bls_prepared_dir, bls_results_path)
                                  if bls_prepared_dir and bls_results_path else collect_bls(max_bls_queries))
    results["fbiCrime"] = collect_fbi(max_fbi_items)
    results["fbiAnnualComparison"] = prepare_fbi_baseline_and_annual(fbi_annual_raw, download_fbi_annual)
    results["publishedBeforeAfter"] = prepare_published_before_after()
    results["definitionMatrixPath"] = write_runtime_matrix(results)
    results["productionReady"] = False
    results["productionReadiness"] = "No admission or database access is part of this worker task. Review source completeness and unresolved blockers before any later admission work."
    write_inventory(results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-bls-queries", type=int, default=500,
                        help="Maximum new BLS API requests this run; keyed v2 requests use the injected BLS_API_KEY, no-key mode is capped at 20/day.")
    parser.add_argument("--max-fbi-items", type=int, default=357,
                        help="Maximum state/offense FBI CDE responses to collect in this run (0-357).")
    parser.add_argument("--skip-page-snapshots", action="store_true",
                        help="Skip small official freshness page downloads.")
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME,
                        help="Ignored local runtime directory for raw and prepared artifacts.")
    parser.add_argument("--inventory", type=Path, default=INVENTORY,
                        help="Output JSON inventory path.")
    parser.add_argument("--bls-prepared-dir", type=Path,
                        help="Import verified parent BLS prepared files; requires --bls-results and performs no BLS requests.")
    parser.add_argument("--bls-results", type=Path,
                        help="Parent BLS run result JSON matching --bls-prepared-dir.")
    parser.add_argument("--fbi-annual-raw", type=Path,
                        help="Import the verified official FBI annual workbook bytes; hash checked, no network request.")
    parser.add_argument("--download-fbi-annual", action="store_true",
                        help="Use the public FBI CDE signed locator in memory and download the official annual workbook; locator is never retained.")
    args = parser.parse_args()
    if args.max_bls_queries < 0 or args.max_bls_queries > 1000:
        parser.error("--max-bls-queries must be between 0 and 1000")
    if args.max_fbi_items < 0 or args.max_fbi_items > 357:
        parser.error("--max-fbi-items must be between 0 and 357")
    try:
        result = run(args.max_bls_queries, args.max_fbi_items, not args.skip_page_snapshots,
                     args.runtime_dir, args.inventory, args.bls_prepared_dir, args.bls_results,
                     args.fbi_annual_raw, args.download_fbi_annual)
        print(json.dumps({"status": "complete" if all(result[key].get("status") == "complete"
                                                       for key in ("population", "eia", "irsIncome",
                                                                   "blsUnemployment", "fbiCrime")) else "partial",
                          "inventory": str(args.inventory.expanduser().resolve()),
                          "sources": {key: value.get("status") if isinstance(value, dict) else None
                                      for key, value in result.items() if isinstance(value, dict)}},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as error:
        print(json.dumps({"status": "partial", "error": type(error).__name__},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
