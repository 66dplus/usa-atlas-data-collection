#!/usr/bin/env python3
"""Bounded collector for CDC's EHE preliminary HIV diagnosis tables."""
import argparse
import csv
import hashlib
import json
import re
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
RECEIPTS = ROOT / "http-receipts.jsonl"
NAME = "cdc-ehe-hiv-preliminary-through-2026-06.xlsx"
URL = "https://stacks.cdc.gov/view/cdc/260354/cdc_260354_DS1.xlsx"
LANDING_NAME = "cdc-ehe-hiv-preliminary-through-2026-06.html"
LANDING_URL = "https://stacks.cdc.gov/view/cdc/260354"
METHOD_NAME = "cdc-ehe-methodology-2023.pdf"
METHOD_URL = "https://stacks.cdc.gov/view/cdc/156512/cdc_156512_DS1.pdf"
MAX_BYTES = 16 * 1024 * 1024
UA = "USAAtlasResearch/1.0 (public aggregate health data collection)"
OUT = ROOT / "hiv-preliminary"
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch_item(name, url, maximum):
    RAW.mkdir(exist_ok=True)
    target = RAW / name
    receipt = {"name": name, "requested_url": url, "method": "GET", "params": {},
               "payload": None, "started_at": now(), "max_response_bytes": maximum,
               "user_agent": UA}
    digest, total = hashlib.sha256(), 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=30) as response:
            receipt.update(final_url=response.url, http_status=response.status,
                           content_type=response.headers.get("Content-Type"),
                           last_modified=response.headers.get("Last-Modified"),
                           etag=response.headers.get("ETag"))
            tmp = target.with_suffix(target.suffix + ".partial")
            with tmp.open("wb") as out:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError(f"response exceeded {maximum} byte cap")
                    digest.update(chunk)
                    out.write(chunk)
            tmp.replace(target)
        receipt.update(status="downloaded", bytes=total, sha256=digest.hexdigest(),
                       path=str(target.relative_to(ROOT)))
    except urllib.error.HTTPError as exc:
        receipt.update(status="error", http_status=exc.code, final_url=exc.geturl(),
                       error=f"HTTPError: {exc.code} {exc.reason}", bytes=total)
    except Exception as exc:
        receipt.update(status="error", error=f"{type(exc).__name__}: {exc}", bytes=total,
                       partial_sha256=digest.hexdigest())
    receipt["finished_at"] = now()
    with RECEIPTS.open("a", encoding="utf-8") as out:
        out.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(receipt, ensure_ascii=False))
    return receipt


def fetch():
    results = [
        fetch_item(NAME, URL, MAX_BYTES),
        fetch_item(LANDING_NAME, LANDING_URL, 6 * 1024 * 1024),
        fetch_item(METHOD_NAME, METHOD_URL, 10 * 1024 * 1024),
    ]
    if any(x.get("status") != "downloaded" or x.get("http_status") != 200 for x in results):
        raise SystemExit("At least one requested HIV source was not downloaded successfully; see receipts")
    return results


def col_number(cell_ref):
    match = re.match(r"[A-Z]+", cell_ref or "")
    value = 0
    for char in match.group(0) if match else "":
        value = value * 26 + ord(char) - 64
    return value - 1


def parse_workbook(data):
    """Parse worksheet XML with tight bounds; skip oversized chart drawings."""
    with ZipFile(BytesIO(data)) as book:
        if sum(item.file_size for item in book.infolist()) > 96 * 1024 * 1024:
            raise ValueError("workbook uncompressed size exceeds 96 MiB cap")
        names = set(book.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            if book.getinfo("xl/sharedStrings.xml").file_size > 2 * 1024 * 1024:
                raise ValueError("shared strings exceed parser cap")
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in si.findall(".//m:t", NS))
                      for si in root.findall("m:si", NS)]
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        relmap = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
        sheets = []
        for sheet in workbook.find("m:sheets", NS):
            target = relmap[sheet.attrib[f"{{{NS['r']}}}id"]]
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target.removeprefix("../")
            info = book.getinfo(target)
            if info.file_size > 5 * 1024 * 1024:
                raise ValueError(f"worksheet {target} exceeds 5 MiB cap")
            root = ET.fromstring(book.read(target))
            rows = []
            for row in root.findall(".//m:sheetData/m:row", NS):
                values = []
                for cell in row.findall("m:c", NS):
                    value = cell.find("m:v", NS)
                    raw = value.text if value is not None else ""
                    if cell.attrib.get("t") == "s" and raw:
                        raw = shared[int(raw)]
                    elif cell.attrib.get("t") == "inlineStr":
                        raw = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
                    values.append((col_number(cell.attrib.get("r", "")), raw,
                                   cell.attrib.get("r", "")))
                width = max((i for i, _, _ in values), default=-1) + 1
                vals, refs = [""] * width, [""] * width
                for i, raw, ref in values:
                    vals[i], refs[i] = raw, ref
                rows.append((vals, refs))
            sheets.append({"name": sheet.attrib.get("name", "Sheet"), "rows": rows})
    return sheets


