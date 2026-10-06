#!/usr/bin/env python3
"""Bounded collectors for the CDC STI 2024 and TB 2024 public tables.

Only public, official CDC endpoints are used. ZIP members are parsed in place;
their original container, request receipt, and hashes remain in raw/.
"""
import argparse
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "additional-surveillance"
RECEIPTS = ROOT / "http-receipts.jsonl"
UA = "USAAtlasResearch/1.0 (public aggregate health data collection)"
MAX_BYTES = {
    "cdc-sti-surveillance-2024-provisional.html": 6 * 1024 * 1024,
    "cdc-sti-surveillance-2024-provisional-data-files.zip": 64 * 1024 * 1024,
    "cdc-tb-reporting-areas-2023-2024.html": 6 * 1024 * 1024,
    "cdc-tb-technical-notes.html": 6 * 1024 * 1024,
    "cdc-heptracker-overview.html": 6 * 1024 * 1024,
}
URLS = {
    "cdc-sti-surveillance-2024-provisional.html": "https://www.cdc.gov/sti-statistics/annual/index.html",
    "cdc-sti-surveillance-2024-provisional-data-files.zip": "https://www.cdc.gov/sti-statistics/media/files/2025/09/STI-Surveillance-Report-2024-Provisional_data-files.zip",
    "cdc-tb-reporting-areas-2023-2024.html": "https://www.cdc.gov/tb-surveillance-report-2024/data/reporting-areas.html",
    "cdc-tb-technical-notes.html": "https://www.cdc.gov/tb-surveillance-report-2024/executive-commentary/technical-notes.html",
    "cdc-heptracker-overview.html": "https://www.cdc.gov/hepatitis/php/data-research/heptracker/index.html",
}
STI_ZIP = "cdc-sti-surveillance-2024-provisional-data-files.zip"
STI_PAGE = "cdc-sti-surveillance-2024-provisional.html"
TB_PAGE = "cdc-tb-reporting-areas-2023-2024.html"
TB_NOTES = "cdc-tb-technical-notes.html"
HEP_PAGE = "cdc-heptracker-overview.html"
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

STATE_FIPS = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05",
    "California": "06", "Colorado": "08", "Connecticut": "09", "Delaware": "10",
    "District of Columbia": "11", "Florida": "12", "Georgia": "13", "Hawaii": "15",
    "Idaho": "16", "Illinois": "17", "Indiana": "18", "Iowa": "19", "Kansas": "20",
    "Kentucky": "21", "Louisiana": "22", "Maine": "23", "Maryland": "24",
    "Massachusetts": "25", "Michigan": "26", "Minnesota": "27", "Mississippi": "28",
    "Missouri": "29", "Montana": "30", "Nebraska": "31", "Nevada": "32",
    "New Hampshire": "33", "New Jersey": "34", "New Mexico": "35", "New York State2": "36",
    "North Carolina": "37", "North Dakota": "38", "Ohio": "39", "Oklahoma": "40",
    "Oregon": "41", "Pennsylvania": "42", "Rhode Island": "44", "South Carolina": "45",
    "South Dakota": "46", "Tennessee": "47", "Texas": "48", "Utah": "49",
    "Vermont": "50", "Virginia": "51", "Washington": "53", "West Virginia": "54",
    "Wisconsin": "55", "Wyoming": "56",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch(name, url, maximum):
    """Single bounded GET; record outcomes even when HTTP or size checks fail."""
    RAW.mkdir(exist_ok=True)
    receipt = {"name": name, "requested_url": url, "method": "GET", "params": {},
               "payload": None, "started_at": now(), "max_response_bytes": maximum,
               "user_agent": UA}
    digest = hashlib.sha256()
    total = 0
    target = RAW / name
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=30) as response:
            receipt.update(final_url=response.url, http_status=response.status,
                           content_type=response.headers.get("Content-Type"),
                           last_modified=response.headers.get("Last-Modified"),
                           etag=response.headers.get("ETag"))
            tmp = target.with_suffix(target.suffix + ".partial")
            with tmp.open("wb") as output:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError(f"response exceeded {maximum} byte cap")
                    digest.update(chunk)
                    output.write(chunk)
            tmp.replace(target)
        receipt.update(bytes=total, sha256=digest.hexdigest(),
                       path=str(target.relative_to(ROOT)), status="downloaded")
    except urllib.error.HTTPError as exc:
        receipt.update(final_url=exc.geturl(), http_status=exc.code,
                       content_type=exc.headers.get("Content-Type") if exc.headers else None,
                       status="error", error=f"HTTPError: {exc.code} {exc.reason}", bytes=total)
    except Exception as exc:
        receipt.update(status="error", error=f"{type(exc).__name__}: {exc}", bytes=total,
                       partial_sha256=digest.hexdigest())
    receipt["finished_at"] = now()
    with RECEIPTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "payload"}, ensure_ascii=False), flush=True)
    return receipt


