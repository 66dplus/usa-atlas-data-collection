#!/usr/bin/env python3
"""Bounded local collector and per-field Eval for the 81-row USA Atlas catalog."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "pilot"
sys.path.insert(0, str(PILOT))
import run_pilot as safety  # noqa: E402


CONTRACT_PATH = HERE / "field-contract.json"
CONFIG_PATH = HERE / "adapter-config.json"
RAW = HERE / "raw"
NORMALIZED = HERE / "normalized"
STATE = HERE / "state"
CALIBRATION_PATH = STATE / "calibration-report.json"
MANIFEST_PATH = STATE / "run-manifest.json"
STATUS_PATH = STATE / "status.json"
EVAL_PATH = HERE / "FIELD-EVAL.json"
PLAN_SHA256 = "8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781"
USER_AGENT = "USA-Atlas-full-collector/0.1"
SENSITIVE_NAMES = safety.CREDENTIAL_NAMES
NORMALIZATION_TIMESTAMP: str | None = None
STATE_FIPS = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15",
    "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27",
    "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
    "40", "41", "42", "44", "45", "46", "47", "48", "49", "50", "51", "53",
    "54", "55", "56", "72",
]
STATE_ABBR = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY", "PR",
]
BLS_LAUS_MEASURES = {
    "03": "unemployment_rate",
    "04": "unemployment",
    "05": "employment",
    "06": "labor_force",
}
BLS_LAUS_VARIABLE_TEMPLATES = [
    *[f"LASST{{state_fips_2}}{'0' * 11}{measure}" for measure in BLS_LAUS_MEASURES],
    *[f"LAUCN{{county_fips_5}}{'0' * 8}{measure}" for measure in BLS_LAUS_MEASURES],
]


class CollectionError(Exception):
    pass


class StopSource(CollectionError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def hash_sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def binding_sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".binding.json")


def current_bindings() -> dict[str, str]:
    return {
        "plan_sha256": PLAN_SHA256,
        "contract_sha256": sha256(CONTRACT_PATH.read_bytes()),
        "config_sha256": sha256(CONFIG_PATH.read_bytes()),
        "collector_sha256": collector_sha256(),
    }


def record_artifact_hash(path: Path, digest: str | None = None,
                         *, bindings: dict[str, str] | None = None) -> str:
    """Bind a cached raw artifact to bytes recorded when the write completed."""
    actual = digest or sha256(path.read_bytes())
    atomic_write(hash_sidecar(path), (actual + "\n").encode())
    write_json(binding_sidecar(path), {"payload_sha256": actual, **(bindings or current_bindings())})
    return actual


def verified_file_artifact(path: Path) -> dict | None:
    """Return metadata only when an existing cache entry matches its saved hash."""
    if not path.exists():
        return None
    sidecar = hash_sidecar(path)
    if not sidecar.exists():
        raise StopSource("cache_hash_record_missing")
    expected = sidecar.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise StopSource("cache_hash_record_invalid")
    payload = path.read_bytes()
    actual = sha256(payload)
    if actual != expected:
        raise StopSource("cache_hash_mismatch")
    binding_path = binding_sidecar(path)
    if not binding_path.exists():
        raise StopSource("cache_binding_missing")
    binding = load_json(binding_path)
    if binding.get("payload_sha256") != actual:
        raise StopSource("cache_binding_payload_mismatch")
    if any(binding.get(key) != value for key, value in current_bindings().items()):
        raise StopSource("cache_binding_mismatch")
    return {"path": str(path.relative_to(HERE)), "sha256": actual, "bytes": len(payload), "cache_hit": True}


def collector_sha256() -> str:
    return sha256(Path(__file__).resolve().read_bytes())


def safe_reason(error: Exception) -> str:
    if isinstance(error, CollectionError):
        return str(error)
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    if isinstance(error, urllib.error.URLError):
        return f"network_{type(error.reason).__name__}"
    return type(error).__name__


class Session:
    def __init__(self, profile: str, *, calibration: bool):
        config = load_json(CONFIG_PATH)["profiles"][profile]
        self.profile = profile
        self.config = config
        self.calibration = calibration
        self.requests = 0
        self.response_bytes = 0
        self.retries = 0
        self.http_429 = 0
        self.cache_hits = 0
        self.started = time.monotonic()
        self.last_request_at = 0.0

    def request(self, url: str, *, body: bytes | None = None,
                headers: dict[str, str] | None = None, max_bytes: int | None = None) -> bytes:
        maximum = max_bytes or int(self.config["max_response_bytes"])
        attempts = int(self.config["max_attempts"])
        pause = 5.0 if self.profile in {"eia", "epa_airdata"} else (
            1.0 if self.profile in {"census_acs", "fbi_cde"} else (0.25 if self.profile == "bls_laus" else 0.0)
        )
        for attempt in range(attempts):
            remaining = pause - (time.monotonic() - self.last_request_at)
            if remaining > 0:
                time.sleep(remaining)
            request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
            req = urllib.request.Request(url, data=body, headers=request_headers)
            self.requests += 1
            try:
                with urllib.request.urlopen(req, timeout=90) as response:
                    self.last_request_at = time.monotonic()
                    original = urllib.parse.urlsplit(url)
                    final = urllib.parse.urlsplit(response.geturl())
                    if final.hostname != original.hostname:
                        raise StopSource("redirect_official_host")
                    payload = response.read(maximum + 1)
                    if len(payload) > maximum:
                        raise StopSource("max_response_bytes")
                    self.response_bytes += len(payload)
                    return payload
            except urllib.error.HTTPError as error:
                self.last_request_at = time.monotonic()
                if error.code == 429:
                    self.http_429 += 1
                    raise StopSource("http_429") from None
                if error.code not in self.config["retryable_statuses"] or attempt + 1 == attempts:
                    raise
                self.retries += 1
                time.sleep(min(2 ** attempt, 5))
        raise AssertionError("unreachable")

    def download(self, url: str, path: Path, *, max_bytes: int) -> dict:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        pause = 5.0 if self.profile in {"eia", "epa_airdata"} else 0.0
        remaining = pause - (time.monotonic() - self.last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        self.requests += 1
        digest = hashlib.sha256()
        size = 0
        try:
            with urllib.request.urlopen(req, timeout=180) as response, temporary.open("wb") as handle:
                self.last_request_at = time.monotonic()
                if urllib.parse.urlsplit(response.geturl()).hostname != urllib.parse.urlsplit(url).hostname:
                    raise StopSource("redirect_official_host")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise StopSource("max_response_bytes")
                    digest.update(chunk)
                    handle.write(chunk)
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        self.response_bytes += size
        recorded = record_artifact_hash(path, digest.hexdigest())
        return {"path": str(path.relative_to(HERE)), "sha256": recorded, "bytes": size}

    def metrics(self) -> dict:
        return {
            "request_count": self.requests,
            "response_bytes": self.response_bytes,
            "retry_count": self.retries,
            "http_429_count": self.http_429,
            "cache_hit_count": self.cache_hits,
            "duration_seconds": round(time.monotonic() - self.started, 3),
        }


def save_payload(source: str, name: str, payload: bytes, *, json_payload: bool = False) -> dict:
    directory = RAW / ("calibration" if name.startswith("cal-") else "full") / source
    path = directory / name
    if json_payload:
        cleaned = safety.sanitize_data(json.loads(payload))
        payload = (json.dumps(cleaned, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    if source == "census_acs" and not name.startswith("cal-"):
        payload = gzip.compress(payload, compresslevel=6, mtime=0)
        path = path.with_suffix(path.suffix + ".gz")
    atomic_write(path, payload)
    digest = record_artifact_hash(path)
    return {"path": str(path.relative_to(HERE)), "sha256": digest, "bytes": len(payload)}


def cached_payload(source: str, name: str) -> tuple[bytes, dict] | None:
    base = RAW / "full" / source / name
    path = base.with_suffix(base.suffix + ".gz") if source == "census_acs" else base
    artifact = verified_file_artifact(path)
    if artifact is None:
        return None
    stored = path.read_bytes()
    payload = gzip.decompress(stored) if path.suffix == ".gz" else stored
    return payload, artifact


def request_cached(session: Session, source: str, name: str, url: str, *, body: bytes | None = None,
                   headers: dict[str, str] | None = None, max_bytes: int | None = None) -> tuple[bytes, dict]:
    cached = cached_payload(source, name)
    if cached is not None:
        session.cache_hits += 1
        return cached
    payload = session.request(url, body=body, headers=headers, max_bytes=max_bytes)
    artifact = save_payload(source, name, payload, json_payload=True)
    return payload, artifact


def append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        with path.open("ab") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed, \
                io.TextIOWrapper(compressed, encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
    else:
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")


def source_output(source: str) -> Path:
    suffix = ".jsonl.gz" if source == "census_acs" else ".jsonl"
    return NORMALIZED / f"{source}{suffix}"


def normalized(field_id: str, geo_id: str, geo_type: str, year: str, value: object,
               unit: str, source: str, source_release: str, source_url: str,
               *, catalog_field_id: str | None = None, note: str = "") -> dict:
    return {
        "geo_id": str(geo_id), "geo_type": geo_type, "year": str(year),
        "field_id": field_id, "catalog_field_id": catalog_field_id or field_id,
        "value": value, "unit": unit, "source": source,
        "source_release": source_release, "source_url": safety.canonical_url(source_url),
        "methodology_note": note, "retrieved_at": NORMALIZATION_TIMESTAMP or now(),
    }


def calibrate_census(session: Session) -> tuple[list[dict], list[dict]]:
    key = os.environ["CENSUS_API_KEY"]
    query = urllib.parse.urlencode({
        "get": "NAME,B01003_001E,B01003_001M", "for": "county:*", "in": "state:06", "key": key,
    })
    url = f"https://api.census.gov/data/2024/acs/acs5?{query}"
    payload = session.request(url)
    artifact = save_payload("census_acs", "cal-ca-counties.json", payload, json_payload=True)
    table = json.loads(payload)
    header = table[0]
    records = []
    for row in table[1:]:
        item = dict(zip(header, row))
        records.append(normalized("01.01", item["state"] + item["county"], "county", "2024",
                                  float(item["B01003_001E"]), "count", "census_acs",
                                  "2024-acs-acs5", url, note="ACS 5-year estimate"))
    return records, [artifact]


def calibrate_bls(session: Session) -> tuple[list[dict], list[dict]]:
    body = json.dumps({
        "seriesid": ["LASST060000000000003"], "startyear": "2024", "endyear": "2024",
        "registrationkey": os.environ["BLS_API_KEY"],
    }).encode()
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    payload = session.request(url, body=body, headers={"Content-Type": "application/json"})
    artifact = save_payload("bls_laus", "cal-ca.json", payload, json_payload=True)
    data = json.loads(payload)
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise StopSource("provider_rejected_request")
    rows = data["Results"]["series"][0]["data"]
    records = [normalized("03.06", "06", "state", f"{row['year']}-{row['period']}",
                          float(row["value"]), "%", "bls_laus", "BLS-LAUS-2024", url)
               for row in rows if row["period"].startswith("M")]
    return records, [artifact]


def calibrate_fbi(session: Session) -> tuple[list[dict], list[dict]]:
    records, artifacts = [], []
    for state in ("CA", "NY", "TX"):
        url = f"https://cde.ucr.cjis.gov/LATEST/summarized/state/{state}/violent-crime?from=01-2023&to=12-2023&type=totals"
        payload = session.request(url)
        artifacts.append(save_payload("fbi_cde", f"cal-{state.lower()}.json", payload, json_payload=True))
        data = json.loads(payload)
        actuals = data["offenses"]["actuals"][f"{data['tooltips']['leftYAxisHeaders']['actual']} Offenses"] if False else data["offenses"]["actuals"]
        state_key = next(key for key in actuals if key.endswith("Offenses"))
        values = actuals[state_key]
        records.append(normalized("04.02", state, "state", "2023",
                                  sum(float(value) for value in values.values()), "count",
                                  "fbi_cde", "FBI-CDE-2023", url,
                                  note="Summed monthly actuals; retain reporting coverage in full run"))
    return records, artifacts


def calibrate_places(session: Session) -> tuple[list[dict], list[dict]]:
    artifacts = []
    metadata_url = "https://api.us.socrata.com/api/catalog/v1?ids=swc5-untb"
    metadata = session.request(metadata_url)
    artifacts.append(save_payload("cdc_places", "cal-metadata.json", metadata, json_payload=True))
    query = urllib.parse.urlencode({
        "$select": "year,locationid,measureid,data_value_type,data_value,data_value_unit,low_confidence_limit,high_confidence_limit",
        "$where": 'locationid="06001" AND measureid in("OBESITY","DIABETES","LPA")', "$limit": "50",
    })
    url = f"https://data.cdc.gov/resource/swc5-untb.json?{query}"
    payload = session.request(url, headers={"X-App-Token": os.environ["SOCRATA_APP_TOKEN"]})
    artifacts.append(save_payload("cdc_places", "cal-alameda.json", payload, json_payload=True))
    field_map = {"OBESITY": "05.14", "DIABETES": "05.15", "LPA": "05.16"}
    records = []
    for row in json.loads(payload):
        if row.get("data_value_type") != "Age-adjusted prevalence":
            continue
        records.append(normalized(field_map[row["measureid"]], row["locationid"], "county", row["year"],
                                  float(row["data_value"]), row.get("data_value_unit", "%"),
                                  "cdc_places", "CDC-PLACES-current", url))
    return records, artifacts


def calibrate_bea(session: Session) -> tuple[list[dict], list[dict]]:
    url = "https://apps.bea.gov/regional/zip/SARPP.zip"
    payload = session.request(url)
    artifact = save_payload("bea_rpp", "cal-SARPP.zip", payload)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        state_name = next(name for name in archive.namelist() if "STATE" in name and name.endswith(".csv"))
        rows = csv.DictReader(io.TextIOWrapper(archive.open(state_name), encoding="utf-8-sig"))
        row = next(item for item in rows if item["GeoFIPS"].strip(' \"') == "06000" and item["LineCode"] == "1")
        year = max(key for key in row if key.isdigit())
    record = normalized("02.10", "06", "state", year, float(row[year]), "index_us_100",
                        "bea_rpp", f"BEA-SARPP-{year}", url)
    return [record], [artifact]


def calibrate_irs(session: Session) -> tuple[list[dict], list[dict]]:
    url = "https://www.irs.gov/pub/irs-soi/22zpallagi.csv"
    payload = session.request(url)
    artifact = save_payload("irs_soi", "cal-22zpallagi.csv", payload)
    rows = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    row = next(item for item in rows if item.get("STATE", "").upper() == "CA" and item.get("zipcode") not in {"00000", None})
    zip_code = row["zipcode"].zfill(5)
    records = [
        normalized("07.01", zip_code, "zip", "2022", float(row["A00100"]), "thousand_USD", "irs_soi", "IRS-SOI-ZIP-2022", url),
        normalized("07.03", zip_code, "zip", "2022", float(row["A01000"]), "thousand_USD", "irs_soi", "IRS-SOI-ZIP-2022", url),
        normalized("07.04", zip_code, "zip", "2022", float(row["A00600"]), "thousand_USD", "irs_soi", "IRS-SOI-ZIP-2022", url),
    ]
    return records, [artifact]


def calibrate_usda(session: Session) -> tuple[list[dict], list[dict]]:
    url = "https://www.ers.usda.gov/media/5570/food-environment-atlas-csv-files.zip?v=99629"
    payload = session.request(url)
    artifact = save_payload("usda_fea", "cal-fea-2025.zip", payload)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        rows = csv.DictReader(io.TextIOWrapper(archive.open("StateAndCountyData.csv"), encoding="utf-8-sig"))
        wanted = {"FFRPTH20": "09.01", "LACCESS_POP19": "09.02", "FMRKTPTH18": "09.03", "RECFACPTH20": "09.04"}
        values = {row["Variable_Code"]: row for row in rows if row["FIPS"] == "06001" and row["Variable_Code"] in wanted}
    records = [normalized(field_id, "06001", "county", re.search(r"(\d\d)$", code).group(1),
                          float(values[code]["Value"]), "source_defined", "usda_fea", "USDA-FEA-2025", url)
               for code, field_id in wanted.items()]
    return records, [artifact]


def calibrate_eia(session: Session) -> tuple[list[dict], list[dict]]:
    params = urllib.parse.urlencode([
        ("api_key", os.environ["EIA_API_KEY"]), ("frequency", "annual"), ("data[0]", "price"),
        ("facets[sectorid][]", "RES"), ("start", "2024"), ("end", "2024"),
        ("offset", "0"), ("length", "5000"),
    ])
    url = f"https://api.eia.gov/v2/electricity/retail-sales/data/?{params}"
    payload = session.request(url)
    artifact = save_payload("eia", "cal-residential-states.json", payload, json_payload=True)
    rows = json.loads(payload)["response"]["data"]
    records = [normalized("08.05", row.get("stateid", row.get("stateDescription", "unknown")), "state",
                          row["period"], float(row["price"]), row["price-units"], "eia",
                          "EIA-electricity-retail-sales-2024", url) for row in rows]
    return records, [artifact]


def calibrate_epa(session: Session) -> tuple[list[dict], list[dict]]:
    auth = urllib.parse.urlencode({"email": os.environ["EPA_AQS_EMAIL"], "key": os.environ["EPA_AQS_KEY"]})
    availability_url = f"https://aqs.epa.gov/data/api/metaData/isAvailable?{auth}"
    availability = session.request(availability_url)
    artifacts = [save_payload("epa_airdata", "cal-availability.json", availability, json_payload=True)]
    params = urllib.parse.urlencode({
        "email": os.environ["EPA_AQS_EMAIL"], "key": os.environ["EPA_AQS_KEY"], "param": "88101",
        "bdate": "20230101", "edate": "20230107", "state": "06", "county": "001",
    })
    url = f"https://aqs.epa.gov/data/api/dailyData/byCounty?{params}"
    payload = session.request(url)
    artifacts.append(save_payload("epa_airdata", "cal-pm25-alameda.json", payload, json_payload=True))
    data = json.loads(payload)
    if str(data.get("Header", [{}])[0].get("status", "")).lower() != "success":
        raise StopSource("provider_rejected_request")
    records = []
    for row in data.get("Data", [])[:1000]:
        records.append(normalized("09.06", f"{row.get('state_code','06')}{row.get('county_code','001')}",
                                  "county", row.get("date_local", "2023")[:4], row.get("arithmetic_mean"),
                                  row.get("units_of_measure", "source_defined"), "epa_aqs",
                                  "EPA-AQS-2023", url))
    return records, artifacts


CALIBRATORS: dict[str, Callable[[Session], tuple[list[dict], list[dict]]]] = {
    "census_acs": calibrate_census, "bls_laus": calibrate_bls, "fbi_cde": calibrate_fbi,
    "cdc_places": calibrate_places, "bea_rpp": calibrate_bea, "irs_soi": calibrate_irs,
    "usda_fea": calibrate_usda, "eia": calibrate_eia, "epa_airdata": calibrate_epa,
}


def calibration_raw_row_count(source: str, artifacts: list[dict]) -> int:
    """Count provider rows in saved calibration payloads, before normalization filters."""
    payloads = []
    for item in artifacts:
        path = HERE / item["path"]
        verified = verified_file_artifact(path)
        if verified is None or verified["sha256"] != item["sha256"]:
            raise StopSource("calibration_artifact_binding_mismatch")
        payloads.append(path.read_bytes())
    if source == "census_acs":
        return max(0, len(json.loads(payloads[0])) - 1)
    if source == "bls_laus":
        data = json.loads(payloads[0])
        return sum(len(series.get("data", [])) for series in data.get("Results", {}).get("series", []))
    if source == "fbi_cde":
        total = 0
        for payload in payloads:
            actuals = json.loads(payload).get("offenses", {}).get("actuals", {})
            total += sum(len(values) for key, values in actuals.items() if key.endswith("Offenses"))
        return total
    if source == "cdc_places":
        return len(json.loads(payloads[-1]))
    if source == "bea_rpp":
        with zipfile.ZipFile(io.BytesIO(payloads[0])) as archive:
            name = next(name for name in archive.namelist() if name.startswith("SARPP_STATE_") and name.endswith(".csv"))
            return sum(1 for _ in csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8-sig")))
    if source == "irs_soi":
        return sum(1 for _ in csv.DictReader(io.StringIO(payloads[0].decode("utf-8-sig"))))
    if source == "usda_fea":
        with zipfile.ZipFile(io.BytesIO(payloads[0])) as archive:
            return sum(1 for _ in csv.DictReader(io.TextIOWrapper(
                archive.open("StateAndCountyData.csv"), encoding="utf-8-sig")))
    if source == "eia":
        return len(json.loads(payloads[0]).get("response", {}).get("data", []))
    if source == "epa_airdata":
        return len(json.loads(payloads[-1]).get("Data", []))
    raise ValueError(f"unknown calibration source: {source}")


def refresh_calibration_evidence() -> dict:
    """Recount saved calibration payloads without repeating provider requests."""
    report = load_json(CALIBRATION_PATH)
    if any(report.get(key) != value for key, value in current_bindings().items()):
        raise StopSource("calibration_binding_mismatch")
    for source, item in report["sources"].items():
        if item.get("status") == "pass":
            item["raw_rows"] = calibration_raw_row_count(source, item["artifacts"])
    report["evidence_refreshed_at"] = now()
    write_json(CALIBRATION_PATH, report)
    return report


def validate_calibration_artifacts(report: dict) -> int:
    """Fail closed unless every declared calibration payload is bound and unchanged."""
    checked = 0
    for item in report.get("sources", {}).values():
        for artifact in item.get("artifacts", []):
            verified = verified_file_artifact(HERE / artifact["path"])
            if verified is None or verified["sha256"] != artifact["sha256"]:
                raise StopSource("calibration_artifact_binding_mismatch")
            checked += 1
    return checked


def validate_contract() -> dict:
    contract = load_json(CONTRACT_PATH)
    config = load_json(CONFIG_PATH)
    required = {
        "field_id", "catalog_label", "planned_state", "source_release", "acquisition_mode",
        "source_selector", "source_variables", "derivation", "target_geographies",
        "unavailable_geography", "unit", "rate_limit_profile", "license_status",
    }
    errors = []
    if len(contract) != 81 or len({row["field_id"] for row in contract}) != 81:
        errors.append("contract must have 81 unique field IDs")
    expected_sections = Counter({str(number).zfill(2): count for number, count in enumerate([8, 10, 9, 9, 16, 6, 7, 9, 7], 1)})
    actual_sections = Counter(row["field_id"].split(".")[0] for row in contract)
    if actual_sections != expected_sections:
        errors.append("section counts do not match 8/10/9/9/16/6/7/9/7")
    for row in contract:
        missing = sorted(required - set(row))
        if missing:
            errors.append(f"{row.get('field_id', '?')}: missing {','.join(missing)}")
        if row.get("planned_state") == "run_now":
            if not row.get("source_selector") or not row.get("source_variables") or not row.get("target_geographies"):
                errors.append(f"{row['field_id']}: incomplete executable mapping")
            if row.get("rate_limit_profile") not in config["profiles"]:
                errors.append(f"{row['field_id']}: unknown rate profile")
            if row.get("rate_limit_profile") == "census_acs" and any(
                    not re.fullmatch(r"[A-Z]\d+_\d{3}[EM]", value)
                    for value in row.get("source_variables", [])):
                errors.append(f"{row['field_id']}: Census variables must be concrete E/M IDs")
            if (row.get("rate_limit_profile") == "bls_laus"
                    and row.get("source_variables") != BLS_LAUS_VARIABLE_TEMPLATES):
                errors.append(f"{row['field_id']}: BLS variables must be exact state/county LAUS templates 03-06")
    expected = {"run_now": 46, "blocked_access": 19, "definition_required": 7, "source_required": 6, "license_required": 3}
    states = Counter(row["planned_state"] for row in contract)
    if states != Counter(expected):
        errors.append(f"planned-state totals differ: {dict(states)}")
    return {"status": "pass" if not errors else "fail", "rows": len(contract), "state_totals": dict(states), "errors": errors}


def run_calibration() -> int:
    safety.load_credentials()
    RAW.mkdir(parents=True, exist_ok=True)
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    output_path = NORMALIZED / "calibration.jsonl"
    if output_path.exists():
        output_path.unlink()
    report = {"started_at": now(), **current_bindings(), "sources": {}}
    for source, calibrator in CALIBRATORS.items():
        session = Session(source, calibration=True)
        started = now()
        try:
            records, artifacts = calibrator(session)
            if not records:
                raise StopSource("zero_normalized_rows")
            append_jsonl(output_path, records)
            result = {"status": "pass", "started_at": started, "finished_at": now(),
                      "raw_rows": calibration_raw_row_count(source, artifacts),
                      "normalized_rows": len(records), "artifacts": artifacts,
                      **session.metrics()}
        except Exception as error:
            result = {"status": "fail", "started_at": started, "finished_at": now(),
                      "reason": safe_reason(error), "raw_rows": 0, "normalized_rows": 0,
                      "artifacts": [], **session.metrics()}
        report["sources"][source] = result
        report["updated_at"] = now()
        write_json(CALIBRATION_PATH, report)
        print(json.dumps({"source": source, "status": result["status"], "metrics": session.metrics()}), flush=True)
    report["finished_at"] = now()
    report["status"] = "pass" if all(item["status"] == "pass" for item in report["sources"].values()) else "partial"
    write_json(CALIBRATION_PATH, report)
    return 0 if report["status"] == "pass" else 2


def copy_calibration_to_full(source: str) -> tuple[int, list[dict]]:
    report = load_json(CALIBRATION_PATH)
    item = report["sources"][source]
    if item["status"] != "pass":
        raise StopSource("calibration_not_passed")
    artifacts = item["artifacts"]
    return item["normalized_rows"], artifacts


def full_places(session: Session) -> tuple[int, list[dict]]:
    query = urllib.parse.urlencode({
        "$select": "year,locationid,measureid,data_value_type,data_value,data_value_unit,low_confidence_limit,high_confidence_limit",
        "$where": 'measureid in("OBESITY","DIABETES","LPA") AND data_value_type="Age-adjusted prevalence"',
        "$order": "locationid,measureid,year", "$limit": "50000", "$offset": "0",
    })
    url = f"https://data.cdc.gov/resource/swc5-untb.json?{query}"
    payload, artifact = request_cached(session, "cdc_places", "places-counties.json", url,
                                       headers={"X-App-Token": os.environ["SOCRATA_APP_TOKEN"]},
                                       max_bytes=100 * 1024 * 1024)
    rows = json.loads(payload)
    field_map = {"OBESITY": "05.14", "DIABETES": "05.15", "LPA": "05.16"}
    records = [normalized(field_map[row["measureid"]], row["locationid"], "county", row["year"],
                          float(row["data_value"]), row.get("data_value_unit", "%"), "cdc_places",
                          "CDC-PLACES-current", url) for row in rows if row.get("data_value") not in {None, ""}]
    append_jsonl(source_output("cdc_places"), records)
    return len(records), [artifact]


def _calibration_artifact(source: str, suffix: str) -> bytes:
    report = load_json(CALIBRATION_PATH)
    artifact = next(item for item in report["sources"][source]["artifacts"] if item["path"].endswith(suffix))
    path = HERE / artifact["path"]
    verified = verified_file_artifact(path)
    if verified is None or verified["sha256"] != artifact["sha256"]:
        raise StopSource("calibration_artifact_binding_mismatch")
    payload = path.read_bytes()
    return payload


def full_bea(session: Session) -> tuple[int, list[dict]]:
    del session
    url = "https://apps.bea.gov/regional/zip/SARPP.zip"
    payload = _calibration_artifact("bea_rpp", "cal-SARPP.zip")
    records = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if not name.startswith("SARPP_") or not name.endswith(".csv"):
                continue
            geo_type = "state" if "STATE" in name else "metro"
            rows = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8-sig"))
            for row in rows:
                if row.get("LineCode") != "1":
                    continue
                geo_id = row["GeoFIPS"].strip(' \"')
                for year in sorted(key for key in row if key.isdigit() and row[key] not in {"", "(NA)"}):
                    records.append(normalized("02.10", geo_id, geo_type, year, float(row[year]),
                                              "index_us_100", "bea_rpp", f"BEA-SARPP-{year}", url))
    append_jsonl(source_output("bea_rpp"), records)
    return len(records), [{"path": "raw/calibration/bea_rpp/cal-SARPP.zip", "sha256": sha256(payload), "bytes": len(payload)}]


def full_irs(session: Session) -> tuple[int, list[dict]]:
    del session
    url = "https://www.irs.gov/pub/irs-soi/22zpallagi.csv"
    payload = _calibration_artifact("irs_soi", "cal-22zpallagi.csv")
    rows = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    mapping = {
        "07.01": ("N00100", "A00100"), "07.03": ("N01000", "A01000"),
        "07.04": ("N00600", "A00600"),
    }
    count, batch = 0, []
    for row in rows:
        zip_code = (row.get("zipcode") or "").zfill(5)
        # IRS uses 99999 for returns that cannot be assigned to a real ZIP.
        if not zip_code.strip("0") or zip_code == "99999":
            continue
        size = row.get("agi_stub", "all")
        for parent, (count_column, amount_column) in mapping.items():
            for suffix, column, unit in (("returns", count_column, "returns"), ("amount", amount_column, "thousand_USD")):
                value = row.get(column)
                if value in {None, ""}:
                    continue
                batch.append(normalized(f"{parent}:{suffix}:agi_stub_{size}", zip_code, "zip", "2022",
                                        float(value), unit, "irs_soi", "IRS-SOI-ZIP-2022", url,
                                        catalog_field_id=parent, note=f"IRS income-size row {size}"))
                count += 1
        if len(batch) >= 50000:
            append_jsonl(source_output("irs_soi"), batch)
            batch.clear()
    append_jsonl(source_output("irs_soi"), batch)
    return count, [{"path": "raw/calibration/irs_soi/cal-22zpallagi.csv", "sha256": sha256(payload), "bytes": len(payload)}]


def full_usda(session: Session) -> tuple[int, list[dict]]:
    del session
    url = "https://www.ers.usda.gov/media/5570/food-environment-atlas-csv-files.zip?v=99629"
    payload = _calibration_artifact("usda_fea", "cal-fea-2025.zip")
    code_map = {
        "FFRPTH20": ("09.01", "2020"), "LACCESS_POP19": ("09.02:count", "2019"),
        "PCT_LACCESS_POP19": ("09.02:percent", "2019"), "FMRKTPTH18": ("09.03", "2018"),
        "RECFACPTH20": ("09.04", "2020"),
    }
    records = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        rows = csv.DictReader(io.TextIOWrapper(archive.open("StateAndCountyData.csv"), encoding="utf-8-sig"))
        for row in rows:
            if row["Variable_Code"] not in code_map or row["Value"] in {"", "N/A", "-9999", "-8888"}:
                continue
            field_id, year = code_map[row["Variable_Code"]]
            parent = field_id.split(":")[0]
            records.append(normalized(field_id, row["FIPS"], "county", year, float(row["Value"]),
                                      "source_defined", "usda_fea", "USDA-FEA-2025", url,
                                      catalog_field_id=parent, note=f"Variable {row['Variable_Code']}"))
    append_jsonl(source_output("usda_fea"), records)
    return len(records), [{"path": "raw/calibration/usda_fea/cal-fea-2025.zip", "sha256": sha256(payload), "bytes": len(payload)}]


def _expand_range(token: str) -> list[str]:
    match = re.fullmatch(r"([A-Z]\d+_)(\d{3})([EM]):[A-Z]\d+_(\d{3})([EM])", token)
    if not match:
        return [token]
    prefix, start, suffix, end, end_suffix = match.groups()
    if suffix != end_suffix:
        raise ValueError("mixed suffix range")
    return [f"{prefix}{number:03d}{suffix}" for number in range(int(start), int(end) + 1)]


def _census_variable_map(session: Session) -> tuple[dict[str, set[str]], list[dict]]:
    contract = [row for row in load_json(CONTRACT_PATH) if row["rate_limit_profile"] == "census_acs"]
    variable_parents: dict[str, set[str]] = defaultdict(set)
    artifacts = []
    for row in contract:
        for token in row["source_variables"]:
            if token.startswith("group:"):
                group = token.split(":")[1]
                url = f"https://api.census.gov/data/2024/acs/acs5/groups/{group}.json"
                payload, artifact = request_cached(session, "census_acs", f"group-{group}.json", url)
                artifacts.append(artifact)
                variables = json.loads(payload)["variables"]
                for variable in variables:
                    if re.fullmatch(fr"{group}_\d{{3}}[EM]", variable):
                        variable_parents[variable].add(row["field_id"])
            elif "+" in row["source_selector"] and token.startswith("group:"):
                raise AssertionError("handled above")
            else:
                for variable in _expand_range(token):
                    if re.fullmatch(r"[A-Z]\d+_\d{3}[EM]", variable):
                        variable_parents[variable].add(row["field_id"])
        selector_group = row["source_selector"].rsplit("/", 1)[-1].removesuffix(".json")
        if "+" in selector_group:
            for group in selector_group.split("+"):
                if not any(token == f"group:{group}:E/M" for token in row["source_variables"]):
                    continue
    return variable_parents, artifacts


def _census_geo_id(values: dict[str, str], geo_type: str) -> str:
    if geo_type == "state":
        return values["state"]
    if geo_type == "county":
        return values["state"] + values["county"]
    if geo_type == "place":
        return values["state"] + values["place"]
    return values["state"] + values["county"] + values["tract"]


def full_census(session: Session) -> tuple[int, list[dict]]:
    variable_parents, artifacts = _census_variable_map(session)
    variables = sorted(variable_parents)
    packs = [variables[index:index + 49] for index in range(0, len(variables), 49)]
    jobs = [("state", None)] + [(geo, state) for geo in ("county", "place", "tract") for state in STATE_FIPS]
    key = os.environ["CENSUS_API_KEY"]
    count = 0
    for pack_number, pack in enumerate(packs):
        for geo_type, state in jobs:
            params: list[tuple[str, str]] = [("get", "NAME," + ",".join(pack))]
            if geo_type == "state":
                params.append(("for", "state:*") )
            elif geo_type == "county":
                params.extend([("for", "county:*"), ("in", f"state:{state}")])
            elif geo_type == "place":
                params.extend([("for", "place:*"), ("in", f"state:{state}")])
            else:
                params.extend([("for", "tract:*"), ("in", f"state:{state}"), ("in", "county:*")])
            params.append(("key", key))
            url = "https://api.census.gov/data/2024/acs/acs5?" + urllib.parse.urlencode(params)
            name = f"2024-{geo_type}-{state or 'all'}-pack-{pack_number:02d}.json"
            payload, artifact = request_cached(session, "census_acs", name, url)
            artifacts.append(artifact)
            table = json.loads(payload)
            if len(table) < 2:
                continue
            header = table[0]
            batch = []
            for row_values in table[1:]:
                values = dict(zip(header, row_values))
                geo_id = _census_geo_id(values, geo_type)
                for variable in pack:
                    raw_value = values.get(variable)
                    if raw_value in {None, "", "-666666666", "-999999999"}:
                        continue
                    for parent in variable_parents[variable]:
                        batch.append(normalized(f"{parent}:{variable}", geo_id, geo_type, "2024", float(raw_value),
                                                "source_defined", "census_acs", "2024-acs-acs5", url,
                                                catalog_field_id=parent, note=f"ACS variable {variable}"))
                        count += 1
            append_jsonl(source_output("census_acs"), batch)
    return count, artifacts


def _census_counties() -> list[str]:
    cached_packs = sorted(path for path in (RAW / "full" / "bls_laus").glob("2024-pack-*.json")
                          if re.fullmatch(r"2024-pack-\d{3}\.json", path.name))
    if cached_packs:
        indices = [int(path.stem.rsplit("-", 1)[-1]) for path in cached_packs]
        last_artifact = verified_file_artifact(cached_packs[-1])
        last_series = json.loads(cached_packs[-1].read_bytes()).get("Results", {}).get("series", [])
        if (last_artifact is not None and indices == list(range(indices[-1] + 1))
                and len(last_series) < 50):
            counties = set()
            for path in cached_packs:
                if verified_file_artifact(path) is None:
                    raise StopSource("cache_hash_record_missing")
                data = json.loads(path.read_bytes())
                for series in data.get("Results", {}).get("series", []):
                    series_id = series.get("seriesID", "")
                    if series_id.startswith("LAUCN"):
                        counties.add(series_id[5:10])
            if len(counties) >= 3000:
                return sorted(counties)
    key = os.environ["CENSUS_API_KEY"]
    query = urllib.parse.urlencode({"get": "NAME", "for": "county:*", "in": "state:*", "key": key})
    payload = Session("census_acs", calibration=False).request(f"https://api.census.gov/data/2024/acs/acs5?{query}")
    table = json.loads(payload)
    header = table[0]
    return [dict(zip(header, row))["state"] + dict(zip(header, row))["county"] for row in table[1:]]


def full_bls(session: Session) -> tuple[int, list[dict]]:
    contract_row = next(row for row in load_json(CONTRACT_PATH) if row["field_id"] == "03.06")
    templates = contract_row["source_variables"]
    series_geo = {}
    for state in STATE_FIPS:
        for template in templates[:4]:
            series_id = template.format(state_fips_2=state)
            series_geo[series_id] = (state, "state", series_id[-2:])
    for county in _census_counties():
        for template in templates[4:]:
            series_id = template.format(county_fips_5=county)
            series_geo[series_id] = (county, "county", series_id[-2:])
    series = sorted(series_geo)
    records, artifacts, count = [], [], 0
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    for pack_number in range(0, len(series), 50):
        pack = series[pack_number:pack_number + 50]
        body = json.dumps({"seriesid": pack, "startyear": "2024", "endyear": "2024",
                           "registrationkey": os.environ["BLS_API_KEY"]}).encode()
        name = f"2024-pack-{pack_number // 50:03d}.json"
        payload, artifact = request_cached(session, "bls_laus", name, url, body=body,
                                            headers={"Content-Type": "application/json"})
        artifacts.append(artifact)
        data = json.loads(payload)
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise StopSource("provider_rejected_request")
        for series_data in data["Results"]["series"]:
            geo_id, geo_type, measure = series_geo[series_data["seriesID"]]
            for row in series_data["data"]:
                records.append(normalized(f"03.06:{BLS_LAUS_MEASURES[measure]}", geo_id, geo_type,
                                          f"{row['year']}-{row['period']}", float(row["value"]),
                                          "%" if measure == "3" else "persons", "bls_laus",
                                          "BLS-LAUS-2024", url, catalog_field_id="03.06"))
                count += 1
        if len(records) >= 50000:
            append_jsonl(source_output("bls_laus"), records)
            records.clear()
    append_jsonl(source_output("bls_laus"), records)
    return count, artifacts


def full_fbi(session: Session) -> tuple[int, list[dict]]:
    offenses = {
        "04.01": "homicide", "04.02": "violent-crime", "04.03": "robbery",
        "04.04": "aggravated-assault", "04.05": "burglary", "04.06": "motor-vehicle-theft",
        "04.07": "rape",
    }
    records, artifacts, count = [], [], 0
    for state in STATE_ABBR:
        for parent, offense in offenses.items():
            url = f"https://cde.ucr.cjis.gov/LATEST/summarized/state/{state}/{offense}?from=01-2019&to=12-2023&type=totals"
            name = f"{state}-{offense}-2019-2023.json"
            payload, artifact = request_cached(session, "fbi_cde", name, url)
            artifacts.append(artifact)
            data = json.loads(payload)
            actuals = data["offenses"]["actuals"]
            key = next(name for name in actuals if name.endswith("Offenses"))
            annual: dict[str, float] = defaultdict(float)
            for period, value in actuals[key].items():
                year = period[-4:]
                annual[year] += float(value)
            previous = None
            for year in sorted(annual):
                records.append(normalized(parent, state, "state", year, annual[year], "count", "fbi_cde",
                                          "FBI-CDE-2019-2023", url,
                                          note="Annual sum of monthly actuals; source coverage retained in raw artifact"))
                count += 1
                if previous is not None and previous != 0:
                    records.append(normalized(f"04.09:{offense}:yoy", state, "state", year,
                                              (annual[year] - previous) / previous * 100, "%", "fbi_cde",
                                              "FBI-CDE-2019-2023", url, catalog_field_id="04.09"))
                    count += 1
                previous = annual[year]
            if len(records) >= 10000:
                append_jsonl(source_output("fbi_cde"), records)
                records.clear()
    append_jsonl(source_output("fbi_cde"), records)
    return count, artifacts


def full_eia(session: Session) -> tuple[int, list[dict]]:
    offset, page, records, artifacts = 0, 0, [], []
    max_pages = int(session.config["max_pages"])
    while True:
        if page >= max_pages:
            raise StopSource("max_pages")
        params = urllib.parse.urlencode([
            ("api_key", os.environ["EIA_API_KEY"]), ("frequency", "annual"), ("data[0]", "price"),
            ("start", "2024"), ("end", "2024"), ("offset", str(offset)), ("length", "5000"),
        ])
        url = f"https://api.eia.gov/v2/electricity/retail-sales/data/?{params}"
        name = f"electricity-2024-{offset}.json"
        payload, artifact = request_cached(session, "eia", name, url)
        artifacts.append(artifact)
        response = json.loads(payload)["response"]
        rows = response["data"]
        page += 1
        for row in rows:
            geo = row.get("stateid") or row.get("stateDescription") or row.get("utilityid") or "unknown"
            if row.get("price") in {None, ""}:
                continue
            sector = row.get("sectorid") or "unknown"
            records.append(normalized(f"08.05:sector_{sector}", geo, "state", row["period"],
                                      float(row["price"]), row["price-units"], "eia",
                                      "EIA-electricity-retail-sales-2024", url,
                                      catalog_field_id="08.05", note=f"Sector {sector}"))
        offset += len(rows)
        if not rows or offset >= int(response.get("total", offset)):
            break
    append_jsonl(source_output("eia"), records)
    return len(records), artifacts


def full_epa_bulk(session: Session) -> tuple[int, list[dict]]:
    year = "2025"
    url = f"https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_{year}.zip"
    archive_path = RAW / "full" / "epa_airdata" / f"annual-conc-by-monitor-{year}.zip"
    cached_archive = verified_file_artifact(archive_path)
    if cached_archive is not None:
        artifact = cached_archive
        session.cache_hits += 1
    else:
        artifact = session.download(url, archive_path, max_bytes=400 * 1024 * 1024)
    records = []
    count = 0
    with zipfile.ZipFile(archive_path) as archive:
        name = next(item for item in archive.namelist() if item.endswith(".csv"))
        rows = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8-sig"))
        for row in rows:
            code = row.get("Parameter Code")
            if code not in {"88101", "44201"}:
                continue
            field_id = "09.06" if code == "88101" else "09.07"
            value = row.get("Arithmetic Mean") or row.get("1st Max Value")
            if value in {None, ""}:
                continue
            geo_id = f"{row.get('State Code','')}{row.get('County Code','')}{row.get('Site Num','')}"
            dimensions = {
                key: row.get(key, "") for key in (
                    "Parameter Code", "POC", "Sample Duration", "Pollutant Standard",
                    "Metric Used", "Method Name", "Event Type", "Units of Measure",
                )
            }
            category = sha256(json.dumps(dimensions, sort_keys=True, separators=(",", ":")).encode())[:16]
            records.append(normalized(f"{field_id}:series_{category}", geo_id, "monitor", year, float(value),
                                      row.get("Units of Measure", "source_defined"), "epa_airdata",
                                      f"EPA-AirData-{year}", url,
                                      catalog_field_id=field_id,
                                      note=json.dumps(dimensions, sort_keys=True, separators=(",", ":"))))
            count += 1
            if len(records) >= 100000:
                append_jsonl(source_output("epa_airdata"), records)
                records.clear()
    append_jsonl(source_output("epa_airdata"), records)
    return count, [artifact]


FULL_RUNNERS: dict[str, Callable[[Session], tuple[int, list[dict]]]] = {
    "bea_rpp": full_bea,
    "irs_soi": full_irs,
    "usda_fea": full_usda,
    "cdc_places": full_places,
    "eia": full_eia,
    "epa_airdata": full_epa_bulk,
    "bls_laus": full_bls,
    "fbi_cde": full_fbi,
    "census_acs": full_census,
}


def inspect_normalized_output(source: str) -> dict:
    path = source_output(source)
    if not path.exists():
        return {"path": str(path.relative_to(HERE)), "rows": 0, "duplicate_keys": 0,
                "sha256": None, "bytes": 0}
    seen: set[tuple[str, str, str, str]] = set()
    duplicates = 0
    rows = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            key = tuple(str(record[name]) for name in ("geo_id", "year", "field_id", "source_release"))
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
            rows += 1
    payload = path.read_bytes()
    return {"path": str(path.relative_to(HERE)), "rows": rows, "duplicate_keys": duplicates,
            "sha256": sha256(payload), "bytes": len(payload)}


def source_is_complete(manifest: dict, source: str) -> bool:
    item = manifest.get("sources", {}).get(source, {})
    artifact = item.get("normalized_artifact", {})
    if item.get("status") != "pass" or artifact.get("duplicate_keys") != 0:
        return False
    if not artifact.get("path") or not artifact.get("sha256"):
        return False
    path = HERE / artifact["path"]
    return path.exists() and sha256(path.read_bytes()) == artifact["sha256"]


def run_full() -> int:
    global NORMALIZATION_TIMESTAMP
    safety.load_credentials()
    validation = validate_contract()
    if validation["status"] != "pass":
        print(json.dumps(validation, indent=2))
        return 1
    if not CALIBRATION_PATH.exists():
        print(json.dumps({"status": "blocked", "reason": "calibration_missing"}))
        return 1
    calibration = load_json(CALIBRATION_PATH)
    bindings = current_bindings()
    if any(calibration.get(key) != value for key, value in bindings.items()):
        print(json.dumps({"status": "blocked", "reason": "calibration_binding_mismatch"}))
        return 1
    try:
        validate_calibration_artifacts(calibration)
    except Exception as error:
        print(json.dumps({"status": "blocked", "reason": safe_reason(error)}))
        return 1
    manifest = {
        "status": "running", "pid": os.getpid(), "started_at": now(),
        **bindings, "sources": {},
    }
    STATE.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists():
        previous = load_json(MANIFEST_PATH)
        if all(previous.get(key) == value for key, value in bindings.items()):
            manifest = previous
            manifest["status"] = "running"
            manifest["pid"] = os.getpid()
            manifest["resumed_at"] = now()
        else:
            manifest["supersedes_manifest_sha256"] = sha256(MANIFEST_PATH.read_bytes())
    write_json(MANIFEST_PATH, manifest)
    write_json(STATUS_PATH, {"status": "running", "pid": os.getpid(), "updated_at": now()})
    for source, runner in FULL_RUNNERS.items():
        if source_is_complete(manifest, source):
            continue
        if calibration["sources"].get(source, {}).get("status") != "pass":
            manifest["sources"][source] = {"status": "not_run", "reason": "calibration_failed"}
            write_json(MANIFEST_PATH, manifest)
            continue
        session = Session(source, calibration=False)
        started = now()
        prior_source = manifest.get("sources", {}).get(source, {})
        normalization_timestamp = prior_source.get("normalization_retrieved_at") or started
        manifest["sources"][source] = {
            "status": "running", "started_at": started,
            "normalization_retrieved_at": normalization_timestamp,
        }
        manifest["updated_at"] = now()
        write_json(MANIFEST_PATH, manifest)
        output_path = source_output(source)
        if output_path.exists():
            output_path.unlink()
        write_json(STATUS_PATH, {"status": "running", "pid": os.getpid(), "source": source,
                                 "source_status": "running", "started_at": started, "updated_at": now()})
        try:
            NORMALIZATION_TIMESTAMP = normalization_timestamp
            free_bytes = shutil.disk_usage(HERE).free
            minimum_free = 6 * 1024 ** 3 if source == "census_acs" else (2 * 1024 ** 3 if source == "epa_airdata" else 512 * 1024 ** 2)
            if free_bytes < minimum_free:
                raise StopSource("insufficient_free_disk")
            count, artifacts = runner(session)
            normalized_artifact = inspect_normalized_output(source)
            if normalized_artifact["rows"] != count:
                raise StopSource("normalized_row_count_mismatch")
            if normalized_artifact["duplicate_keys"]:
                raise StopSource("duplicate_normalized_keys")
            manifest["sources"][source] = {"status": "pass", "started_at": started,
                                                   "finished_at": now(), "normalized_rows": count,
                                                   "normalization_retrieved_at": normalization_timestamp,
                                                   "artifacts": artifacts,
                                                   "normalized_artifact": normalized_artifact,
                                                   "free_bytes_before": free_bytes,
                                                   **session.metrics()}
        except Exception as error:
            manifest["sources"][source] = {"status": "fail", "started_at": started,
                                                   "finished_at": now(), "reason": safe_reason(error),
                                                   "normalization_retrieved_at": normalization_timestamp,
                                                   **session.metrics()}
        NORMALIZATION_TIMESTAMP = None
        manifest["updated_at"] = now()
        write_json(MANIFEST_PATH, manifest)
        write_json(STATUS_PATH, {"status": "running", "pid": os.getpid(), "source": source,
                                 "source_status": manifest["sources"][source]["status"], "updated_at": now()})
        summary = {key: value for key, value in manifest["sources"][source].items()
                   if key in {"status", "normalized_rows", "reason", "request_count", "response_bytes",
                              "retry_count", "http_429_count", "duration_seconds"}}
        print(json.dumps({"source": source, **summary}), flush=True)
    statuses = [item["status"] for item in manifest["sources"].values()]
    manifest["status"] = "complete" if statuses and all(status == "pass" for status in statuses) else "partial"
    manifest["finished_at"] = now()
    write_json(MANIFEST_PATH, manifest)
    write_json(STATUS_PATH, {"status": manifest["status"], "pid": os.getpid(), "updated_at": now()})
    build_eval()
    return 0 if manifest["status"] == "complete" else 2


def build_eval() -> dict:
    contract = load_json(CONTRACT_PATH)
    calibration = load_json(CALIBRATION_PATH) if CALIBRATION_PATH.exists() else {"sources": {}}
    manifest = load_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else {"sources": {}}
    field_sources = {row["field_id"]: row["rate_limit_profile"] for row in contract}
    coverage: dict[str, dict] = defaultdict(lambda: {"rows": 0, "geographies": set(), "years": set()})
    source_evidence: dict[str, dict] = {}
    for source in FULL_RUNNERS:
        path = source_output(source)
        if not path.exists():
            continue
        source_evidence[source] = inspect_normalized_output(source)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                parent = record.get("catalog_field_id", record["field_id"].split(":")[0])
                item = coverage[parent]
                item["rows"] += 1
                item["geographies"].add(record["geo_type"])
                item["years"].add(record["year"])
    evaluations = []
    contract_hash = sha256(CONTRACT_PATH.read_bytes())
    calibration_hash = sha256(CALIBRATION_PATH.read_bytes()) if CALIBRATION_PATH.exists() else contract_hash
    manifest_hash = sha256(MANIFEST_PATH.read_bytes()) if MANIFEST_PATH.exists() else calibration_hash
    for row in contract:
        field_id = row["field_id"]
        state = row["planned_state"]
        source = field_sources[field_id]
        if state != "run_now":
            result = "BLOCKED"
            observed = state
            reason = row["derivation"]
            evidence = "field-contract.json"
            evidence_hash = contract_hash
        else:
            source_run = manifest.get("sources", {}).get(source)
            field_coverage = coverage.get(field_id, {"rows": 0, "geographies": set(), "years": set()})
            source_artifact = source_evidence.get(source, {})
            if (source_run and source_run.get("status") == "pass" and field_coverage["rows"] > 0
                    and source_artifact.get("duplicate_keys") == 0):
                result, observed, reason = "PASS", "source run completed with normalized rows", ""
                evidence = source_artifact["path"]
                evidence_hash = source_artifact["sha256"]
            elif source_run and source_run.get("status") == "pass":
                result = "FAIL"
                if source_artifact.get("duplicate_keys", 0):
                    observed, reason = "source output contains duplicate normalized keys", "duplicate_normalized_keys"
                else:
                    observed, reason = "source completed but field has zero rows", "zero_normalized_rows"
                evidence = "state/run-manifest.json"
                evidence_hash = manifest_hash
            elif source_run and source_run.get("status") == "fail":
                result, observed, reason = "FAIL", "source run failed", source_run.get("reason", "unknown")
                evidence = "state/run-manifest.json"
                evidence_hash = manifest_hash
            else:
                cal = calibration.get("sources", {}).get(source, {})
                result, observed = "NOT_RUN", "full source run not completed"
                reason = "calibration_failed" if cal.get("status") == "fail" else "run_not_started"
                evidence = "state/calibration-report.json" if cal else "field-contract.json"
                evidence_hash = calibration_hash if cal else contract_hash
        evaluations.append({
            "field_id": field_id, "catalog_label": row["catalog_label"],
            "expected": f"planned_state={state}; source={source}; release={row['source_release']}",
            "observed": observed, "result": result, "evidence": evidence,
            "evidence_sha256": evidence_hash,
            "coverage": {
                "rows": coverage.get(field_id, {}).get("rows", 0),
                "observed_geographies": sorted(coverage.get(field_id, {}).get("geographies", set())),
                "observed_years": sorted(coverage.get(field_id, {}).get("years", set())),
                "target_geographies": row["target_geographies"],
            },
            "reason": reason,
        })
    totals = Counter(item["result"] for item in evaluations)
    report = {"generated_at": now(), "total": len(evaluations), "totals": dict(totals),
              "contract_sha256": contract_hash, "fields": evaluations}
    write_json(EVAL_PATH, report)
    return report


def show_status() -> int:
    status = load_json(STATUS_PATH) if STATUS_PATH.exists() else {"status": "not_started"}
    if status.get("status") == "running" and status.get("pid"):
        try:
            os.kill(int(status["pid"]), 0)
        except ProcessLookupError:
            status = {**status, "status": "interrupted", "reason": "process_not_running"}
        except PermissionError:
            pass
    print(json.dumps(status, indent=2))
    return 0


def mark_interrupted() -> None:
    if MANIFEST_PATH.exists():
        manifest = load_json(MANIFEST_PATH)
        if manifest.get("status") == "running" and manifest.get("pid") == os.getpid():
            manifest["status"] = "interrupted"
            manifest["interrupted_at"] = now()
            write_json(MANIFEST_PATH, manifest)
    write_json(STATUS_PATH, {"status": "interrupted", "pid": os.getpid(), "updated_at": now()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "calibrate", "run", "eval", "status"))
    args = parser.parse_args()
    if args.command == "validate":
        result = validate_contract()
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    if args.command == "calibrate":
        return run_calibration()
    if args.command == "run":
        try:
            return run_full()
        except KeyboardInterrupt:
            mark_interrupted()
            return 130
    if args.command == "eval":
        print(json.dumps(build_eval()["totals"], indent=2))
        return 0
    return show_status()


if __name__ == "__main__":
    raise SystemExit(main())
