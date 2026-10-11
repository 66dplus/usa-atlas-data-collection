#!/usr/bin/env python3
"""Build the versioned map consumer definitions without changing ingestion pins."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "full/map-metric-definitions.json"
EVIDENCE = ROOT / "research/2026-10-11/map-metrics"
MOE_DOC = "https://www.census.gov/content/dam/Census/library/publications/2020/acs/acs_general_handbook_2020.pdf"


def build():
    official = json.loads((EVIDENCE / "census-variable-metadata.json").read_text())["groups"]
    coverage = {r["field_id"]: r for r in json.loads((ROOT / "research/2026-09-29/coverage-audit/coverage.json").read_text())["fields"]}
    definitions = []

    def acs(metric_id, parent, label, group, numerator, denominator=(), unit="%", operation="share", notes=(), assertions=None):
        numerator = {v if isinstance(v, str) else v[0]: 1 if isinstance(v, str) else v[1] for v in numerator}
        denominator = {v if isinstance(v, str) else v[0]: 1 if isinstance(v, str) else v[1] for v in denominator}
        first = next(iter(numerator))
        table_coverage = coverage[parent]["native_coverage_by_table"].get("acs-summary-" + group, {})
        if group == "B17021":
            table_coverage = coverage[parent]["native_coverage_by_table"]["extension:B17021"]
        definitions.append({"metric_id": metric_id, "version": 1, "catalog_field_id": parent,
            "label": label, "source": "census_acs", "source_releases": ["2024-acs-acs5"],
            "period": "2024", "reference_period": "2020–2024", "period_type": "five_year_period_estimate",
            "universe": official[group]["variables"][first]["universe"],
            "raw_component_unit": raw_unit(group), "display_unit": unit,
            "accepted_input_units": ["source_defined", raw_unit(group)],
            "native_geographies": sorted(table_coverage),
            "geography_evidence": "research/2026-09-29/coverage-audit/coverage.json; table-specific source collection, not numeric coverage",
            "formula": {"operation": operation, "numerator": numerator, "denominator": denominator,
                        "scale": 100 if operation == "share" else 1},
            "label_assertions": assertions or {},
            "source_urls": [official[group]["url"], "https://www.census.gov/programs-surveys/acs/guidance/estimates.html", MOE_DOC],
            "uncertainty": "Published ACS 90% MOEs; component sums and ratios use documented approximations. Missing/sentinel MOEs remain unknown.",
            "state_calculation": "Use native components for the state; apply this formula once.",
            "nation_calculation": "Use native nation components from the same ACS five-year release; apply this formula once.",
            "limitations": ["ACS 2024 means the 2020–2024 five-year period, not a 2024 annual observation.",
                             "Do not average county medians or percentages; no geography is downscaled.", *notes]})

    def bins(group, start, end):
        return [f"{group}_{i:03d}E" for i in range(start, end + 1)]

    acs("population", "01.01", "Population", "B01003", ["B01003_001E"], unit="people", operation="identity")
    # Broad categorical fields retain exact source-series alternatives. Selecting
    # a category/age band belongs to product configuration, never to lexical order.
    acs("median-age", "01.02", "Median age", "B01002", ["B01002_001E"], unit="years", operation="identity")
    acs("female-population-share", "01.03", "Female population share", "B01001", ["B01001_026E"], ["B01001_001E"])
    acs("male-population-share", "01.03", "Male population share", "B01001", ["B01001_002E"], ["B01001_001E"])
    acs("hispanic-origin-share", "01.04", "Hispanic or Latino population share", "B03002", ["B03002_012E"], ["B03002_001E"],
        notes=["Hispanic origin can be of any race; a full race/origin breakdown needs an explicitly selected category."])
    acs("foreign-born-share", "01.05", "Foreign-born population share", "B05002", ["B05002_013E"], ["B05002_001E"], assertions={"B05002_013E": "Foreign-born:"})
    acs("foreign-born-count", "01.05", "Foreign-born population", "B05002", ["B05002_013E"], unit="people", operation="identity")
    acs("foreign-born-birthplace-total", "01.06", "Foreign-born population in birthplace table", "B05006", ["B05006_001E"], unit="people", operation="identity",
        notes=["This total is not a selected country or region; a country/region selector is still required."])
    acs("us-citizen-share", "01.07", "U.S. citizen population share", "B05001", bins("B05001", 2, 5), ["B05001_001E"])
    acs("entry-period-population-total", "01.08", "Population born outside the United States", "B05005", ["B05005_001E"], unit="people", operation="identity",
        notes=["Includes native and foreign-born persons born outside the United States. Select both entry period and nativity explicitly."])
    for parent, metric_id, group, label, unit in [
        ("02.01", "median-household-income", "B19013", "Median household income", "2024 USD/year"),
        ("02.02", "per-capita-income", "B19301", "Per-capita income", "2024 USD/year"),
        ("02.03", "median-gross-rent", "B25064", "Median gross rent", "USD/month"),
        ("02.04", "median-home-value", "B25077", "Median home value", "USD"),
        ("02.05", "median-selected-monthly-owner-costs", "B25088", "Median selected monthly owner costs · all owners", "USD/month"),
    ]:
        acs(metric_id, parent, label, group, [group + "_001E"], unit=unit, operation="identity")
    acs("median-owner-costs-with-mortgage", "02.05", "Median selected monthly owner costs · with mortgage", "B25088", ["B25088_002E"], unit="USD/month", operation="identity",
        assertions={"B25088_002E": "with a mortgage"})
    acs("rent-burden-30-plus-share", "02.06", "Gross rent at least 30% of household income", "B25070", bins("B25070", 7, 10), bins("B25070", 2, 10),
        notes=["Denominator excludes not-computed income ratios. Sum of bins 002–010 equals total 001 minus not-computed 011; neither total nor bin 007 alone is rent burden.",
               "MOEs for numerator and denominator sums are approximate RSS values, then the subset proportion formula is applied."],
        assertions={"B25070_007E": "30.0 to 34.9 percent", "B25070_010E": "50.0 percent or more"})
    acs("owner-renter-ratio", "02.07", "Owner-occupied units per renter-occupied unit", "B25003", ["B25003_002E"], ["B25003_003E"], unit="ratio", operation="ratio")
    acs("owner-occupied-share", "02.07", "Owner-occupied share of occupied housing units", "B25003", ["B25003_002E"], ["B25003_002E", "B25003_003E"],
        notes=["Owner plus renter occupied units form the total occupied-unit denominator; vacant units are excluded."])
    acs("renter-occupied-share", "02.07", "Renter-occupied share of occupied housing units", "B25003", ["B25003_003E"], ["B25003_002E", "B25003_003E"],
        notes=["Owner plus renter occupied units form the total occupied-unit denominator; vacant units are excluded."])
    acs("poverty-share", "02.08", "Population below poverty level", "B17001", ["B17001_002E"], ["B17001_001E"],
        assertions={"B17001_002E": "below poverty level:"})
    acs("poverty-share-b17021", "02.08", "Population below poverty level · B17021", "B17021", ["B17021_002E"], ["B17021_001E"],
        notes=["B17021 is an explicit alternative table including BG. Never silently relabel B17021 as B17001; retain table identity."])
    acs("households-income-200k-plus-share", "02.09", "Households with income $200,000 or more", "B19001", ["B19001_017E"], ["B19001_001E"],
        assertions={"B19001_017E": "$200,000 or more"})
    for parent, metric_id, variable, label, assertion in [
        ("03.01", "bachelors-degree-exact-share", "B15003_022E", "Bachelor’s degree as highest attainment · age 25+", "Bachelor's degree"),
        ("03.02", "masters-degree-exact-share", "B15003_023E", "Master’s degree as highest attainment · age 25+", "Master's degree"),
        ("03.03", "doctorate-exact-share", "B15003_025E", "Doctorate as highest attainment · age 25+", "Doctorate degree"),
    ]:
        acs(metric_id, parent, label, "B15003", [variable], ["B15003_001E"],
            notes=["Highest-attainment category; professional-school degrees are a separate bin. This is not a bachelor’s-or-higher cumulative percentage."], assertions={variable: assertion})
    acs("high-school-or-higher-share", "03.04", "High school diploma or higher · age 25+", "B15003", bins("B15003", 17, 25), ["B15003_001E"],
        notes=["Includes regular diploma, GED/alternative credential, and all higher attainment groups."],
        assertions={"B15003_017E": "Regular high school diploma", "B15003_018E": "GED"})
    acs("no-high-school-diploma-share", "03.05", "No high school diploma · age 25+", "B15003", bins("B15003", 2, 16), ["B15003_001E"],
        assertions={"B15003_002E": "No schooling completed", "B15003_016E": "12th grade, no diploma"})
    acs("worked-from-home-share", "03.09", "Worked from home · workers age 16+", "B08301", ["B08301_021E"], ["B08301_001E"], assertions={"B08301_021E": "Worked from home"})

    def direct(metric_id, parent, label, field_id, source, releases, unit, display, scale, geographies, universe, urls, notes, period_type="annual"):
        definitions.append({"metric_id": metric_id, "version": 1, "catalog_field_id": parent,
            "label": label, "source": source, "source_releases": releases, "period": None,
            "period_type": period_type, "universe": universe,
            "raw_component_unit": unit, "display_unit": display, "accepted_input_units": [unit],
            "native_geographies": geographies, "formula": {"operation": "identity", "numerator": {field_id: 1}, "denominator": {}, "scale": scale},
            "source_urls": urls, "state_calculation": "Use the exact published or admitted state series when available.",
            "nation_calculation": "Use a compatible official national observation if available; follow separate aggregate policy otherwise.",
            "uncertainty": "No sampling interval supplied by this scalar series; missing uncertainty is not zero uncertainty.",
            "limitations": notes})

    direct("regional-price-parity", "02.10", "All-items regional price parity", "02.10", "bea_rpp", ["BEA-SARPP-2024", "BEA-SARPP-2024-release-2026-02-19"], "index_us_100", "index · US = 100", 1,
        ["state", "nation"], "Regional prices relative to the national price level",
        ["https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area"],
        ["Use SARPP LineCode 1; MARPP metro series and MAIRPD deflator are distinct. Index base is the US price level in the same year."])
    direct("unemployment-rate", "03.06", "Unemployment rate", "03.06:unemployment_rate", "bls_laus", ["BLS-LAUS-2024"], "%", "%", 1,
        ["state", "county"], "Civilian labor force age 16+",
        ["https://www.bls.gov/lau/lauseas.htm", "https://www.bls.gov/lau/data-overview.htm"],
        ["State LASST series are seasonally adjusted; county LAUCN series are unadjusted. Do not compare or pool adjustment regimes.",
         "Published one-decimal rates can differ from ratios calculated from published counts. National state-count aggregates are calculated values, not official CPS national estimates."], "monthly")
    for metric_id, field_id, label in [("unemployment_count", "03.06:unemployment", "Unemployed people"),
                                      ("labor_force_count", "03.06:labor_force", "Civilian labor force")]:
        direct(metric_id, "03.06", label, field_id, "bls_laus", ["BLS-LAUS-2024"], "persons", "persons", 1,
            ["state", "county"], "Civilian labor force age 16+", ["https://www.bls.gov/lau/lauseas.htm"],
            ["State LASST series are seasonally adjusted; county LAUCN series are unadjusted. Aggregate only compatible adjustment regimes."], "monthly")
    for parent, metric_id, label in [("04.01", "murder-count", "Murders"), ("04.02", "violent-crime-count", "Violent crime"),
        ("04.03", "robbery-count", "Robbery"), ("04.04", "aggravated-assault-count", "Aggravated assault"),
        ("04.05", "burglary-count", "Burglary"), ("04.06", "motor-vehicle-theft-count", "Motor vehicle theft"), ("04.07", "rape-count", "Rape")]:
        direct(metric_id, parent, label, parent, "fbi_cde", ["FBI-CDE-2019-2023"], "count", "events", 1, ["state"], "Offenses reported by participating law enforcement agencies",
            ["https://cde.ucr.cjis.gov/", "https://ucr.fbi.gov/crime-in-the-u.s/2019/crime-in-the-u.s.-2019/topic-pages/tables/table-1"],
            ["Annual summed source monthly actuals are reported counts with participation limits, not necessarily complete incidence estimates.",
             "A rate per 100,000 requires matched-year covered-population evidence and matching reporting scope. ACS 2020–2024 population is not silently used for 2023 crimes.",
             "National totals require official national source or verified coverage; do not assume state sums equal official estimates."])
    direct("agi-county-total", "07.01", "Adjusted gross income · county total", "07.01:A00100:county_sum_agi_stubs_1_8", "irs_soi", ["IRS-SOI-COUNTY-2023"], "thousand_USD", "USD", 1000,
        ["county"], "Individual income tax returns represented in IRS county tables",
        ["https://www.irs.gov/statistics/soi-tax-stats-county-data", "https://www.irs.gov/pub/irs-soi/23incyallagi.csv"],
        ["Sum disjoint AGI stubs 1–8 once. County FIPS 000 is a state total and is never a county.",
         "The selected county series has no state row. Validated derived state totals retain a separate identity and do not overwrite county observations.",
         "Amount is in thousands of dollars. No per-return result without a separately validated return-count variable; N1 is not automatically N00100."])
    direct("electricity-price-all-sectors", "08.05", "Average electricity retail price · all sectors", "08.05:sector_ALL", "eia", ["EIA-electricity-retail-sales-2024"], "cents per kilowatt-hour", "USD/kWh", .01,
        ["state", "nation"], "Electricity retail sales · all sectors", ["https://www.eia.gov/electricity/data.php", "https://www.eia.gov/electricity/sales_revenue_price/"],
        ["Source price is cents/kWh. Residential sector RES is a separate series; rates must not be averaged across states without sales weights."])
    direct("fitness-facilities-density", "09.04", "Recreation and fitness facilities per 1,000 residents", "09.04", "usda_fea", ["USDA-FEA-2025"], "facilities_per_1000_persons", "facilities/1,000 people", 1,
        ["county"], "NAICS 713940 recreation and fitness establishments per population",
        ["https://www.ers.usda.gov/data-products/food-environment-atlas/documentation/"],
        ["RECFACPTH20 is facilities per 1,000 population, not per 10,000 and not a percentage.",
         "The provider publishes county density; a stored state value needs its own aggregation-method evidence. Do not sum county densities.",
         "Observation year is 2020, distinct from the 2025 atlas release. Suppressed establishments and historical county-boundary changes can limit coverage."])
    definitions[-1]["accepted_input_units"].append("source_defined")
    # This explicit raw amount variant is the aggregate-session component contract.
    original_agi = next(d for d in definitions if d["metric_id"] == "agi-county-total")
    raw_agi = json.loads(json.dumps(original_agi))
    raw_agi.update(metric_id="published_total_agi", label="Published county AGI · source thousands of USD", display_unit="thousand_USD")
    raw_agi["formula"]["scale"] = 1
    definitions.append(raw_agi)
    for item in definitions:
        operation = item["formula"]["operation"]
        if operation in {"share", "ratio"}:
            item["statistic"] = operation
        elif item["metric_id"] == "unemployment-rate":
            item["statistic"] = "share"
        elif item["catalog_field_id"] == "07.01":
            item["statistic"] = "amount"
            item["provenance_kind"] = "derived"
        elif item["metric_id"].startswith("median-"):
            item["statistic"] = "median"
        elif item["metric_id"] in {"per-capita-income", "electricity-price-all-sectors"}:
            item["statistic"] = "mean"
        elif item["metric_id"] == "regional-price-parity":
            item["statistic"] = "index"
        elif item["metric_id"] == "fitness-facilities-density":
            item["statistic"] = "density"
        else:
            item["statistic"] = "count"
    return {"format": "usa_atlas_map_metric_definitions_v1", "checked_on": "2026-10-11", "version": 1,
        "purpose": "Opt-in checked consumer definitions; source observations and ingestion pins remain unchanged.",
        "definitions": sorted(definitions, key=lambda r: (r["catalog_field_id"], r["metric_id"]))}


def raw_unit(group):
    if group == "B01002":
        return "years"
    if group in {"B19013", "B19301", "B25064", "B25077", "B25088"}:
        return "USD"
    if group == "B19001":
        return "households"
    if group in {"B25003", "B25070"}:
        return "housing_units"
    if group == "B08301":
        return "workers"
    return "persons"


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