def fetch_all():
    for name, url in URLS.items():
        fetch(name, url, MAX_BYTES[name])
        time.sleep(.25)


def latest_receipts():
    latest = {}
    if RECEIPTS.exists():
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                name = item.get("name") or Path(item.get("path", "")).name
                if name:
                    latest[name] = item
            except json.JSONDecodeError:
                continue
    return latest


def require_source(name):
    path = RAW / name
    rec = latest_receipts().get(name)
    if not path.exists() or not rec or rec.get("status") != "downloaded" or rec.get("http_status") != 200:
        raise RuntimeError(f"No successful HTTP 200 download receipt for raw/{name}")
    content = path.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    if sha != rec.get("sha256"):
        raise RuntimeError(f"Source hash does not match latest receipt for raw/{name}")
    return content, rec


def col_number(cell_ref):
    letters = re.match(r"[A-Z]+", cell_ref or "")
    value = 0
    for ch in letters.group(0) if letters else "":
        value = value * 26 + ord(ch) - 64
    return value - 1


def parse_xlsx(data, max_member_bytes=4 * 1024 * 1024):
    """Read small public CDC spreadsheets without non-standard XLSX packages."""
    with zipfile.ZipFile(BytesIO(data)) as book:
        if sum(info.file_size for info in book.infolist()) > 24 * 1024 * 1024:
            raise ValueError("nested spreadsheet exceeds uncompressed size cap")
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                      for si in root.findall("m:si", NS)]
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        relmap = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
        sheets = []
        for sheet in workbook.find("m:sheets", NS):
            target = relmap[sheet.attrib[f"{{{NS['r']}}}id"]]
            target = target if target.startswith("xl/") else "xl/" + target
            xml = book.read(target)
            if len(xml) > max_member_bytes:
                raise ValueError("worksheet exceeds parser size cap")
            root = ET.fromstring(xml)
            rows = []
            for row in root.findall(".//m:sheetData/m:row", NS):
                values = []
                for cell in row.findall("m:c", NS):
                    value = cell.find("m:v", NS)
                    raw = value.text if value is not None else ""
                    if cell.attrib.get("t") == "s" and raw:
                        raw = shared[int(raw)]
                    elif cell.attrib.get("t") == "inlineStr":
                        raw = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                    values.append((col_number(cell.attrib.get("r", "")), raw,
                                   cell.attrib.get("r", "")))
                width = max((i for i, _, _ in values), default=-1) + 1
                vals = [""] * width
                refs = [""] * width
                for i, val, ref in values:
                    vals[i] = val
                    refs[i] = ref
                rows.append((vals, refs))
            sheets.append({"name": sheet.attrib.get("name", "Sheet1"), "rows": rows})
    return sheets


def numeric(raw):
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def clean_year(raw):
    m = re.search(r"\b(20\d{2}|19\d{2})\b", str(raw))
    return int(m.group(1)) if m else None


def slug(text):
    s = str(text).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unspecified"