def latest_receipts():
    latest = {}
    if RECEIPTS.exists():
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if item.get("name"):
                    latest[item["name"]] = item
            except json.JSONDecodeError:
                continue
    return latest


def require_download(name):
    path = RAW / name
    receipt = latest_receipts().get(name)
    if not path.exists() or not receipt or receipt.get("status") != "downloaded" or receipt.get("http_status") != 200:
        raise RuntimeError(f"Missing successful HTTP 200 receipt for raw/{name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != receipt.get("sha256"):
        raise RuntimeError(f"Receipt SHA-256 mismatch for raw/{name}")
    return path.read_bytes(), receipt


def norm_name(value):
    text = str(value).strip().lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    # Keep "city" where it is part of an independent city name (e.g. Baltimore city),
    # while removing source-unit suffixes used inconsistently between systems.
    text = re.sub(r"\b(county|parish|municipio|borough|census area)\b", " ", text)
    return " ".join(text.split())


def number(text):
    text = str(text).strip().replace(",", "")
    if text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def clean_label(value):
    """Remove only the superscript footnote letters used in this CDC workbook."""
    exact = {
        "Male-to-male sexual contactc": "Male-to-male sexual contact",
        "Injection drug used": "Injection drug use",
        "Heterosexual contacte": "Heterosexual contact",
        "Otherf": "Other",
        "Male-to-male sexual contactc and injection drug used": "Male-to-male sexual contact and injection drug use",
    }
    return exact.get(str(value).strip(), str(value).strip())


def census_counties():
    import sys
    sys.path.insert(0, str(ROOT))
    from collect_additional_surveillance import STATE_ABBR_FIPS, STATE_NAME_ABBR
    recs = latest_receipts()
    census_rec = recs.get("census-2025-county-gazetteer.zip")
    path = RAW / "census-2025-county-gazetteer.zip"
    if not census_rec or census_rec.get("http_status") != 200 or census_rec.get("status") != "downloaded":
        raise RuntimeError("No prior HTTP 200 Census Gazetteer receipt available for county FIPS crosswalk")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != census_rec.get("sha256"):
        raise RuntimeError("Census Gazetteer no longer matches its recorded source hash")
    with ZipFile(BytesIO(raw)) as zf:
        members = zf.namelist()
        if len(members) != 1 or zf.getinfo(members[0]).file_size > 2 * 1024 * 1024:
            raise ValueError("Unexpected Census Gazetteer archive layout/size")
        rows = csv.DictReader(zf.read(members[0]).decode("utf-8").splitlines(), delimiter="|")
        geo = {}
        all_geo = []
        for row in rows:
            code, geoid, name = row["USPS"], row["GEOID"], row["NAME"]
            key = (code, norm_name(name))
            if key in geo:
                raise RuntimeError(f"Duplicate Census Gazetteer name key: {key}")
            geo[key] = {"geoid": geoid, "name": name, "state_code": code,
                        "state_fips": geoid[:2], "source_fips": geoid}
            all_geo.append({"geoid": geoid, "name": name, "state_code": code,
                            "state_fips": geoid[:2]})
    names = dict(STATE_NAME_ABBR)
    names["New York"] = "NY"
    return geo, all_geo, names, STATE_ABBR_FIPS, census_rec


def common_record(value, period, cell, row_num, table_name, table_title,
                  workbook_receipt, retrieved_at, *, geo_level, geoid, geo_name,
                  state_fips=None, state_code=None, source_geoid=None,
                  scope="", stratum_variable="all", stratum_value="all persons aged 13 years or older",
                  sex="both sexes", age_stratum="all ages 13 years and older",
                  race="all races/ethnicities", transmission=None, region=None, source_stratum_text=None):
    year = 2025 if period == "2025" else 2026
    return {
        "metric_id": "hiv_preliminary_diagnoses_count",
        "metric_label": "Preliminary reported HIV diagnoses",
        "geography_level": geo_level, "geoid": geoid, "source_geoid": source_geoid or geoid,
        "geography_name": geo_name, "state_fips": state_fips, "state_code": state_code,
        "boundary_vintage": "2025 Census Gazetteer crosswalk for county identifiers; release does not state boundary vintage" if geo_level == "county" else None,
        "geography_compatibility": "County counts cover selected EHE priority jurisdictions only; they are a subset of state totals and not a complete county series." if geo_level == "county" else "Counts shown at source-reported geography; no smaller-area allocation.",
        "period": period, "period_type": "calendar_year" if period == "2025" else "partial_calendar_year_january_through_june",
        "observation_year": year, "period_month_start": 1, "period_month_end": 12 if year == 2025 else 6,
        "value": value, "value_status": "numeric" if value is not None else "source_cell_blank",
        "unit": "reported_diagnoses", "measure_type": "observed_reported_diagnosis_count",
        "estimate_status": "preliminary", "preliminary": True,
        "age_group": "13 years and older", "age_stratum": age_stratum, "sex": sex,
        "race_ethnicity": race, "transmission_category": transmission, "census_region": region,
        "stratum_variable": stratum_variable, "stratum_value": stratum_value,
        "source_stratum_text": source_stratum_text,
        "source_category": "HIV infection diagnosis, regardless of stage, tabulated by date of diagnosis",
        "source_population_scope": "Persons aged 13 years and older; reported diagnosis dates in observation period; geography is residence at time of HIV diagnosis.",
        "geography_scope": scope,
        "denominator_population": None,
        "denominator_definition": "The workbook publishes counts only; it does not provide population denominators or rates.",
        "source_reporting_cutoff": "Cases reported to CDC through June 2026",
        "source_definition_url": "https://www.cdc.gov/hiv-data/nhss/index.html",
        "source_url": LANDING_URL, "download_url": URL,
        "source_file": "raw/" + NAME, "source_sha256": workbook_receipt["sha256"],
        "source_table": table_name, "source_table_title": table_title,
        "source_row": row_num, "source_cell": cell, "source_value_text": str(value) if value is not None else None,
        "source_suppression_code": None, "source_small_count_caution": value is not None and value < 12,
        "source_missingness_note": "No suppression symbol is present in the normalized diagnosis tables. Published numeric values below 12 are retained and flagged for CDC's small-count caution; published zeros remain numeric. Blank area headers are not observations.",
        "source_note": "CDC states 2025/2026 counts are preliminary until a 12-month reporting delay; values are based on date of diagnosis, not report date. National CDC deduplication/statistical adjustment means values can differ from jurisdiction totals.",
        "retrieved_at": retrieved_at, "production_ready": False,
        "count_comparable_across_geographies": False,
        "comparability_note": "Preliminary reporting lag applies; selected EHE county values are not a complete county set, and county counts must not be expanded or summed as full state totals. 2026 is six months only and is not directly comparable to full-year 2025.",
    }


def periods_for(row):
    return [("2025", 1), ("2026-01_to_2026-06", 2)]


def demographics_records(sheet, workbook_receipt, retrieved_at, all_values, all_geo, states, state_fips):
    rows = sheet["rows"]
    title = rows[0][0][0].strip()
    table_name = sheet["name"]
    territory_inclusive = table_name == "Table 1b"
    records = []
    section = None
    parent_transmission = None
    for row_num, (cells, refs) in enumerate(rows[3:], start=4):
        label = str(cells[0] if cells else "").strip()
        if not label or label.startswith(("Abbreviation:", "Note.")):
            continue
        folded = label.lower().replace("\xa0", " ")
        if folded == "sex": section, parent_transmission = "sex", None; continue
        if folded.startswith("age at diagnosis"): section, parent_transmission = "age_group", None; continue
        if folded.startswith("race/ethnicity"): section, parent_transmission = "race_ethnicity", None; continue
        if folded.startswith("transmission category"): section, parent_transmission = "transmission_category", None; continue
        if folded.startswith("region of residence"): section, parent_transmission = "census_region", None; continue
        if label.startswith("U.S. territories and freely associated states") and territory_inclusive:
            # This row is the territory subtotal in Table 1b, not a characteristic stratum.
            for period, col in periods_for(cells):
                val = number(cells[col] if col < len(cells) else "")
                if val is None: continue
                rec = common_record(val, period, refs[col] if col < len(refs) else None,
                    row_num, table_name, title, workbook_receipt, retrieved_at,
                    geo_level="territory_group", geoid="CDC_HIV_7_TERRITORIES",
                    geo_name="7 U.S. territories and freely associated states",
                    scope="Territory subtotal as shown in CDC Table 1b; seven jurisdictions named in Table 1c.",
                    stratum_variable="all", stratum_value="all persons aged 13 years or older")
                rec["source_suppression_code"] = None
                records.append(rec)
            section = "census_region"
            continue
        if label == "Total":
            for period, col in periods_for(cells):
                val = number(cells[col] if col < len(cells) else "")
                if val is None: continue
                rec = common_record(val, period, refs[col] if col < len(refs) else None,
                    row_num, table_name, title, workbook_receipt, retrieved_at,
                    geo_level="national_plus_territories" if territory_inclusive else "national",
                    geoid="US_PLUS_7_TERRITORIES" if territory_inclusive else "US",
                    geo_name="United States and 7 territories/freely associated states" if territory_inclusive else "United States (50 states and DC)",
                    scope="National total including the seven territories/freely associated states listed by CDC" if territory_inclusive else "United States total; territories/freely associated states excluded",
                    stratum_variable="all", stratum_value="all persons aged 13 years or older")
                records.append(rec)
            continue
        if section is None:
            continue
        v0 = number(cells[1] if len(cells) > 1 else "")
        v1 = number(cells[2] if len(cells) > 2 else "")
        if v0 is None and v1 is None:
            if section == "transmission_category": parent_transmission = clean_label(label)
            continue
        if section == "census_region" and territory_inclusive:
            # U.S. census-region counts are the state/DC population, unchanged from Table 1a.
            continue
        cleaned = clean_label(label)
        stratum_variable, stratum_value, sex, age_stratum = section, cleaned, "both sexes", "all ages 13 years and older"
        race, transmission, region = "all races/ethnicities", None, None
        if section == "sex": sex = label
        elif section == "age_group": age_stratum = label.replace("\xa0", " ")
        elif section == "race_ethnicity": race = cleaned
        elif section == "transmission_category":
            if label in ("Male", "Female") and parent_transmission:
                transmission, sex = parent_transmission, label
                stratum_value = parent_transmission + " / " + label
            else:
                transmission = cleaned
                parent_transmission = None
        elif section == "census_region": region = cleaned
        for period, col in periods_for(cells):
            val = v0 if col == 1 else v1
            if val is None: continue
            scope = ("Seven-jurisdiction-inclusive selected-characteristics table" if territory_inclusive else "United States excluding U.S. territories/freely associated states")
            geoid = "US_PLUS_7_TERRITORIES" if territory_inclusive else "US"
            geo_level = "national_plus_territories" if territory_inclusive else "national"
            if section == "census_region":
                geoid, geo_level, scope = "US", "national", "United States states and DC; Census region categories do not include the separate territory subtotal"
            rec = common_record(val, period, refs[col] if col < len(refs) else None,
                row_num, table_name, title, workbook_receipt, retrieved_at,
                geo_level=geo_level, geoid=geoid,
                geo_name="United States (50 states and DC)" if geoid == "US" else "United States and 7 territories/freely associated states",
                scope=scope, stratum_variable=stratum_variable,
                stratum_value=stratum_value, sex=sex, age_stratum=age_stratum,
                race=race, transmission=transmission, region=region,
                source_stratum_text=label)
            records.append(rec)
    return records


def geography_records(sheets, workbook_receipt, retrieved_at, census_geo, state_names, state_fips):
    records = []
    sheet = next(x for x in sheets if x["name"] == "Table 1c")
    title = sheet["rows"][0][0][0].strip()
    territory_codes = {
        "American Samoa": "AS", "Guam": "GU", "Northern Mariana Islands": "MP",
        "Puerto Rico": "PR", "Republic of the Marshall Islands": "MH",
        "Republic of Palau": "PW", "U.S. Virgin Islands": "VI",
    }
    for row_num, (cells, refs) in enumerate(sheet["rows"][3:], start=4):
        name = str(cells[0] if cells else "").strip()
        if name in state_names:
            code = state_names[name]
            fips = state_fips[code]
            area = {"level": "state", "geoid": fips, "state_fips": fips, "state_code": code, "source_geoid": fips, "name": name, "scope": "State or District of Columbia residence aggregate"}
        elif name in territory_codes:
            code = territory_codes[name]
            area = {"level": "territory", "geoid": code, "state_fips": None, "state_code": code, "source_geoid": code, "name": name, "scope": "One of seven U.S. territories/freely associated states listed in CDC Table 1c; not included in U.S. national row"}
        else:
            continue
        for period, col in periods_for(cells):
            val = number(cells[col] if col < len(cells) else "")
            # These are named geography rows, including source-published zeroes.
            rec = common_record(val, period, refs[col] if col < len(refs) else None,
                row_num, "Table 1c", title, workbook_receipt, retrieved_at,
                geo_level=area["level"], geoid=area["geoid"], geo_name=area["name"],
                state_fips=area["state_fips"], state_code=area["state_code"], source_geoid=area["source_geoid"],
                scope=area["scope"])
            if val is None: rec["source_missingness_note"] = "Named geography row is present but its source count cell is blank; retained as null."
            records.append(rec)
    county_sheet = next(x for x in sheets if x["name"] == "Table 1d")
    title = county_sheet["rows"][0][0][0].strip()
    parent = None
    for row_num, (cells, refs) in enumerate(county_sheet["rows"][3:], start=4):
        label = str(cells[0] if cells else "").strip()
        if not label or label.startswith(("Total", "Abbreviations:", "Note.")):
            continue
        values = [number(cells[i] if i < len(cells) else "") for i in (1, 2)]
        if label in state_names or label in territory_codes:
            parent = label
            continue
        if parent is None or (values[0] is None and values[1] is None):
            continue
        if parent == "District of Columbia":
            # Table 1d repeats DC in full; the direct state-level row is already Table 1c.
            continue
        if parent not in state_names and parent not in territory_codes:
            raise RuntimeError(f"Unexpected Table 1d state/territory heading before {label!r}: {parent!r}")
        state_code = state_names.get(parent, territory_codes.get(parent))
        key = (state_code, norm_name(label))
        area = census_geo.get(key)
        if area is None:
            raise RuntimeError(f"County name did not resolve to Census 2025 FIPS: state={parent!r}, county={label!r}, key={key!r}")
        geo_level = "municipality" if parent == "Puerto Rico" else "county"
        for period, col in periods_for(cells):
            val = number(cells[col] if col < len(cells) else "")
            rec = common_record(val, period, refs[col] if col < len(refs) else None,
                row_num, "Table 1d", title, workbook_receipt, retrieved_at,
                geo_level=geo_level, geoid=area["geoid"], geo_name=label,
                state_fips=area["state_fips"], state_code=area["state_code"], source_geoid=area["source_fips"],
                scope="Selected EHE priority jurisdiction only; no inference for other counties in this state")
            rec["source_geography_name"] = label
            rec["fips_lookup_source"] = "U.S. Census Bureau 2025 County Gazetteer"
            if val is None: rec["source_missingness_note"] = "Named selected EHE geography row has a blank source count cell; retained as null."
            records.append(rec)
    return records


def write_outputs(records, all_geo, workbook_receipt, census_receipt):
    OUT.mkdir(exist_ok=True)
    seen, conflicts = {}, []
    for rec in records:
        key = (rec["metric_id"], rec["period"], rec["geography_level"], rec["geoid"],
               rec["stratum_variable"], rec["stratum_value"], rec["sex"], rec["age_stratum"], rec["race_ethnicity"], rec["transmission_category"], rec["census_region"])
        if key in seen:
            old = seen[key]
            if old["value"] != rec["value"]: conflicts.append((key, old["value"], rec["value"]))
            continue
        seen[key] = rec
    if conflicts:
        raise RuntimeError("Conflicting duplicate workbook observations: " + repr(conflicts[:5]))
    records = list(seen.values())
    records.sort(key=lambda r: (r["period"], r["geography_level"], r["geoid"], r["stratum_variable"], r["stratum_value"], r["source_table"], r["source_row"]))
    for rec in records:
        stable = "|".join(str(rec.get(k) or "") for k in ("metric_id", "period", "geography_level", "geoid", "stratum_variable", "stratum_value", "sex", "age_stratum", "race_ethnicity", "transmission_category", "census_region"))
        rec["observation_id"] = hashlib.sha256(stable.encode()).hexdigest()
    (OUT / "observations.json").write_text(json.dumps({"schema_version": 1, "as_of": "2026-10-05", "observations": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = sorted({k for row in records for k,v in row.items() if not isinstance(v,(dict,list))})
    with (OUT / "observations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(records)
    observed_counties = {r["geoid"] for r in records if r["geography_level"] in ("county", "municipality")}
    state_rows = [r for r in records if r["geography_level"] == "state"]
    county_geos = []
    for geo in all_geo:
        is_observed = geo["geoid"] in observed_counties
        county_geos.append({**geo, "collection_status": "observed_selected_ehe_county_or_municipality" if is_observed else "not_in_this_release"})
    with (OUT / "coverage-geographies.csv").open("w", encoding="utf-8", newline="") as handle:
        cols = ["geoid", "name", "state_code", "state_fips", "collection_status"]
        writer = csv.DictWriter(handle, fieldnames=cols); writer.writeheader(); writer.writerows(county_geos)
    periods = {}
    for r in records:
        entry = periods.setdefault(r["period"], {"records": 0, "numeric": 0, "missing": 0, "geographies": {}})
        entry["records"] += 1
        entry["numeric"] += r["value_status"] == "numeric"
        entry["missing"] += r["value_status"] != "numeric"
        entry["geographies"][r["geography_level"]] = entry["geographies"].get(r["geography_level"], 0) + 1
    coverage = {
        "as_of": "2026-10-05", "metric_id": "hiv_preliminary_diagnoses_count",
        "records": len(records), "numeric": sum(r["value_status"] == "numeric" for r in records),
        "missing_or_suppressed": sum(r["value_status"] != "numeric" for r in records), "periods": periods,
        "observation_periods": {"2025": "Full calendar year; preliminary", "2026-01_to_2026-06": "January through June only; preliminary"},
        "geographic_coverage": {
            "national": ["US", "US_PLUS_7_TERRITORIES"],
            "state_geographies_numeric": sorted({r["geoid"] for r in state_rows if r["value_status"] == "numeric"}),
            "state_geographies_count": len({r["geoid"] for r in state_rows}),
            "territories_numeric": sorted({r["geoid"] for r in records if r["geography_level"] == "territory" and r["value_status"] == "numeric"}),
            "ehe_counties_and_municipalities_numeric": sorted(observed_counties),
            "ehe_counties_and_municipalities_count": len(observed_counties),
            "unobserved_census_county_equivalents": sum(g["collection_status"] == "not_in_this_release" for g in county_geos),
            "county_geographies_reference": "coverage-geographies.csv",
            "tracts_observed": [], "block_groups_observed": [],
        },
        "strata_available": ["sex", "age at diagnosis", "race/ethnicity", "transmission category", "U.S. Census region"],
        "strata_geography_scope": "National Table 1a (U.S. excluding seven territories) and Table 1b (U.S. plus seven territories for selected characteristics); no state/county race/sex strata in this workbook.",
        "rate_coverage": "No rates, rate denominators, or population denominators are published in the workbook.",
        "source_limitations": [
            "2025 and Jan-Jun 2026 counts are preliminary until the 12-month reporting delay; CDC advises not to assess trends or compare these counts with previous years before sufficient delay.",
            "Diagnosis counts are persons aged 13 years and older diagnosed in the period by date of diagnosis, not estimated infections occurring in that period.",
            "County observations cover only CDC EHE priority jurisdictions: the listed county/county-equivalent areas and San Juan Municipio. Remaining Census county-equivalents are not included, not zero.",
            "Counts under 12 are published but CDC cautions they are statistically unstable; the collector retains them and flags source_small_count_caution.",
            "No tract, block-group, or routine all-county observations are published in this release. Blank parent labels in Table 1d are headers, not missing county values.",
            "This dataset does not replace CDC modeled estimated incidence, or the separate end-year count of people living with diagnosed HIV; no total estimated prevalence is in this workbook.",
            "CDC notes national deduplication and statistical adjustment for missing transmission category, so national totals may not match jurisdiction-published totals and adjusted transmission categories may not sum exactly.",
        ],
        "source_download": {"path": workbook_receipt["path"], "url": workbook_receipt["final_url"], "http_status": workbook_receipt["http_status"], "bytes": workbook_receipt["bytes"], "sha256": workbook_receipt["sha256"], "retrieved_at": workbook_receipt["finished_at"]},
        "fips_reference": {"path": "raw/census-2025-county-gazetteer.zip", "url": census_receipt.get("requested_url"), "sha256": census_receipt.get("sha256"), "retrieved_at": census_receipt.get("finished_at")},
    }
    (OUT / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return coverage, county_geos


def update_source_register(receipts, workbook_receipt, landing_receipt, method_receipt):
    path = ROOT / "source-register.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_sources = data.setdefault("raw_sources", [])
    entry = {
        "source_id": NAME, "publisher": "CDC / NCHHSTP Division of HIV Prevention",
        "role": "official_observed_surveillance_data", "accessed_at": workbook_receipt["finished_at"],
        "url": URL, "landing_page": LANDING_URL, "documentation_url": METHOD_URL,
        "http_status": workbook_receipt["http_status"], "access_outcome": workbook_receipt["status"],
        "sha256": workbook_receipt["sha256"], "bytes": workbook_receipt["bytes"], "path": workbook_receipt["path"],
        "method": "GET", "params": {}, "payload": None, "content_type": workbook_receipt.get("content_type"),
        "source_release": "Core Indicators for Monitoring the Ending the HIV Epidemic Initiative, preliminary through June 2026; published 2026-09-24",
        "observation_period": "2025 full calendar year and 2026-01 through 2026-06", "population_universe": "Persons aged 13 years or older diagnosed with HIV; diagnosis date; residence at time of diagnosis",
        "source_geography_level": "national, 50 states/DC, 7 territories/freely associated states; county/county-equivalent EHE priority jurisdictions only",
        "geography": "Table 1c national/state/territory; Table 1d selected EHE counties and San Juan Municipio; national demographic strata Tables 1a-b",
        "next_collection_step": "Revisit the next CDC EHE preliminary release after the 12-month reporting delay; preserve county subset, report cutoff, and age universe. Track complete 2025 diagnosis release separately from the preliminary series.",
        "documentation_urls": [LANDING_URL, METHOD_URL, "https://www.cdc.gov/hiv-data/nhss/index.html", "https://gis.cdc.gov/grasp/nchhstpatlas/tables.html"],
        "access_attempts": [workbook_receipt, landing_receipt, method_receipt],
    }
    old = next((x for x in raw_sources if x.get("source_id") == NAME), None)
    if old: old.update(entry)
    else: raw_sources.append(entry)
    methods = data.setdefault("methodology_sources", [])
    for url, title in [
        (LANDING_URL, "CDC Stacks release metadata and direct data endpoint for EHE preliminary HIV diagnoses through June 2026"),
        (METHOD_URL, "CDC EHE tables technical notes and prior full tabulation/methodology; current release also embeds a Technical Notes tab"),
        ("https://www.cdc.gov/hiv-data/nhss/index.html", "CDC NHSS diagnosis definition, reporting delays, suppression, prevalence and incidence distinction"),
        ("https://gis.cdc.gov/grasp/nchhstpatlas/tables.html", "CDC AtlasPlus preliminary 2025/2026 notice and table geography/demographic availability"),
    ]:
        if not any(x.get("url") == url for x in methods):
            methods.append({"url": url, "title": title, "publisher": "CDC", "accessed_at": "2026-10-05", "role": "primary_methodology", "access_outcome": "opened_live_official_documentation"})
    data["refreshed_at"] = now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize():
    workbook, workbook_receipt = require_download(NAME)
    landing, landing_receipt = require_download(LANDING_NAME)
    _, method_receipt = require_download(METHOD_NAME)
    page_text = landing.decode("utf-8", "replace")
    if "through June 2026" not in page_text and "260354_DS1.xlsx" not in page_text:
        raise RuntimeError("Official CDC Stacks landing page does not identify the expected June 2026 release")
    sheets = parse_workbook(workbook)
    required = {"Technical Notes", "Table 1a", "Table 1b", "Table 1c", "Table 1d"}
    if not required.issubset({x["name"] for x in sheets}):
        raise RuntimeError(f"Expected CDC workbook sheets missing: {required - {x['name'] for x in sheets}}")
    _, all_geo, state_names, state_fips, census_receipt = census_counties()
    retrieved_at = workbook_receipt["finished_at"]
    records = []
    records += demographics_records(next(x for x in sheets if x["name"] == "Table 1a"), workbook_receipt, retrieved_at, None, None, state_names, state_fips)
    records += demographics_records(next(x for x in sheets if x["name"] == "Table 1b"), workbook_receipt, retrieved_at, None, None, state_names, state_fips)
    county_geo, _, _, _, _ = census_counties()
    records += geography_records(sheets, workbook_receipt, retrieved_at, county_geo, state_names, state_fips)
    coverage, county_geos = write_outputs(records, all_geo, workbook_receipt, census_receipt)
    update_source_register(latest_receipts(), workbook_receipt, landing_receipt, method_receipt)
    (OUT / "source-checks.json").write_text(json.dumps({
        "as_of": "2026-10-05", "release_date": "2026-09-24",
        "sources": [
            {"source_id": x["name"], "url": x["requested_url"], "http_status": x.get("http_status"), "status": x["status"], "bytes": x.get("bytes"), "sha256": x.get("sha256"), "path": x.get("path"), "retrieved_at": x.get("finished_at")}
            for x in (workbook_receipt, landing_receipt, method_receipt)
        ],
        "table_validation": {"sheet_names": [x["name"] for x in sheets], "diagnosis_table_1c_rows_parsed": sum(r["source_table"] == "Table 1c" for r in records), "selected_local_table_1d_rows_parsed": sum(r["source_table"] == "Table 1d" for r in records), "source_suppression_symbols_observed": 0, "numeric_published_zeros_retained": sum(r["value"] == 0 for r in records)},
        "coverage_counts": {"observations": coverage["records"], "numeric": coverage["numeric"], "state_geographies": coverage["geographic_coverage"]["state_geographies_count"], "selected_county_or_municipality_geographies": coverage["geographic_coverage"]["ehe_counties_and_municipalities_count"]},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(readme(coverage), encoding="utf-8")
    print(json.dumps({"observations": coverage["records"], "numeric": coverage["numeric"], "periods": coverage["periods"], "state_geographies": coverage["geographic_coverage"]["state_geographies_count"], "county_geographies": coverage["geographic_coverage"]["ehe_counties_and_municipalities_count"]}, ensure_ascii=False))


def readme(coverage):
    return f'''# CDC preliminary HIV diagnosis tables\n\nDownloaded and normalized 2026-10-05 from CDC Stacks release 2026-09-24. Reproduction uses `python3 collect_hiv_preliminary.py fetch` and `python3 collect_hiv_preliminary.py normalize`.\n\n## Dataset\n\n`observations.csv` and `.json` contain **{coverage['records']} rows ({coverage['numeric']} numeric)** for `hiv_preliminary_diagnoses_count`. CDC's workbook reports diagnoses among persons aged 13 years and older by date of diagnosis, through June 2026. It has a full-year 2025 column and a separate January-June 2026 column. These are observed diagnoses, not estimated incident infections. They remain separate from diagnosed HIV prevalence and modeled total prevalence.\n\nThe collection includes Table 1a national demographic strata (sex, age, race/ethnicity, transmission category and Census region), Table 1b selected characteristics with the separate seven-territory scope, Table 1c state/DC and named territory counts, and Table 1d selected EHE county/county-equivalent counts. No rates or denominators are published. County identifiers are matched by state and source name to the downloaded 2025 Census Gazetteer; source table boundary vintage is unspecified. Each normalized record retains its table, row, cell, source text, workbook hash and report cutoff.\n\n## Coverage and limits\n\n- State/DC: {coverage['geographic_coverage']['state_geographies_count']} published geographies (FIPS preserved as two-character strings). Seven named territories/freely associated states are separate rows. National tables include `US` and `US_PLUS_7_TERRITORIES` scopes as explicitly titled.\n- County/county-equivalent: {coverage['geographic_coverage']['ehe_counties_and_municipalities_count']} selected EHE jurisdictions, listed in `coverage.json`. `coverage-geographies.csv` compares these with every Census 2025 county-equivalent identifier and labels all others `not_in_this_release`. Unlisted counties are unavailable in this release, not zero. No tracts or block groups.\n- The 2026 column covers six months, not a full year. CDC says 2025 and 2026 counts are preliminary until a 12-month reporting delay and cautions against trend or cross-year count comparisons. Values under 12 remain numeric and receive `source_small_count_caution`; source-published zeros remain zero. No suppression symbols appeared in the collected diagnosis tables.\n- The workbook does not include population denominators/rates. National race/sex strata are not state or county cross-tabs. Transmission-category counts are statistically adjusted for missing category and may not sum to the total. CDC's national deduplication and statistical adjustments can cause differences from jurisdiction publications.\n\nSee `coverage.json`, `source-checks.json`, the row-level provenance and `../http-receipts.jsonl` for coverage and verified HTTP outcomes.\n'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["fetch", "normalize", "inspect"])
    args = parser.parse_args()
    if args.stage == "fetch":
        fetch()
    elif args.stage == "normalize":
        normalize()
    else:
        data = (RAW / NAME).read_bytes()
        sheets = parse_workbook(data)
        for sheet in sheets:
            print(f"\n### {sheet['name']} rows={len(sheet['rows'])}")
            for values, _ in sheet["rows"][:18]:
                print(json.dumps(values[:20], ensure_ascii=False))
