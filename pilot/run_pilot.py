#!/usr/bin/env python3
"""Small, sequential, policy-compliant source probe for the USA Atlas catalog.

The default run makes one small request per source and never rotates IPs or
retries through proxies. Credentials are loaded from a mode-600 file outside
the project and are never written to pilot artifacts or diagnostic output.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
NORMALIZED = ROOT / "normalized"
USER_AGENT = "USA-Atlas-data-pilot/0.1"
CREDENTIALS_PATH = Path.home() / ".config" / "usa-atlas" / "credentials.env"
CREDENTIAL_NAMES = (
    "CENSUS_API_KEY",
    "EPA_AQS_EMAIL",
    "EPA_AQS_KEY",
    "EIA_API_KEY",
    "BLS_API_KEY",
    "SOCRATA_APP_TOKEN",
    "BEA_API_KEY",
)
CREDENTIALED_PROBES = (
    "census_acs",
    "epa_aqs",
    "eia",
    "bls_laus",
    "cdc_places",
    "bea_api",
)
SENSITIVE_FIELD_NAMES = {
    "key",
    "apikey",
    "userid",
    "email",
    "registrationkey",
    "apptoken",
    "xapptoken",
}
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
DROP = object()


class CredentialFileError(Exception):
    """A safe-to-display credential file configuration error."""


class ProbeError(Exception):
    """A provider response failed validation without exposing response content."""


def load_credentials(path: Path = CREDENTIALS_PATH) -> None:
    if not path.exists():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise CredentialFileError(f"credential file must have mode 600, found {mode:03o}")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise CredentialFileError(f"invalid credential file syntax on line {line_number}")
        name, value = stripped.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in CREDENTIAL_NAMES:
            raise CredentialFileError(f"unknown credential name on line {line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value and name not in os.environ:
            os.environ[name] = value


def is_sensitive_field(name: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(name).lower())
    return normalized in SENSITIVE_FIELD_NAMES


def redact_text(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    redacted = canonical_url(value) if parts.scheme in {"http", "https"} and parts.netloc else value
    for secret in (os.getenv(name, "") for name in CREDENTIAL_NAMES):
        if not secret:
            continue
        variants = {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}
        for variant in sorted(variants, key=len, reverse=True):
            if variant:
                redacted = redacted.replace(variant, "[REDACTED]")
    return EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)


def sanitize_data(value: object) -> object:
    if isinstance(value, dict):
        parameter_name = next(
            (item for key, item in value.items() if str(key).lower() == "parametername"),
            None,
        )
        if parameter_name is not None and is_sensitive_field(parameter_name):
            return DROP
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if is_sensitive_field(key):
                continue
            sanitized = sanitize_data(item)
            if sanitized is not DROP:
                cleaned[str(key)] = sanitized
        return cleaned
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            sanitized = sanitize_data(item)
            if sanitized is not DROP:
                cleaned_list.append(sanitized)
        return cleaned_list
    if isinstance(value, str):
        return redact_text(value)
    return value


def canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    public_query = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not is_sensitive_field(name)
    ]
    return urllib.parse.urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urllib.parse.urlencode(public_query, doseq=True),
        parts.fragment,
    ))


def request(url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, data=body, headers=merged)
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def save_raw(name: str, payload: bytes) -> None:
    (RAW / name).write_bytes(payload)


def save_raw_json(name: str, payload: bytes) -> None:
    sanitized = sanitize_data(json.loads(payload))
    (RAW / name).write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")


def record(metric_id: str, value: float, unit: str, geo_id: str, geo_type: str,
           year: str, source: str, source_url: str, note: str, rate: float | None = None) -> dict:
    return {
        "geo_id": geo_id,
        "geo_type": geo_type,
        "year": year,
        "metric_id": metric_id,
        "value": value,
        "rate": rate,
        "unit": unit,
        "source": source,
        "source_url": source_url,
        "methodology_note": note,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def probe_bls(samples: list[dict]) -> dict:
    key = os.getenv("BLS_API_KEY")
    if not key:
        return {"status": "credential_required", "credential": "BLS_API_KEY"}
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    payload = json.dumps({
        "seriesid": ["LASST060000000000003"],
        "startyear": "2024",
        "endyear": "2024",
        "registrationkey": key,
    }).encode()
    raw = request(url, body=payload, headers={"Content-Type": "application/json"})
    save_raw_json("bls-laus.json", raw)
    data = json.loads(raw)
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise ProbeError("provider_rejected_request")
    december = next(row for row in data["Results"]["series"][0]["data"] if row["period"] == "M12")
    samples.append(record(
        "unemployment_rate", float(december["value"]), "%", "06", "state", "2024-12",
        "bls_laus", url, "Seasonally adjusted state unemployment rate; December observation.",
        float(december["value"]),
    ))
    return {
        "status": "pass",
        "rows": len(data["Results"]["series"][0]["data"]),
        "credential": "project key",
    }


def probe_fbi(samples: list[dict]) -> dict:
    url = "https://cde.ucr.cjis.gov/LATEST/summarized/state/CA/violent-crime?from=01-2023&to=12-2023&type=totals"
    raw = request(url)
    save_raw("fbi-cde-violent-crime.json", raw)
    data = json.loads(raw)
    count = data["offenses"]["actuals"]["California Offenses"]["01-2023"]
    rate = data["offenses"]["rates"]["California Offenses"]["01-2023"]
    samples.append(record(
        "violent_crime", float(count), "count", "06", "state", "2023-01",
        "fbi_cde", url, "CDE summarized endpoint; reporting coverage metadata must accompany production data.",
        float(rate),
    ))
    return {"status": "pass", "months": 12}


def probe_places(samples: list[dict]) -> dict:
    token = os.getenv("SOCRATA_APP_TOKEN")
    if not token:
        return {"status": "credential_required", "credential": "SOCRATA_APP_TOKEN"}
    query = urllib.parse.urlencode({
        "$select": "year,locationid,locationname,measureid,measure,data_value_type,data_value,data_value_unit",
        "$where": 'locationid="06001" AND measureid in("OBESITY","DIABETES","LPA")',
        "$limit": "20",
    })
    url = f"https://data.cdc.gov/resource/swc5-untb.json?{query}"
    raw = request(url, headers={"X-App-Token": token})
    save_raw_json("cdc-places-alameda.json", raw)
    data = json.loads(raw)
    metric_map = {"OBESITY": "obesity_rate", "DIABETES": "diabetes_rate", "LPA": "physical_inactivity_rate"}
    for row in data:
        if row["data_value_type"] != "Age-adjusted prevalence":
            continue
        value = float(row["data_value"])
        samples.append(record(
            metric_map[row["measureid"]], value, "%", row["locationid"], "county", row["year"],
            "cdc_places", url, "Model-based age-adjusted county prevalence estimate.", value,
        ))
    return {"status": "pass", "rows": len(data), "credential": "project token"}


def probe_eia(samples: list[dict]) -> dict:
    key = os.getenv("EIA_API_KEY")
    if not key:
        return {"status": "credential_required", "credential": "EIA_API_KEY"}
    params = urllib.parse.urlencode([
        ("api_key", key),
        ("frequency", "annual"),
        ("data[0]", "price"),
        ("facets[stateid][]", "CA"),
        ("facets[sectorid][]", "RES"),
        ("start", "2023"),
        ("end", "2023"),
        ("length", "5"),
    ])
    url = f"https://api.eia.gov/v2/electricity/retail-sales/data/?{params}"
    raw = request(url)
    save_raw_json("eia-electricity-price.json", raw)
    row = json.loads(raw)["response"]["data"][0]
    samples.append(record(
        "residential_electricity_price", float(row["price"]), row["price-units"], "06", "state",
        row["period"], "eia", canonical_url(url), "Average residential retail electricity price.",
    ))
    return {"status": "pass", "rows": 1, "credential": "project key"}


def probe_bea_bulk(samples: list[dict]) -> dict:
    url = "https://apps.bea.gov/regional/zip/SARPP.zip"
    raw = request(url)
    save_raw("bea-sarpp.zip", raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        with archive.open("SARPP_STATE_2008_2024.csv") as handle:
            rows = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig"))
            row = next(r for r in rows if r["GeoFIPS"].strip(' \"') == "06000" and r["LineCode"] == "1")
    samples.append(record(
        "regional_price_parity", float(row["2024"]), "index_us_100", "06", "state", "2024",
        "bea_rpp", url, "All-items regional price parity; U.S. average equals 100.",
    ))
    return {"status": "pass", "archive_bytes": len(raw)}


def probe_bea_api(samples: list[dict]) -> dict:
    del samples
    key = os.getenv("BEA_API_KEY")
    if not key:
        return {"status": "credential_required", "credential": "BEA_API_KEY"}
    params = urllib.parse.urlencode({
        "UserID": key,
        "method": "GetDataSetList",
        "ResultFormat": "JSON",
    })
    raw = request(f"https://apps.bea.gov/api/data?{params}")
    data = json.loads(raw)
    results = data.get("BEAAPI", {}).get("Results", {})
    datasets = results.get("Dataset")
    if not isinstance(datasets, list) or not datasets:
        raise ProbeError("provider_rejected_request")
    # BEA echoes UserID in RequestParam, so the authenticated response is not persisted.
    return {"status": "pass", "datasets": len(datasets), "credential": "project key"}


def probe_census(samples: list[dict]) -> dict:
    key = os.getenv("CENSUS_API_KEY")
    if not key:
        return {"status": "credential_required", "credential": "CENSUS_API_KEY"}
    params = urllib.parse.urlencode({
        "get": "NAME,B01003_001E,B19013_001E,B25064_001E,B17001_002E",
        "for": "county:001",
        "in": "state:06",
        "key": key,
    })
    url = f"https://api.census.gov/data/2024/acs/acs5?{params}"
    raw = request(url)
    save_raw_json("census-acs-alameda.json", raw)
    table = json.loads(raw)
    header, row = table[0], table[1]
    values = dict(zip(header, row))
    for metric_id, field, unit in [
        ("population", "B01003_001E", "count"),
        ("median_household_income", "B19013_001E", "USD"),
        ("median_gross_rent", "B25064_001E", "USD"),
    ]:
        samples.append(record(
            metric_id,
            float(values[field]),
            unit,
            "06001",
            "county",
            "2024",
            "census_acs",
            canonical_url(url),
            "ACS 5-year estimate.",
        ))
    return {"status": "pass", "rows": 1}


def probe_epa(samples: list[dict]) -> dict:
    del samples
    email = os.getenv("EPA_AQS_EMAIL")
    key = os.getenv("EPA_AQS_KEY")
    if not email or not key:
        return {"status": "credential_required", "credentials": ["EPA_AQS_EMAIL", "EPA_AQS_KEY"]}
    auth = urllib.parse.urlencode({"email": email, "key": key})
    availability_raw = request(f"https://aqs.epa.gov/data/api/metaData/isAvailable?{auth}")
    availability = json.loads(availability_raw)
    availability_status = str(availability.get("Header", [{}])[0].get("status", "")).lower()
    if availability_status != "success" and "healthy" not in availability_status:
        raise ProbeError("provider_unavailable_or_rejected_request")
    save_raw_json("epa-availability.json", availability_raw)
    time.sleep(5)
    params = urllib.parse.urlencode({
        "email": email,
        "key": key,
        "param": "88101",
        "bdate": "20230101",
        "edate": "20230107",
        "state": "06",
        "county": "001",
    })
    url = f"https://aqs.epa.gov/data/api/dailyData/byCounty?{params}"
    raw = request(url)
    save_raw_json("epa-pm25-alameda.json", raw)
    data = json.loads(raw)
    status = str(data.get("Header", [{}])[0].get("status", "")).lower()
    if status != "success":
        raise ProbeError("provider_rejected_request")
    return {"status": "pass", "availability": "pass", "rows": len(data.get("Data", []))}


def failure_result(error: Exception) -> dict:
    if isinstance(error, urllib.error.HTTPError):
        return {"status": "http_error", "http_status": error.code}
    if isinstance(error, urllib.error.URLError):
        return {"status": "network_error", "error_type": type(error.reason).__name__}
    return {"status": "error", "error_type": type(error).__name__}


def credentialed_probes_pass(results: dict[str, dict]) -> bool:
    return all(results.get(name, {}).get("status") == "pass" for name in CREDENTIALED_PROBES)


def main() -> int:
    try:
        load_credentials()
    except CredentialFileError as error:
        print(json.dumps({"status": "credential_file_error", "reason": str(error)}, indent=2))
        return 1
    RAW.mkdir(parents=True, exist_ok=True)
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    samples: list[dict] = []
    results: dict[str, dict] = {}
    probes = [
        ("census_acs", probe_census),
        ("bls_laus", probe_bls),
        ("fbi_cde", probe_fbi),
        ("cdc_places", probe_places),
        ("eia", probe_eia),
        ("bea_rpp_bulk", probe_bea_bulk),
        ("bea_api", probe_bea_api),
        ("epa_aqs", probe_epa),
    ]
    for name, probe in probes:
        try:
            results[name] = probe(samples)
        except Exception as error:  # Pilot records source-specific failures and continues.
            results[name] = failure_result(error)

    results.update({
        "cdc_wonder": {"status": "manual_probe_pass", "constraint": "NVSS API supports national results only; one robot query about every two minutes."},
        "hud_pit": {"status": "blocked", "constraint": "Direct XLSB request returned an AWS WAF challenge; use approved interactive or alternate bulk-download path."},
        "bls_oews": {"status": "blocked", "constraint": "Akamai returned 403 to automated ZIP/TXT download from this environment."},
        "irs_soi": {"status": "manual_probe_pass", "sample": "2022 Delaware XLSX parsed successfully."},
        "usda_food_environment_atlas": {"status": "manual_probe_pass", "sample": "2025 CSV archive parsed for Alameda County."},
        "forbes_billionaires": {"status": "not_authorized", "constraint": "Forbes terms prohibit automated scraping/collection; license or replacement source required."},
        "retail_menu": {"status": "source_unselected"},
        "gasoline_price": {"status": "metric_and_source_unselected"},
        "consumer_debt": {"status": "metric_and_source_unselected"},
        "health_insurance_cost": {"status": "metric_and_source_unselected"},
        "nchs_life_expectancy": {"status": "dataset_unselected"},
    })

    (NORMALIZED / "pilot-samples.json").write_text(json.dumps(samples, indent=2) + "\n", encoding="utf-8")
    (ROOT / "probe-results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"probe_results": results, "normalized_records": len(samples)}, indent=2))
    accepted_statuses = {
        "pass", "credential_required", "manual_probe_pass", "blocked",
        "not_authorized", "source_unselected", "metric_and_source_unselected",
        "dataset_unselected",
    }
    statuses_are_known = all(value["status"] in accepted_statuses for value in results.values())
    return 0 if statuses_are_known and credentialed_probes_pass(results) else 1


if __name__ == "__main__":
    sys.exit(main())