def sti_member_records(archive, archive_hash, retrieved_at):
    records = []
    members = [
        "Public Spreadsheets/CS - Cases by Year of Birth and Syphilis Rates Women 15-44 (US 2015-2024).xlsx",
        "Public Spreadsheets/CT - Rates by Sex (US 2015-2024).xlsx",
        "Public Spreadsheets/GC - Rates by Sex (US 2015-2024).xlsx",
        "Public Spreadsheets/PS Syphilis - Cases by Sex and Sex of Sex Partners (US 2015-2024).xlsx",
        "Public Spreadsheets/PS Syphilis - Rates by Sex (US 2015-2024).xlsx",
        "Public Spreadsheets/STI - Cases by Year (US 2015-2024).xlsx",
        "Public Spreadsheets/Syphilis - Cases by Stage and Year (US 2015-2024).xlsx",
        "Public Spreadsheets/Syphilis - Cases Men by Stage and Year (US 2015-2024).xlsx",
        "Public Spreadsheets/Syphilis - Cases Women by Stage and Year (US 2015-2024).xlsx",
    ]
    with zipfile.ZipFile(BytesIO(archive)) as outer:
        names = set(outer.namelist())
        missing = [name for name in members if name not in names]
        if missing:
            raise RuntimeError(f"CDC ZIP members missing: {missing}")
        for member in members:
            member_bytes = outer.read(member)
            member_hash = hashlib.sha256(member_bytes).hexdigest()
            for sheet in parse_xlsx(member_bytes):
                if not sheet["rows"]:
                    continue
                header = [str(v).strip() for v in sheet["rows"][0][0]]
                for row_number, (cells, refs) in enumerate(sheet["rows"][1:], start=2):
                    row = {header[i]: (cells[i] if i < len(cells) else "") for i in range(len(header))}
                    cell_refs = {header[i]: (refs[i] if i < len(refs) else "") for i in range(len(header))}
                    joined = " ".join(str(x) for x in row.values())
                    if re.search(r"2024 data are provisional", joined, re.I):
                        continue
                    year_text = row.get("Year", "")
                    year = clean_year(year_text)
                    if year is None:
                        continue
                    is_birth_year = "by year of birth" in member.lower() and "CS cases" in row
                    raw_value = None
                    metric = None
                    label = None
                    sex = None
                    subgroup = None
                    denominator = "not applicable to counts"
                    rate_period = False
                    points = []
                    if "STI - Cases by Year" in member:
                        label = row.get("STI", "")
                        metric = "sti_" + slug(label) + "_reported_cases_count"
                        raw_value = row.get("Cases", "")
                    elif "Cases" in member and "Stage and Year" in member:
                        label = row.get("Syphilis Stage", "")
                        sex = row.get("Sex", "") or "both sexes"
                        metric = "syphilis_" + slug(label) + "_reported_cases_count"
                        if "Cases Men" in member:
                            sex = "men"
                            metric = "syphilis_" + slug(label) + "_men_reported_cases_count"
                        elif "Cases Women" in member:
                            sex = "women"
                            metric = "syphilis_" + slug(label) + "_women_reported_cases_count"
                        raw_value = row.get("Cases", "")
                    elif "Cases by Sex and Sex of Sex Partners" in member:
                        label = row.get("STI", "Primary and secondary syphilis")
                        subgroup = row.get("Sex and Sex of Sex Partners", "")
                        sex = subgroup
                        metric = "syphilis_primary_and_secondary_" + slug(subgroup) + "_partner_category_reported_cases_count"
                        raw_value = row.get("Cases", "")
                    elif "Rates by Sex" in member:
                        label = row.get("STI", "")
                        sex = row.get("Sex", "")
                        metric = "sti_" + slug(label) + "_" + slug(sex) + "_reported_rate"
                        raw_value = row.get("Rate", "")
                        rate_period = True
                        denominator = "U.S. population in the same sex stratum; exact denominator not included in workbook"
                    elif "CS - Cases by Year of Birth" in member:
                        if row.get("CS cases", "") != "":
                            points.append(("syphilis_congenital_cases_by_birth_year_count", "Congenital syphilis cases by infant year of birth", row.get("CS cases", ""), False, "infant sex not reported", "congenital syphilis cases", "not applicable to counts", "birth_year"))
                        for col, metric_id, measure_label in [
                            ("Total syphilis rate (women 15–44 years)", "syphilis_total_women_15_44_reported_rate", "Total syphilis rate among women ages 15–44"),
                            ("P&S syphilis rate (women 15–44 years)", "syphilis_primary_secondary_women_15_44_reported_rate", "Primary and secondary syphilis rate among women ages 15–44"),
                        ]:
                            val = row.get(col, "")
                            if val != "":
                                points.append((metric_id, measure_label, val, True, "women", "women ages 15–44", "women ages 15–44 population; exact denominator not included in workbook", "calendar_year"))
                    if metric:
                        year_basis = "birth_year" if is_birth_year and metric.endswith("count") else "calendar_year"
                        points.append((metric, label, raw_value, rate_period, sex or "all sexes / total as labeled by source", subgroup, denominator, year_basis))
                    if not points:
                        continue
                    area = {
                        "geography_level": "national", "geoid": "US",
                        "geography_name": "United States (CDC NNDSS national surveillance total)",
                        "state_code": None, "boundary_vintage": None,
                        "geography_compatibility": "national_series_includes_DC_excludes_US_territories; counts_include_non_US_residents",
                    }
                    for metric_id, label, raw_value, rate_period, sex, subgroup, denominator, year_basis in points:
                        value = numeric(raw_value)
                        status = "numeric" if value is not None else ("missing_source_cell" if raw_value in (None, "") else "non_numeric_source_value")
                        rate_unit = "reported_cases_per_100000_population"
                        if "women_15_44" in metric_id:
                            rate_unit = "reported_cases_per_100000_women_ages_15_44"
                        base_unit = rate_unit if rate_period else "reported_cases"
                        records.append({
                            "metric_id": metric_id, "metric_label": label, **area,
                            "period": str(year), "period_type": "annual",
                            "period_basis": year_basis, "value": value,
                            "value_status": status, "unit": base_unit,
                            "measure_type": "reported_case_count" if not rate_period else "published_reported_case_rate",
                            "estimate_status": "provisional" if year == 2024 else "published_historical",
                            "preliminary": year == 2024,
                            "age_group": "all ages" if not subgroup else subgroup,
                            "sex": sex,
                            "race_ethnicity": "not stratified in selected sheet",
                            "source_category": label,
                            "subgroup": subgroup,
                            "denominator_population": None,
                            "denominator_definition": denominator,
                            "source_population_scope": "CDC 2024 provisional STI surveillance: U.S. including D.C., excluding U.S. territories; national counts include cases reported among non-U.S. residents",
                            "source_reporting_cutoff": "2025-08-14 for 2024 provisional data",
                            "source_url": URLS[STI_PAGE],
                            "download_url": URLS[STI_ZIP],
                            "source_file": "raw/" + STI_ZIP,
                            "source_sha256": archive_hash,
                            "source_member": member,
                            "source_member_sha256": member_hash,
                            "source_sheet": sheet["name"],
                            "source_row": row_number,
                            "source_cells": {key: cell_refs.get(key) for key in row if cell_refs.get(key)},
                            "source_value_text": str(raw_value) if raw_value is not None else None,
                            "source_year_text": str(year_text),
                            "source_suppression_code": None,
                            "source_missingness_note": "Blank cells are retained as null with missing_source_cell; the workbook does not distinguish suppression from unavailable values.",
                            "retrieved_at": retrieved_at,
                            "production_ready": False,
                            "comparability_note": "National aggregate only; do not infer state or county values from this total. Sex and age-specific measures retain their source-specific denominators.",
                        })
    return records


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table": self.table = []
        elif self.table is not None and tag == "tr": self.row = []
        elif self.table is not None and tag in ("td", "th"): self.cell = []

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.table is not None and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def int_text(raw):
    cleaned = re.sub(r"[^0-9-]", "", raw or "")
    return int(cleaned) if cleaned not in ("", "-") else None


