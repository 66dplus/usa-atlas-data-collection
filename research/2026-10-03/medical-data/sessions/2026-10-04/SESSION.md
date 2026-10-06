# Medical-data research session — 2026-10-04

**Status: partial.** This session extended the standalone medical-data seed. All edits and downloads are inside this research directory. No production database, UI, catalog, credentials, services, or Git state were changed.

## Work completed

- Retrieved the CDC HIV Surveillance Supplemental Report 2024;29(1) PDF from the official CDC Stacks URL. Receipt: HTTP 200, PDF, 9,155,010 bytes, SHA-256 `dcb13fbebb596b217fdc873d3bf5a2ba4200ea0a8616f301797b25fa640e1563`. The bounded reusable downloader is `collect_hiv_estimates.py`; request, retrieval time, response type, size, status, and hash are in `http-receipts.jsonl`.
- Transcribed and normalized the report's 2022 modeled estimated HIV incidence (Table 6 and selected EHE Phase I Table A1): 52 state/DC/Puerto Rico rows and 49 selected county/municipality rows. Count and rate are separate metrics, yielding 101 area rows per metric: 60 published values and 41 source ellipses for RSE >50% per metric. Ellipses remain null. The report's age 13+ universe, residence-at-diagnosis definition, rounding, 95% CIs, RSE stars, Census Vintage 2022 population denominator source, reporting caveats, and PDF/extract hashes are attached to records.
- Added estimated total HIV prevalence separately from diagnoses and diagnosed-only prevalence, using Table 13 and Table A2 from the same report. The extracts contain 52 state/DC/Puerto Rico areas and 50 EHE areas (49 county/municipality geographies plus DC). Count and rate each have 102 numeric records, 204 numeric observations total. They retain age 13+, diagnosed-plus-undiagnosed model status, 95% CIs, RSE, preliminary 2022 flag, end-year most-recent-address definition, reporting caveats, and Vintage 2022 Census denominator source. The Table A2 county coverage is selected EHE geography, not a complete county series.
- Rechecked source documentation for linked-infant definition/coverage, HIV model/reporting definitions, and NCI State Cancer Profiles/CDC U.S. Cancer Statistics. Current downloaded NCI State Cancer Profiles export headers show pooled incidence 2019–2023 and mortality 2020–2024. Existing raw NCI exports have successful HTTP 200 receipts with full query parameters and hashes; the CDC 2026 USCS technical notes state that the newest incidence year is 2023 and newest death year is 2024.
- Rebuilt normalized records, source/coverage audits, and the combined overview/inventory with `normalize_medical.py`, `audit_medical.py`, and `build_overview.py`. Overview now reports 57 combined metric IDs and 98,219 numeric observation cells across the core and separate child-county bundles. Core contains 124,434 rows (86,253 numeric; 38,181 missing/suppressed); the child-county bundle remains unchanged and its exact 0–17/0–19 ages and periods remain separate.

## Sources checked

- CDC HIV report, data tables and method notes: <https://stacks.cdc.gov/view/cdc/156513/cdc_156513_DS1.pdf>
- CDC NHSS definitions and denominator notes: <https://www.cdc.gov/hiv-data/nhss/index.html>
- CDC current modeled-estimate release page: <https://www.cdc.gov/hiv-data/nhss/estimated-hiv-incidence-and-prevalence.html>
- CDC AtlasPlus table availability notice: <https://gis.cdc.gov/grasp/nchhstpatlas/tables.html>
- NCI State Cancer Profiles incidence and death-rate documentation: <https://statecancerprofiles.cancer.gov/help/about/incidence_rates.html> and <https://statecancerprofiles.cancer.gov/help/about/death_rates.html>
- CDC U.S. Cancer Statistics current release notes and database scope: <https://www.cdc.gov/united-states-cancer-statistics/technical-notes/index.html> and <https://www.cdc.gov/united-states-cancer-statistics/public-use/about.html>
- CDC WONDER linked-infant release and documentation: <https://wonder.cdc.gov/lbd-current-expanded.html> and <https://wonder.cdc.gov/wonder/help/lbd-expanded.html>

## Remaining limitations and continuation queue

- CDC AtlasPlus currently says new modeled incidence/prevalence estimates are postponed; the latest opened official model report covers 2018–2022 only. Table A1/A2 are selected EHE county/municipality series, not all-county coverage. The 41 high-RSE incidence cells per count/rate metric remain unreported/null. Estimated 2022 prevalence remains preliminary; CDC flags laboratory-reporting and death-completeness limitations. Exact denominator counts are not published in these table cells. No race/sex strata appear in the area tables.
- Linked infant county data remain limited to counties meeting the 2010 Census population threshold of 250,000; other counties stay in state-specific Unidentified Counties. Small-cell suppression and unreliable-rate flags remain as published.
- Child 1–4 and 5–14 county/state death counts are retained, but county 1–4 age-specific population denominators/direct rates remain unavailable in the selected official export; county 5–14 derived rates are clearly separate from direct counts and state-published rates.
- Next: pursue documented state/county child-mortality rates and age-specific denominators where available; check the next complete HIV diagnosis year and keep it separate from incidence/prevalence; then advance hepatitis B/C, tuberculosis and reportable STI availability. Continue to mark unsupported HSV surveillance and absent geographies as unavailable, never zero. Recheck AtlasPlus for a newer modeled HIV release.

## Changed and added artifacts

- `raw/cdc-hiv-estimated-incidence-prevalence-2018-2022.pdf`
- `raw/cdc-hiv-estimated-incidence-2022-state.csv`
- `raw/cdc-hiv-estimated-incidence-2022-ehe-county.csv`
- `raw/cdc-hiv-estimated-prevalence-2022-state.csv`
- `raw/cdc-hiv-estimated-prevalence-2022-ehe-county.csv`
- `collect_hiv_estimates.py`, `normalize_medical.py`, `audit_medical.py`
- `normalized/observations.csv`, `normalized/observations.json`, `coverage.json`, `coverage-geographies.json`, `metric-inventory.csv`, `metric-inventory.json`, `source-register.json`, `all-metric-inventory.csv`, `research-overview.json`, `artifact-manifest.json`, `backlog.json`
- `README.md` and `WEEKLY-HANDOFF.md`
