#!/usr/bin/env python3
"""Build the deterministic 81-row field contract from the preserved DOCX catalog."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree


HERE = Path(__file__).resolve().parent
DOCX = HERE.parent / "source" / "us_map_statistics_catalog.docx"
OUTPUT = HERE / "field-contract.json"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

BLOCKED_ACCESS = {
    "03.07", *{f"05.{number:02d}" for number in range(1, 13)},
    *{f"06.{number:02d}" for number in range(1, 7)},
}
DEFINITION_REQUIRED = {"03.08", "04.08", "07.02", "07.05", "08.04", "08.09", "09.05"}
SOURCE_REQUIRED = {"05.13", "07.06", "08.01", "08.02", "08.07", "08.08"}
LICENSE_REQUIRED = {"07.07", "08.03", "08.06"}

CENSUS_GROUP_LAST_VARIABLE = {
    "B01001": 49,
    "B03002": 21,
    "B05001": 6,
    "B05002": 27,
    "B05005": 21,
    "B05006": 178,
    "B25070": 11,
}

HOUSING_STOCK_VARIABLES = [
    "B25001_001E", "B25001_001M",
    "B25002_001E", "B25002_001M", "B25002_002E", "B25002_002M",
    "B25002_003E", "B25002_003M",
    "B25003_001E", "B25003_001M", "B25003_002E", "B25003_002M",
    "B25003_003E", "B25003_003M",
]


def census_group_variables(group: str) -> list[str]:
    """Materialize the frozen 2024 ACS E/M IDs used by the executable ledger."""
    return [f"{group}_{number:03d}{suffix}"
            for number in range(1, CENSUS_GROUP_LAST_VARIABLE[group] + 1)
            for suffix in ("E", "M")]


def census_range(group: str, start: int, end: int, suffix: str) -> list[str]:
    return [f"{group}_{number:03d}{suffix}" for number in range(start, end + 1)]


def census(group: str, variables: list[str], derivation: str, geographies: list[str] | None = None) -> dict:
    return {
        "source_release": "2024-acs-acs5",
        "acquisition_mode": "api",
        "source_selector": f"https://api.census.gov/data/2024/acs/acs5/groups/{group}.json",
        "source_variables": variables,
        "derivation": derivation,
        "target_geographies": geographies or ["state", "county", "place", "tract"],
        "rate_limit_profile": "census_acs",
        "license_status": "public_official",
    }


def bls_laus_variables() -> list[str]:
    """Return the exact state/county series templates for LAUS measures 03–06."""
    measures = ("03", "04", "05", "06")
    return [f"LASST{{state_fips_2}}{'0' * 11}{measure}" for measure in measures] + [
        f"LAUCN{{county_fips_5}}{'0' * 8}{measure}" for measure in measures
    ]


MAPPINGS = {
    "01.01": census("B01003", ["B01003_001E", "B01003_001M"], "identity estimate and MOE"),
    "01.02": census("B01001+B01002", census_group_variables("B01001") + ["B01002_001E", "B01002_001M"], "emit every labeled age band and median age"),
    "01.03": census("B01001", census_group_variables("B01001"), "emit labeled sex counts and shares using B01001_001E"),
    "01.04": census("B03002", census_group_variables("B03002"), "emit labeled race and Hispanic-origin counts and shares"),
    "01.05": census("B05002", census_group_variables("B05002"), "emit native/foreign-born counts and shares"),
    "01.06": census("B05006", census_group_variables("B05006"), "emit every published birthplace category"),
    "01.07": census("B05001", census_group_variables("B05001"), "emit citizenship-status counts and shares"),
    "01.08": census("B05005", census_group_variables("B05005"), "emit entry-period counts"),
    "02.01": census("B19013", ["B19013_001E", "B19013_001M"], "identity estimate and MOE"),
    "02.02": census("B19301", ["B19301_001E", "B19301_001M"], "identity estimate and MOE"),
    "02.03": census("B25064", ["B25064_001E", "B25064_001M"], "identity estimate and MOE"),
    "02.04": census("B25077", ["B25077_001E", "B25077_001M"], "identity estimate and MOE"),
    "02.05": census("B25088", ["B25088_001E", "B25088_001M"], "identity estimate and MOE"),
    "02.06": census("B25070", census_group_variables("B25070"), "emit distribution; derive 30%+ share excluding not-computed"),
    "02.07": census(
        "B25001+B25002+B25003", HOUSING_STOCK_VARIABLES,
        "owner-, renter-, and vacant-unit counts over all housing units; derived shares use B25001_001E",
    ),
    "02.08": census("B17001", ["B17001_001E", "B17001_001M", "B17001_002E", "B17001_002M"], "below-poverty count divided by status-determined total"),
    "02.09": census("B19001", ["B19001_001E", "B19001_001M", "B19001_017E", "B19001_017M"], "$200k+ households divided by total households"),
    "03.01": census("B15003", ["B15003_001E", "B15003_001M", "B15003_022E", "B15003_022M"], "bachelor count and share age 25+"),
    "03.02": census("B15003", ["B15003_001E", "B15003_001M", "B15003_023E", "B15003_023M"], "master count and share age 25+"),
    "03.03": census("B15003", ["B15003_001E", "B15003_001M", "B15003_025E", "B15003_025M"], "doctorate count and share age 25+"),
    "03.04": census("B15003", ["B15003_001E", "B15003_001M"] + census_range("B15003", 17, 25, "E") + census_range("B15003", 17, 25, "M"), "sum high-school-or-higher bins; combine MOE by documented RSS rule"),
    "03.05": census("B15003", ["B15003_001E", "B15003_001M"] + census_range("B15003", 2, 16, "E") + census_range("B15003", 2, 16, "M"), "sum no-diploma bins; combine MOE by documented RSS rule"),
    "03.09": census("B08301", ["B08301_001E", "B08301_001M", "B08301_021E", "B08301_021M"], "worked-at-home count divided by workers 16+"),
    "02.10": {
        "source_release": "BEA-SARPP-2024", "acquisition_mode": "bulk_zip",
        "source_selector": "https://apps.bea.gov/regional/zip/SARPP.zip",
        "source_variables": ["LineCode=1"], "derivation": "all-items RPP identity",
        "target_geographies": ["state", "metro"], "rate_limit_profile": "bea_rpp",
        "license_status": "public_official",
    },
    "03.06": {
        "source_release": "BLS-LAUS-latest-final-annual", "acquisition_mode": "api_post",
        "source_selector": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "source_variables": bls_laus_variables(),
        "derivation": "published unemployment rate plus supporting counts",
        "target_geographies": ["state", "county"], "rate_limit_profile": "bls_laus",
        "license_status": "public_official",
    },
    **{
        field_id: {
            "source_release": "FBI-CDE-latest-complete-year", "acquisition_mode": "api",
            "source_selector": "https://cde.ucr.cjis.gov/LATEST/summarized/state/{state}/{offense}",
            "source_variables": [offense], "derivation": "monthly and annual count/rate with coverage",
            "target_geographies": ["state"], "rate_limit_profile": "fbi_cde",
            "license_status": "public_official",
        }
        for field_id, offense in {
            "04.01": "homicide", "04.02": "violent-crime", "04.03": "robbery",
            "04.04": "aggravated-assault", "04.05": "burglary",
            "04.06": "motor-vehicle-theft", "04.07": "rape",
        }.items()
    },
    "04.09": {
        "source_release": "FBI-CDE-latest-five-complete-years", "acquisition_mode": "derived",
        "source_selector": "artifacts:04.01-04.07", "source_variables": ["annual_total", "year_over_year_change"],
        "derivation": "derive from seven offense families without extra transport",
        "target_geographies": ["state"], "rate_limit_profile": "fbi_cde",
        "license_status": "public_official",
    },
    **{
        field_id: {
            "source_release": "CDC-PLACES-swc5-untb-current", "acquisition_mode": "socrata_api",
            "source_selector": "https://data.cdc.gov/resource/swc5-untb.json",
            "source_variables": [measure, "Age-adjusted prevalence", "confidence_limit_low", "confidence_limit_high"],
            "derivation": "identity model-based estimate with interval",
            "target_geographies": ["county"], "rate_limit_profile": "cdc_places",
            "license_status": "public_official",
        }
        for field_id, measure in {"05.14": "OBESITY", "05.15": "DIABETES", "05.16": "LPA"}.items()
    },
    **{
        field_id: {
            "source_release": "IRS-SOI-ZIP-2022", "acquisition_mode": "bulk_csv",
            "source_selector": "https://www.irs.gov/pub/irs-soi/22zpallagi.csv",
            "source_variables": variables, "derivation": "identity by ZIP and income-size row",
            "target_geographies": ["zip"], "rate_limit_profile": "irs_soi",
            "license_status": "public_official",
        }
        for field_id, variables in {
            "07.01": ["N00100", "A00100"], "07.03": ["N01000", "A01000"],
            "07.04": ["N00600", "A00600"],
        }.items()
    },
    "08.05": {
        "source_release": "EIA-electricity-retail-sales-latest-annual", "acquisition_mode": "paginated_api",
        "source_selector": "https://api.eia.gov/v2/electricity/retail-sales/data/",
        "source_variables": ["price", "stateid", "sectorid"], "derivation": "identity retail price",
        "target_geographies": ["state", "utility", "sector"], "rate_limit_profile": "eia",
        "license_status": "public_official",
    },
    **{
        field_id: {
            "source_release": "USDA-FEA-2025", "acquisition_mode": "bulk_zip",
            "source_selector": "https://www.ers.usda.gov/media/5570/food-environment-atlas-csv-files.zip?v=99629",
            "source_variables": variables, "derivation": "identity with variable-list unit and year",
            "target_geographies": ["county"], "rate_limit_profile": "usda_fea",
            "license_status": "public_official",
        }
        for field_id, variables in {
            "09.01": ["FFRPTH20"], "09.02": ["LACCESS_POP19", "PCT_LACCESS_POP19"],
            "09.03": ["FMRKTPTH18"], "09.04": ["RECFACPTH20"],
        }.items()
    },
    **{
        field_id: {
            "source_release": "EPA-AirData-latest-complete-annual", "acquisition_mode": "bulk_zip",
            "source_selector": "https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_{year}.zip",
            "source_variables": [parameter], "derivation": "identity monitor statistics; county aggregate remains labeled",
            "target_geographies": ["monitor", "county"], "rate_limit_profile": "epa_airdata",
            "license_status": "public_official",
        }
        for field_id, parameter in {"09.06": "88101", "09.07": "44201"}.items()
    },
}


def cell_text(cell: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in cell.findall(".//w:t", NS)).strip()


def catalog_rows() -> list[dict]:
    with zipfile.ZipFile(DOCX) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    rows = []
    tables = root.findall(".//w:tbl", NS)[:9]
    for table_number, table in enumerate(tables, start=1):
        raw_rows = table.findall("./w:tr", NS)[1:]
        for row_number, row in enumerate(raw_rows, start=1):
            values = [cell_text(cell) for cell in row.findall("./w:tc", NS)]
            if len(values) != 4:
                raise ValueError(f"unexpected catalog row shape: table {table_number}, row {row_number}")
            rows.append({
                "field_id": f"{table_number:02d}.{row_number:02d}",
                "catalog_label": values[0],
                "catalog_source": values[1],
                "catalog_geography": values[2],
                "catalog_note": values[3],
            })
    return rows


def state_for(field_id: str) -> str:
    if field_id in BLOCKED_ACCESS:
        return "blocked_access"
    if field_id in DEFINITION_REQUIRED:
        return "definition_required"
    if field_id in SOURCE_REQUIRED:
        return "source_required"
    if field_id in LICENSE_REQUIRED:
        return "license_required"
    return "run_now"


def build() -> list[dict]:
    contract = []
    for row in catalog_rows():
        field_id = row["field_id"]
        state = state_for(field_id)
        row.update({
            "planned_state": state,
            "unavailable_geography": "record_not_available",
            "unit": "source_defined",
        })
        if state == "run_now":
            row.update(MAPPINGS[field_id])
        else:
            row.update({
                "source_release": "unselected",
                "acquisition_mode": "disabled",
                "source_selector": "",
                "source_variables": [],
                "derivation": f"disabled:{state}",
                "target_geographies": [row["catalog_geography"]],
                "rate_limit_profile": "disabled",
                "license_status": "not_approved" if state == "license_required" else "unresolved",
            })
        contract.append(row)
    if len(contract) != 81 or len({row["field_id"] for row in contract}) != 81:
        raise ValueError("catalog contract must contain exactly 81 unique rows")
    if set(MAPPINGS) != {row["field_id"] for row in contract if row["planned_state"] == "run_now"}:
        raise ValueError("run_now mappings do not match the ledger")
    return contract


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} with 81 rows")


if __name__ == "__main__":
    main()