def float_text(raw):
    try: return float((raw or "").replace(",", "").replace("%", "").strip())
    except ValueError: return None


def tb_records(page, page_hash, retrieved_at):
    parser = TableParser()
    parser.feed(page.decode("utf-8", "replace"))
    if len(parser.tables) != 1 or len(parser.tables[0]) < 60:
        raise RuntimeError("Expected CDC TB reporting areas HTML table was not found")
    table = parser.tables[0]
    records = []
    for row_num, row in enumerate(table[2:], start=3):
        if len(row) < 8 or not row[0].strip():
            continue
        name = row[0].strip()
        if name.startswith("United States"):
            geo_level, geoid, fips, code = "country", "US", None, None
            display = "United States (CDC national total)"
            boundary = "CDC national total excludes American Samoa, FSM, Guam, Marshall Islands, Northern Mariana Islands, Puerto Rico, Palau, and U.S. Virgin Islands; New York City included"
        elif name == "New York City":
            geo_level, geoid, fips, code = "city_reporting_area", "CDC_TB:New York City", "36", "NY"
            display = name
            boundary = "separate CDC reporting area; no county-resolved values in this table"
        elif name == "New York State2":
            geo_level, geoid, fips, code = "state_reporting_area", "CDC_TB:New_York_State_excluding_NYC", "36", "NY"
            display = "New York State (excluding New York City)"
            boundary = "source footnote explicitly excludes New York City; not the complete New York State aggregate"
        elif name in STATE_FIPS:
            geo_level, geoid, fips = "state", STATE_FIPS[name], STATE_FIPS[name]
            code = next((abbr for abbr, val in STATE_ABBR_FIPS.items() if val == fips), None)
            display = name
            boundary = "state reporting area"
        else:
            geo_level, geoid, fips, code = "other_cdc_reporting_area", "CDC_TB:" + slug(name), None, None
            display = name
            boundary = "territory or freely associated state; excluded from CDC U.S. national total per footnote"
        case_2023, case_2024 = int_text(row[1]), int_text(row[2])
        rate_2023, rate_2024 = float_text(row[4]), float_text(row[5])
        pop_2024 = int_text(row[7])
        for year, cases, rate in [(2023, case_2023, rate_2023), (2024, case_2024, rate_2024)]:
            for metric, value, unit, kind in [
                ("tuberculosis_disease_reported_cases_count", cases, "reported_cases", "reported_case_count"),
                ("tuberculosis_disease_reported_incidence_rate", rate, "reported_cases_per_100000_population", "published_crude_incidence_rate"),
            ]:
                records.append({
                    "metric_id": metric, "metric_label": "Reported tuberculosis disease cases" if kind == "reported_case_count" else "Reported TB disease incidence rate",
                    "geography_level": geo_level, "geoid": geoid, "source_geoid": fips,
                    "geography_name": display, "state_fips": fips, "state_code": code,
                    "boundary_vintage": None, "geography_compatibility": boundary,
                    "period": str(year), "period_type": "calendar_year",
                    "value": value, "value_status": "numeric" if value is not None else "missing_source_cell",
                    "unit": unit, "measure_type": kind, "estimate_status": "published_surveillance",
                    "preliminary": False, "age_group": "all ages", "sex": "all sexes",
                    "race_ethnicity": "all races/ethnicities",
                    "source_category": "TB disease; latent TB infection excluded",
                    "denominator_population": pop_2024 if year == 2024 else None,
                    "denominator_definition": "U.S. Census Bureau official resident population estimates; exact July 1 2024 population shown by CDC for 2024 only" if year == 2024 else "U.S. Census Bureau official resident population estimate for observation year; exact 2023 cell not published in this table",
                    "source_population_scope": "Incident TB disease cases verified under CDC/CSTE surveillance case definition and countable for morbidity statistics; report by reporting-area residence at evaluation start",
                    "source_reporting_cutoff": "2025-07-10",
                    "source_url": URLS["cdc-tb-reporting-areas-2023-2024.html"],
                    "documentation_url": URLS["cdc-tb-technical-notes.html"],
                    "source_file": "raw/" + TB_PAGE,
                    "source_sha256": page_hash,
                    "source_row": row_num, "source_row_name": name,
                    "source_value_text": row[1 if year == 2023 and kind == "reported_case_count" else 2 if kind == "reported_case_count" else 4 if year == 2023 else 5],
                    "source_suppression_code": None,
                    "source_missingness_note": "Source HTML reports numeric cases and rates for each listed reporting area; this normalized table preserves blanks as null if present.",
                    "retrieved_at": retrieved_at, "production_ready": False,
                    "comparability_note": "Published crude rate per 100,000; 2024 source population field is July 1 2024, while 2023 exact denominator is not printed. New York State excludes the separately reported New York City. No county-level routine incidence values in this table.",
                })
    return records


