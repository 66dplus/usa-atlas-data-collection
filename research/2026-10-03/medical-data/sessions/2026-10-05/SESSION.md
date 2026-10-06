# Medical-data research session — 2026-10-05

**Status: partial.** This daily session advanced the required child mortality series and refreshed official source and coverage documentation. The separate population-data research remains incomplete. All downloads and edits stayed in this medical-data directory; no production data, application, credentials, services, or Git state were changed.

## Work completed

- Added the bounded standard-library collector `collect_child_population_denominators.py`. It requests the Census Population Estimates Program Vintage 2025 county age/sex CSV once for each of 50 states and DC, with a 45-second timeout and 32 MiB per-file bound; successful raw files are cached by SHA-256 and request receipts include URL, parameters, HTTP outcome, retrieval time, byte count, hash and source headers.
- Verified all **51/51 final Census CSV downloads** returned HTTP 200. Together they are 105,016,627 bytes. The compact support table `child-age-bands/census-pep-2025-age1-4-population.csv` has **62,880 unique rows**: 3,144 county-equivalents × years 2020–2024 × exact ages 1, 2, 3 and 4. The source Vintage 2025 boundaries are dated 2025-01-01; estimates are July 1 total resident population, both sexes.
- Added a distinct `child_mortality_1_4_derived_county_rate` metric from directly observed CDC WONDER 2020–2024 age 1–4 death counts and the sum of 20 matching PEP age/year populations, per 100,000 person-years. There are **1,186 numeric rates from 3,142 source county rows**. Of 1,956 nulls, **1,952** retain the WONDER death-count suppression (<10), and **4** have visible counts but no matching denominator FIPS. Of the numeric rates, **283** carry the CDC/NCHS unreliable-rate flag because the direct count is below 20. No confidence intervals were created.
- Preserved geography exactly. The WONDER file contains 3,142 county source FIPS; 3,131 match a 2025 Census county-equivalent FIPS and 11 source IDs do not (`02261`, `02270`, `09001`, `09003`, `09005`, `09007`, `09009`, `09011`, `09013`, `09015`, `46113`). Thirteen Census 2025 county-equivalents have no row in this WONDER source set. No crosswalk or allocation was applied. `coverage-geographies.json` and `child-age-bands/census-pep-2025-coverage.json` enumerate the exact FIPS.
- Kept the new PEP-derived county rate separate from published state rates and from the existing 5–14 county-rate derivation. The 1–4 denominator uses a different source and vintage than the WONDER state-rate denominators, so the rates are not directly comparable. Direct state rates and the separate 5–14 series remain intact; the distinct `child-county/` four-year 0–17 and 0–19 measures were normalized separately and retain their exact age ranges, periods and Connecticut boundary differences.
- Rebuilt the core normalized rows, source register, geography coverage, combined inventory and overview. Current summary: **133,968 core observations / 93,807 numeric; 94 combined metric IDs / 106,627 numeric cells across separate bundles.** These cells are not people or combined disease totals.
- Reopened primary CDC/NCI sources and current release documentation. Confirmed the linked-infant county cutoff is 250,000 residents under the 2010 Census for the 2017+ public linked file; smaller counties remain state-specific `Unidentified Counties`. Confirmed CDC's current HIV model-release page still points to the 2018–2022 report; AtlasPlus's static page lists estimated-incidence/prevalence tables but does not disclose their data vintage. The separately stored 2025 and Jan–Jun 2026 HIV diagnosis rows remain preliminary diagnoses, not modeled incidence. Checked the current USCS public-use scope, denominator notes, rate standard, data dictionary and NCI State Cancer Profiles methods; no new cancer numeric export was added in this session.

## Data and receipt review

