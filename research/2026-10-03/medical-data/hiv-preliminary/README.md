# CDC preliminary HIV diagnosis tables

Downloaded and normalized 2026-10-05 from CDC Stacks release 2026-09-24. Reproduction uses `python3 collect_hiv_preliminary.py fetch` and `python3 collect_hiv_preliminary.py normalize`.

## Dataset

`observations.csv` and `.json` contain **320 rows (320 numeric)** for `hiv_preliminary_diagnoses_count`. CDC's workbook reports diagnoses among persons aged 13 years and older by date of diagnosis, through June 2026. It has a full-year 2025 column and a separate January-June 2026 column. These are observed diagnoses, not estimated incident infections. They remain separate from diagnosed HIV prevalence and modeled total prevalence.

The collection includes Table 1a national demographic strata (sex, age, race/ethnicity, transmission category and Census region), Table 1b selected characteristics with the separate seven-territory scope, Table 1c state/DC and named territory counts, and Table 1d selected EHE county/county-equivalent counts. No rates or denominators are published. County identifiers are matched by state and source name to the downloaded 2025 Census Gazetteer; source table boundary vintage is unspecified. Each normalized record retains its table, row, cell, source text, workbook hash and report cutoff.

## Coverage and limits

- State/DC: 51 published geographies (FIPS preserved as two-character strings). Seven named territories/freely associated states are separate rows. National tables include `US` and `US_PLUS_7_TERRITORIES` scopes as explicitly titled.
- County/county-equivalent: 49 selected EHE jurisdictions, listed in `coverage.json`. `coverage-geographies.csv` compares these with every Census 2025 county-equivalent identifier and labels all others `not_in_this_release`. Unlisted counties are unavailable in this release, not zero. No tracts or block groups.
- The 2026 column covers six months, not a full year. CDC says 2025 and 2026 counts are preliminary until a 12-month reporting delay and cautions against trend or cross-year count comparisons. Values under 12 remain numeric and receive `source_small_count_caution`; source-published zeros remain zero. No suppression symbols appeared in the collected diagnosis tables.
- The workbook does not include population denominators/rates. National race/sex strata are not state or county cross-tabs. Transmission-category counts are statistically adjusted for missing category and may not sum to the total. CDC's national deduplication and statistical adjustments can cause differences from jurisdiction publications.

See `coverage.json`, `source-checks.json`, the row-level provenance and `../http-receipts.jsonl` for coverage and verified HTTP outcomes.