STATE_ABBR_FIPS = {
    "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08","CT":"09","DE":"10","DC":"11","FL":"12","GA":"13","HI":"15","ID":"16","IL":"17","IN":"18","IA":"19","KS":"20","KY":"21","LA":"22","ME":"23","MD":"24","MA":"25","MI":"26","MN":"27","MS":"28","MO":"29","MT":"30","NE":"31","NV":"32","NH":"33","NJ":"34","NM":"35","NY":"36","NC":"37","ND":"38","OH":"39","OK":"40","OR":"41","PA":"42","RI":"44","SC":"45","SD":"46","TN":"47","TX":"48","UT":"49","VT":"50","VA":"51","WA":"53","WV":"54","WI":"55","WY":"56"
}
STATE_NAME_ABBR = {
    "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE","District of Columbia":"DC","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York State2":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY"
}


def enrich_sti_records(records):
    for item in records:
        code = item.get("state_fips")
        if not code:
            continue
        item["state_code"] = next((abbr for abbr, fips in STATE_ABBR_FIPS.items() if fips == code), item.get("state_code"))
    return records


def dedupe(records):
    by_key = {}
    conflicts = []
    for record in records:
        key = (record["metric_id"], record["period"], record["geography_level"],
               record["geoid"], record.get("sex"), record.get("subgroup"), record.get("source_row_name"))
        if key not in by_key:
            by_key[key] = record
            continue
        prior = by_key[key]
        prior.setdefault("duplicate_source_refs", []).append({
            "source_file": record.get("source_file"), "source_member": record.get("source_member"),
            "source_row": record.get("source_row"), "value": record.get("value")})
        if prior.get("value") != record.get("value"):
            conflicts.append({"key": list(key), "first_value": prior.get("value"), "duplicate_value": record.get("value")})
    if conflicts:
        raise RuntimeError("Conflicting duplicate source rows: " + json.dumps(conflicts[:5]))
    return list(by_key.values())