- Recalculated all 1,186 derived rates from the attached direct count and denominator; every numeric row matched `count / population person-years × 100,000`. Suppressed counts and denominator gaps remain null with distinct statuses.
- Re-read the 62,880 support rows: zero duplicate `(FIPS, year, age)` keys. Verified local SHA-256 against all 51 successful Census HTTP 200 receipts; no missing or mismatched file hashes.
- The first collector header check rejected the Census CSV's quoted UTF-8-BOM header on some HTTP 200 responses. The header parser was corrected; all final files were downloaded and parsed. The initial attempts and later successful requests remain recorded in `http-receipts.jsonl`; the audit marks the earlier failures recovered. No Census route remains blocked.
- No suppressed cell was inferred, and no state figure was copied to counties. A missing FIPS is not treated as a zero.

## Sources checked

- Census PEP Vintage 2025 county estimates and file layout: <https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html> and <https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/CC-EST2025-SYASEX.pdf>
- CDC WONDER Underlying Cause of Death query/help and linked infant release/help: <https://wonder.cdc.gov/ucd-icd10-expanded.html>, <https://wonder.cdc.gov/wonder/help/ucd-expanded.html>, <https://wonder.cdc.gov/lbd-current-expanded.html>, <https://wonder.cdc.gov/wonder/help/lbd-expanded.html>
- CDC infant and child definitions/statistics: <https://www.cdc.gov/nchs/state-stats/deaths/infant-mortality.html> and <https://www.cdc.gov/nchs/fastats/child-health.htm>
- CDC HIV current modeled release, NHSS definitions and AtlasPlus table page: <https://www.cdc.gov/hiv-data/nhss/estimated-hiv-incidence-and-prevalence.html>, <https://www.cdc.gov/hiv-data/nhss/index.html>, <https://gis.cdc.gov/grasp/nchhstpatlas/tables.html>
- NCI State Cancer Profiles incidence/death methods and CDC USCS current release, denominators and data dictionary: <https://statecancerprofiles.cancer.gov/help/about/incidence_rates.html>, <https://statecancerprofiles.cancer.gov/help/about/death_rates.html>, <https://www.cdc.gov/united-states-cancer-statistics/technical-notes/index.html>, <https://www.cdc.gov/united-states-cancer-statistics/technical-notes/population-denominator-data-sources.html>, <https://www.cdc.gov/united-states-cancer-statistics/public-use/documentation.html>

## Remaining limitations and next work

- The 1–4 county rate is only numerically supported for 1,186 source FIPS. Most rows remain null from CDC suppression; four additional visible death counts lack an exact 2025 PEP denominator. The source has 11 legacy/mismatched county FIPS, and 13 current Census county-equivalents are absent. The rate has no published CI and is not directly comparable to the state series. Continue source-vintage and boundary review without allocating geographies.
- The 2017+ linked infant county release still hides counties below its 2010 Census population cutoff; their `Unidentified Counties` totals cannot be recovered. Preserve the separate period-linked definition, suppression and unreliable-rate markers.
- Continue HIV first: inspect the documented live AtlasPlus table/API response for a downloadable modeled-estimate vintage newer than 2018–2022, then fill the queued complete-year diagnosed trend baseline if an official export is available. Do not infer incidence from diagnosis counts.
- Then pursue an actual CDC HepTracker hepatitis 2024 export, including acute/chronic/perinatal case categories and public geography, and revisit final 2024 STI state/county availability, county TB sources and unavailable uniform HSV surveillance. Existing national-only or unsupported measures remain explicitly unavailable rather than zero.

## Artifacts added or refreshed

- `collect_child_population_denominators.py`
- `raw/census-pep-v2025-syasex/cc-est2025-syasex-*.csv` (51 official source files)
- `child-age-bands/census-pep-2025-age1-4-population.csv`
- `child-age-bands/census-pep-2025-coverage.json`
- `normalized/observations.csv`, `normalized/observations.json`, `coverage.json`, `coverage-geographies.json`
- `metric-inventory.csv`, `metric-inventory.json`, `state-coverage.csv`, `state-coverage.json`
- `source-register.json`, `http-receipts.jsonl`, `artifact-manifest.json`, `all-metric-inventory.csv`, `research-overview.json`, `backlog.json`
- `README.md`, `WEEKLY-HANDOFF.md`, and this session record