def write_records(records):
    OUT.mkdir(exist_ok=True)
    records.sort(key=lambda r: (r["metric_id"], r["period"], r["geography_level"], r["geoid"] or "", r.get("sex", ""), r.get("subgroup", "")))
    for row in records:
        stable = "|".join(str(row.get(key) or "") for key in (
            "metric_id", "period", "geography_level", "geoid", "sex", "subgroup", "source_row_name"))
        row["observation_id"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    (OUT / "observations.json").write_text(json.dumps({"schema_version": 1, "as_of": "2026-10-05", "observations": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = sorted({key for row in records for key, value in row.items() if not isinstance(value, (dict, list))})
    with (OUT / "observations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    summary = {}
    for row in records:
        item = summary.setdefault(row["metric_id"], {"metric_id": row["metric_id"], "periods": set(), "numeric_observations": 0, "missing_or_suppressed": 0, "geographies": {}, "units": set(), "source_urls": set()})
        item["periods"].add(row["period"])
        item["units"].add(row["unit"])
        item["source_urls"].add(row["source_url"])
        item["numeric_observations" if row["value_status"] == "numeric" else "missing_or_suppressed"] += 1
        item["geographies"].setdefault(row["geography_level"], set()).add(row["geoid"])
    metrics = []
    for item in summary.values():
        metrics.append({**item,
            "periods": sorted(item["periods"]), "units": sorted(item["units"]),
            "source_urls": sorted(item["source_urls"]),
            "geographies": {level: sorted(x for x in ids if x is not None) for level, ids in item["geographies"].items()},
            "county_numeric_rows": 0,
            "state_numeric_rows": sum(r["value_status"] == "numeric" and r["geography_level"] in ("state", "state_reporting_area") for r in records if r["metric_id"] == item["metric_id"]),
            "country_numeric_rows": sum(r["value_status"] == "numeric" and r["geography_level"] == "country" for r in records if r["metric_id"] == item["metric_id"]),
            "finest_collected": ("city_reporting_area_and_state" if "city_reporting_area" in item["geographies"] else "state" if any(x in item["geographies"] for x in ("state", "state_reporting_area")) else "national"),
            "definition": "; ".join(sorted({r["metric_label"] for r in records if r["metric_id"] == item["metric_id"]})),
            "reason_missing": "No county observations in the selected source. CDC 2024 provisional STI measures are national-only; TB report table is by state/NYC and other CDC reporting area. Source blanks remain null and are not treated as zero.",
        })
    coverage = {
        "as_of": "2026-10-05", "bundle": "additional-surveillance", "records": len(records),
        "numeric": sum(r["value_status"] == "numeric" for r in records),
        "missing_or_suppressed": sum(r["value_status"] != "numeric" for r in records),
        "metrics": len(metrics), "no_subcounty_values": True,
        "geographic_coverage": {
            "block_group": [], "tract": [], "county": [],
            "sti": {"country": ["US"], "state": [], "note": "CDC 2024 provisional STI data ZIP provides national spreadsheets only; CDC deferred state/geographic publication pending NNDSS reconciliation."},
            "tb": {"state_fips_observed": sorted({r["state_fips"] for r in records if r.get("state_fips") and r["geography_level"] == "state"}),
                   "special_state_reporting_areas": sorted({r["geoid"] for r in records if r["geography_level"] == "state_reporting_area"}),
                   "city_reporting_areas": sorted({r["geoid"] for r in records if r["geography_level"] == "city_reporting_area"}),
                   "other_reporting_areas": sorted({r["geography_name"] for r in records if r["geography_level"] == "other_cdc_reporting_area"}),
                   "country": ["US"], "note": "52 U.S. reporting areas (50 states, DC, NYC; New York State excludes NYC) plus 8 territories/freely associated states; annual table gives no county-specific routine case rates."},
        },
        "metric_coverage": sorted(metrics, key=lambda x: x["metric_id"]),
        "source_limitations": [
            "STI 2024 values are provisional as of 2025-08-14; 2024 state-level counts and rates were withheld while CDC migrates NNDSS to 1CDP.",
            "National STI case totals include non-U.S. residents and exclude U.S. territories; congenital syphilis rates use 2023 live births, other rates use 2024 population denominators.",
            "TB reporting-area table was updated through 2025-07-10. The 2020 RVCT revision was first fully used across jurisdictions in 2023; CDC notes possible minor data-quality/completeness fluctuations.",
            "New York City is reported separately and excluded from the New York State reporting-area row. FIPS is not assigned to the city aggregate.",
            "The source publishes annual state/NYC values, not county incidence rates. The separate recent-transmission county map is a specific genotyped-case-derived measure, not total county TB incidence.",
        ],
    }
    (OUT / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return coverage


def update_source_register(receipts):
    path = ROOT / "source-register.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"raw_sources": [], "methodology_sources": []}
    sources = data.setdefault("raw_sources", [])
    known = {item.get("source_id") for item in sources}
    definitions = [
        (STI_PAGE, "CDC", "raw_statistical_data_or_primary_metadata", "CDC Sexually Transmitted Infections Surveillance 2024 (Provisional)", "2020-2024 national trends; data provisional as of 2025-08-14", "U.S. national only, includes DC; excludes territories; national counts include non-U.S. residents", "2024 state/county output withheld pending NNDSS reconciliation; recheck after CDC finalizes data in 2026"),
        (STI_ZIP, "CDC", "public_download", "CDC 2024 STI surveillance provisional data files ZIP", "2015-2024; 2024 provisional", "National only, U.S. including DC and excluding territories", "Recheck for final 2024 release and geographies; do not assign national values to states/counties"),
        (TB_PAGE, "CDC / Division of Tuberculosis Elimination", "raw_statistical_data_or_primary_metadata", "Reported Tuberculosis in the United States, 2024; reporting-area HTML table", "2023-2024", "50 states, DC, separately reported NYC, territories and freely associated states; NY state row excludes NYC", "Investigate official county TB source routes; keep CDC county recent-transmission counts as a different measure and preserve unavailable geographies"),
        (TB_NOTES, "CDC / Division of Tuberculosis Elimination", "primary_methodology", "Reported Tuberculosis in the United States, 2024 Technical Notes", "1993-2024 report; rate denominators 2020-2024 from Census resident-population estimates", "Reporting-area based", "Retain RVCT definition and 2023 form transition in future series"),
        (HEP_PAGE, "CDC / Division of Viral Hepatitis", "primary_methodology", "HepTracker Viral Hepatitis Surveillance Data Dashboard", "2024 case data marked provisional; source update says refreshed 2026-01-17", "Public dashboard includes national/state time trends; no verified direct public county export collected this session", "Inspect documented dashboard export after fall-2026 finalization; keep acute/chronic NNDSS cases separate from seroprevalence and mortality"),
    ]
    by_url = {item.get("url"): item for item in sources}
    for url, owner, role, release, period, geography, next_step in definitions:
        name = next((n for n, u in URLS.items() if u == url), None)
        rec = receipts.get(name) if name else None
        if not rec:
            continue
        entry = {
            "source_id": name, "publisher": owner, "role": role,
            "accessed_at": rec.get("finished_at"), "url": url,
            "http_status": rec.get("http_status"), "access_outcome": rec.get("status"),
            "sha256": rec.get("sha256"), "bytes": rec.get("bytes"),
            "path": rec.get("path"), "method": "GET", "params": {}, "payload": None,
            "content_type": rec.get("content_type"), "last_modified": rec.get("last_modified"),
            "etag": rec.get("etag"), "source_release": release,
            "observation_period": period, "population_universe": geography,
            "geography": geography, "next_collection_step": next_step,
        }
        existing = by_url.get(url)
        if existing:
            existing.update(entry)
        else:
            sources.append(entry)
            by_url[url] = entry
            known.add(name)
    nci_checks = [
        ("nci-incidence-all_sites-state-2026-10-05-live-audit.csv", "state", "NCI/CDC State Cancer Profiles current all-sites incidence CSV export"),
        ("nci-incidence-all_sites-county-2026-10-05-live-audit.csv", "county", "NCI/CDC State Cancer Profiles current all-sites incidence CSV export"),
    ]
    for name, level, release in nci_checks:
        rec = receipts.get(name)
        if not rec:
            continue
        url = rec.get("final_url") or rec.get("requested_url")
        params = rec.get("params") or {}
        existing = by_url.get(url)
        entry = {
            "source_id": name, "publisher": "NCI / CDC", "role": "raw_statistical_data_current_release_check",
            "accessed_at": rec.get("finished_at"), "url": url,
            "http_status": rec.get("http_status"), "access_outcome": rec.get("status"),
            "sha256": rec.get("sha256"), "bytes": rec.get("bytes"), "path": rec.get("path"),
            "method": "GET", "params": params, "payload": None, "content_type": rec.get("content_type"),
            "source_release": release, "observation_period": "2019-2023",
            "population_universe": "All Races (includes Hispanic), Both Sexes, All Ages",
            "geography": level + " export; output includes source suppression and source-provided fields",
            "next_collection_step": "Use this live release selector for subsequent site-specific exports; keep original five-year period, average annual count, rate, confidence intervals, sex-specific breast/prostate populations, and source FIPS.",
        }
        if existing:
            existing.update(entry)
        else:
            sources.append(entry)
            by_url[url] = entry
    methods = data.setdefault("methodology_sources", [])
    method_defs = [
        ("https://www.cdc.gov/sti-statistics/annual/index.html", "CDC STI 2024 provisional notes: national-only pending NNDSS migration; case/rate universe, provisional date, and denominator notes", "CDC"),
        ("https://www.cdc.gov/tb-surveillance-report-2024/executive-commentary/technical-notes.html", "CDC TB 2024 technical notes: case definition, RVCT counting, reporting areas, population denominators and 2023 RVCT transition", "CDC"),
        ("https://www.cdc.gov/hepatitis/php/data-research/heptracker/index.html", "CDC HepTracker sources and footnotes: NNDSS confirmed reports; 2024 provisional date; public Power BI dashboard", "CDC"),
        ("https://statecancerprofiles.cancer.gov/help/about/incidence_rates.html", "NCI/CDC State Cancer Profiles incidence table: registry source, NCI-modified Census denominators, SEER*Stat rate calculation", "NCI / CDC"),
        ("https://statecancerprofiles.cancer.gov/help/about/death_rates.html", "NCI/CDC State Cancer Profiles death table: NVSS mortality source, NCI-modified Census denominators, SEER*Stat rate calculation and confidence intervals", "NCI / CDC"),
        ("https://www.cdc.gov/united-states-cancer-statistics/public-use/documentation.html", "Current 2001-2023 U.S. Cancer Statistics public-use data standards and dictionary index; geography coverage and dictionary links", "CDC / NCI"),
        ("https://www.cdc.gov/united-states-cancer-statistics/public-use/pdf/uscs-public-use-database-technical-documentation-2001-2023-final-508.pdf", "2025 submission U.S. Cancer Statistics public-use technical documentation/data dictionary: ICD-O-3 site codes, population coverage, age adjustment, and fewer-than-16 suppression rule", "CDC / NCI"),
        ("https://www.cdc.gov/united-states-cancer-statistics/technical-notes/population-denominator-data-sources.html", "2026 U.S. Cancer Statistics denominator release notes: bridged-race incidence denominators through 2023 and single-race death denominators 2018-2024", "CDC / NCI"),
        ("https://www.cdc.gov/united-states-cancer-statistics/technical-notes/incidence-death-rates.html", "2026 U.S. Cancer Statistics crude/age-adjusted rate definitions and 2000 U.S. standard population", "CDC / NCI"),
    ]
    old_urls = {item.get("url") for item in methods}
    for url, title, publisher in method_defs:
        if url not in old_urls:
            methods.append({"url": url, "title": title, "publisher": publisher, "accessed_at": "2026-10-05", "role": "primary_methodology", "access_outcome": "opened_live_official_documentation"})
    data["refreshed_at"] = now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize():
    archive, zip_receipt = require_source(STI_ZIP)
    sti_page, sti_page_receipt = require_source(STI_PAGE)
    tb_page, tb_receipt = require_source(TB_PAGE)
    _, tb_notes_receipt = require_source(TB_NOTES)
    hep_page, hep_receipt = require_source(HEP_PAGE)
    sti_page_text = sti_page.decode("utf-8", "replace")
    if "Why are only national data available?" not in sti_page_text or "provisional" not in sti_page_text.lower():
        raise RuntimeError("CDC STI page no longer matches the documented provisional national-only release")
    if "DVH_HepTracker_Final_Jan26" not in hep_page.decode("utf-8", "replace"):
        raise RuntimeError("HepTracker iframe/version identifier changed; review before normalizing")
    sti = sti_member_records(archive, zip_receipt["sha256"], zip_receipt["finished_at"])
    tb = tb_records(tb_page, tb_receipt["sha256"], tb_receipt["finished_at"])
    coverage = write_records(dedupe(enrich_sti_records(sti) + tb))
    receipts = latest_receipts()
    update_source_register(receipts)
    (OUT / "source-checks.json").write_text(json.dumps({
        "as_of": "2026-10-05", "sources": [
            {"source_id": n, "url": URLS[n], "http_status": receipts[n].get("http_status"),
             "status": receipts[n].get("status"), "bytes": receipts[n].get("bytes"),
             "sha256": receipts[n].get("sha256"), "path": receipts[n].get("path"),
             "retrieved_at": receipts[n].get("finished_at")}
            for n in (STI_PAGE, STI_ZIP, TB_PAGE, TB_NOTES, HEP_PAGE)
        ],
        "hepatitis_route_finding": "Official CDC page was downloaded. It embeds a public Power BI HepTracker viewer (DVH_HepTracker_Final_Jan26), reports NNDSS confirmed case surveillance, and marks 2024 case data provisional with a stated Jan 17 2026 update. No documented machine-readable direct export was verified in this session; do not infer additional rows from the viewer.",
        "coverage_counts": {"observations": coverage["records"], "numeric": coverage["numeric"], "metrics": coverage["metrics"]},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"observations": coverage["records"], "numeric": coverage["numeric"], "metrics": coverage["metrics"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["fetch", "normalize"])
    args = parser.parse_args()
    if args.stage == "fetch": fetch_all()
    else: normalize()
