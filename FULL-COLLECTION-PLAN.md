# USA Atlas full collection: local launch plan

Date: 19 September 2026  
Workflow: FULL  
Current gate: Plan  
Goal version: `full-collection-v1`

## Before and after

**Before.** The repository has an 81-row source catalog and a credentialed pilot that
returns 10 records from six authenticated services plus two public paths. It does not
yet have an exact field-run ledger, a resumable nationwide collector, measured local
throughput, or a per-field Eval. Several catalog rows name broad families rather than
one numeric variable, and some sources require manual export, a source decision, or a
license.

**After.** A local-only collection run has been started from a deterministic 81-row
ledger. Every catalog row is either collected/derived or reports a precise non-success
state. The run is resumable, retains sanitized raw evidence, measures request/row/byte
throughput, and produces an Eval tied to the exact ledger and run manifest. A separate
scaling report estimates a compliant local-plus-two-server path to a roughly two-day
collection, without treating extra IP addresses or proxies as permission to bypass a
provider limit.

The first launch is the nine-source calibration matrix below. A source may enter the
full local queue only when its own slice passes every bound in that matrix. A failed
source remains stopped while independent passed sources continue. This is an execution
safeguard, not a second approval gate.

## Immutable acceptance target

1. **FC1 — Complete field contract.** All 81 catalog rows have a stable `field_id`,
   source family, target geography, acquisition mode, concrete field definition or
   explicit definition gap, and planned state. Every `run_now` row also has an exact
   release/endpoint or bulk file selector, source variable/group/code, derivation,
   target geography, and unavailable-geography behavior. Broad rows such as age and
   race may expand to multiple source variables, but remain traceable to one catalog
   row. Verification: the contract validator reports exactly 81 unique catalog IDs,
   all nine sections represented, zero missing required cells, and zero `run_now` rows
   missing an executable mapping field.
2. **FC2 — Safe local calibration.** A bounded local calibration covers the nine
   `run_now` source families using the matrix below.
   Verification: each attempted slice records start/end time, request count, response
   bytes, raw row count, normalized row count, retry/`429` count, and terminal state;
   secrets and personal email have zero matches in project artifacts.
3. **FC3 — Resumable local run.** The same runner can enqueue every field whose ledger
   state is `run_now`, checkpoint completed work, and resume without duplicating a
   normalized key or redownloading an immutable successful artifact. Verification: a
   stopped-and-resumed test asserts zero transport calls for already-complete immutable
   jobs, produces the same artifact hashes as an uninterrupted fixture run, and has no
   duplicate `(geo_id, year, field_id, source_release)` keys; the real local run is
   launched with a saved PID/status and manifest.
4. **FC4 — Provider compliance.** Each adapter uses the provider's documented packing,
   pagination, and rate behavior. Credentials remain outside the project; request URLs
   and saved responses are sanitized. No proxy, key rotation, server fan-out, or IP
   rotation is used to evade quotas, WAFs, licenses, or terms. A versioned adapter
   configuration records, for all nine active source families, official documentation
   URL/date, documented limit, conservative local limiter, packing/page caps,
   retry/stop behavior, and sanitization mode; each run manifest binds its SHA-256.
   Verification: the run log shows the source limiter and bound config hash, and safety
   tests plus a credential-value scan pass.
5. **FC5 — Per-field Eval.** Eval maps every original `field_id` to `expected`,
   `observed`, `PASS | FAIL | BLOCKED | NOT_RUN`, evidence path/hash, row/geography/year
   coverage, and reason. `BLOCKED` and `NOT_RUN` never count as `PASS`. Verification:
   Eval covers 81/81 unique IDs and its summary totals equal 81.
6. **FC6 — Measured scale plan.** The separate `SCALING-PLAN.md` states official limits,
   measured or bounded request/byte volume, partitioning across one local machine and
   two servers, shared-limit behavior, checkpoint/retry design, storage estimate,
   two-day feasibility, and an explicit `buy proxies: yes/no` recommendation.
   Verification: facts are linked to official sources, assumptions are labeled, and
   the estimate is recalculated from calibration measurements before any distributed
   run. Its verdict is exactly `feasible`, `not_feasible`, or `unknown` for 48 hours,
   and its `buy proxies: yes|no` line is explicitly a recommendation, not authorization.

After final verification we will have a real local collection in progress, a complete
and honest Eval surface for all 81 requested rows, and a measured decision on how to
finish nationwide collection—not a claim that undefined or unlicensed data was scraped.

## Field-run ledger frozen for v1

The `planned state` below governs the first local run. `run_now` means the adapter may
be executed after calibration. Other states remain in Eval and require their named
condition; they must not be replaced with a look-alike metric.

| ID | Catalog field | Source | Planned state | v1 definition / blocker |
| --- | --- | --- | --- | --- |
| 01.01 | Population | Census ACS | run_now | Total population; retain estimate and margin of error where published |
| 01.02 | Age | Census ACS | run_now | Full published age-band distribution plus median age; no single-score collapse |
| 01.03 | Sex | Census ACS | run_now | Published sex counts/shares; preserve source labels |
| 01.04 | Race / ethnicity | Census ACS | run_now | Mutually clear race and Hispanic-origin variables with denominators |
| 01.05 | Foreign-born population | Census ACS | run_now | Foreign-born count and share |
| 01.06 | Country / region of birth | Census ACS | run_now | Published birthplace regions/counts available at each geography |
| 01.07 | Citizenship | Census ACS | run_now | Citizenship-status counts/shares |
| 01.08 | Year / period of immigration | Census ACS | run_now | Published entry-period bins/counts |
| 02.01 | Median household income | Census ACS | run_now | Median household income, nominal USD, estimate + MOE |
| 02.02 | Per-capita income | Census ACS | run_now | Per-capita income, nominal USD, estimate + MOE |
| 02.03 | Median rent | Census ACS | run_now | Median gross rent, nominal USD, estimate + MOE |
| 02.04 | Median home value | Census ACS | run_now | Owner-occupied median value, nominal USD, estimate + MOE |
| 02.05 | Mortgage / selected monthly owner costs | Census ACS | run_now | Selected monthly owner costs with mortgage; estimate + MOE |
| 02.06 | Rent as % of income / rent burden | Census ACS | run_now | Gross-rent-as-income distribution and 30%+ derived share |
| 02.07 | Owner / renter ratio | Census ACS | run_now | Occupied owner and renter counts plus derived ratio |
| 02.08 | Poverty | Census ACS | run_now | Below-poverty count and share for population with status determined |
| 02.09 | Households earning $200k+ | Census ACS | run_now | Count and derived share of households in $200k+ income bins |
| 02.10 | Cost of living / Regional Price Parities | BEA RPP | run_now | All-items RPP, U.S.=100, state and metro release rows |
| 03.01 | Bachelor's degree | Census ACS | run_now | Highest attainment bachelor's count/share, age 25+ |
| 03.02 | Master's degree | Census ACS | run_now | Highest attainment master's count/share, age 25+ |
| 03.03 | Doctorate | Census ACS | run_now | Highest attainment doctorate count/share, age 25+ |
| 03.04 | High school attainment | Census ACS | run_now | High-school-or-higher derived count/share, age 25+ |
| 03.05 | No diploma | Census ACS | run_now | Less-than-high-school derived count/share, age 25+ |
| 03.06 | Unemployment | BLS LAUS | run_now | Published unemployment rate and supporting labor-force counts |
| 03.07 | Average / mean salary | BLS OEWS | blocked_access | Mean annual wage; official bulk file path must pass current access check |
| 03.08 | Employment growth | BLS LAUS | definition_required | Exact series, comparison window, seasonal adjustment, and geography are unresolved |
| 03.09 | Work from home share | Census ACS | run_now | Worked-from-home count and derived share among workers 16+ |
| 04.01 | Murders | FBI CDE | run_now | UCR murder/nonnegligent manslaughter count/rate with coverage |
| 04.02 | Violent crime | FBI CDE | run_now | Violent-crime count/rate with reporting coverage |
| 04.03 | Robbery | FBI CDE | run_now | Robbery count/rate with reporting coverage |
| 04.04 | Aggravated assault | FBI CDE | run_now | Aggravated-assault count/rate with reporting coverage |
| 04.05 | Burglary | FBI CDE | run_now | Burglary count/rate with reporting coverage |
| 04.06 | Motor vehicle theft | FBI CDE | run_now | Motor-vehicle-theft count/rate with reporting coverage |
| 04.07 | Rape | FBI CDE | run_now | Rape count/rate with definition and reporting coverage |
| 04.08 | Homicide | FBI CDE / CDC WONDER | definition_required | Crime-report count and mortality count are not interchangeable; owner definition needed |
| 04.09 | Crime trends | FBI CDE | run_now | Derived time series/change from the seven collected offense families; preserve coverage |
| 05.01 | Drug overdose deaths | CDC WONDER | blocked_access | Official API disallows state/county grouping; compliant subnational export required |
| 05.02 | Opioid deaths | CDC WONDER | blocked_access | Same subnational export constraint; ICD-10 definition retained |
| 05.03 | Fentanyl / synthetic opioid deaths | CDC WONDER | blocked_access | Same subnational export constraint; multiple-cause definition retained |
| 05.04 | Cocaine deaths | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.05 | Methamphetamine / psychostimulant deaths | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.06 | Heroin deaths | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.07 | Alcohol-related deaths | CDC WONDER | blocked_access | Same export constraint; case definition also must be recorded |
| 05.08 | Suicide | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.09 | Homicide mortality | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.10 | Heart disease deaths | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.11 | Cancer deaths | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.12 | Accidental deaths | CDC WONDER | blocked_access | Same subnational export constraint |
| 05.13 | Life-expectancy-related indicators | CDC / NCHS | source_required | Exact official release, vintage, measure, and suppression rules not selected |
| 05.14 | Obesity rate | CDC PLACES | run_now | County/place/tract/ZCTA model-based estimate with type and confidence interval |
| 05.15 | Diabetes rate | CDC PLACES | run_now | County/place/tract/ZCTA model-based estimate with type and confidence interval |
| 05.16 | Physical inactivity rate | CDC PLACES | run_now | County/place/tract/ZCTA model-based estimate with type and confidence interval |
| 06.01 | Total homeless | HUD PIT | blocked_access | Official workbook currently returns WAF challenge to automated client |
| 06.02 | Sheltered homeless | HUD PIT | blocked_access | Same official workbook access constraint |
| 06.03 | Unsheltered homeless | HUD PIT | blocked_access | Same official workbook access constraint |
| 06.04 | Homeless veterans | HUD PIT | blocked_access | Same official workbook access constraint |
| 06.05 | Homeless families | HUD PIT | blocked_access | Same official workbook access constraint |
| 06.06 | Chronically homeless | HUD PIT | blocked_access | Same official workbook access constraint |
| 07.01 | Adjusted Gross Income (AGI) | IRS SOI | run_now | Published aggregate AGI with return count and source income band |
| 07.02 | High-income taxpayers / returns | IRS SOI | definition_required | Income threshold must be fixed before collection/derivation |
| 07.03 | Capital gains | IRS SOI | run_now | Published net capital-gain amount and return count |
| 07.04 | Dividends | IRS SOI | run_now | Published ordinary-dividend amount and return count |
| 07.05 | Taxes / income tax metrics | IRS SOI | definition_required | Exact tax field(s), denominator, and aggregation must be fixed |
| 07.06 | Millionaires | Source TBD | source_required | No approved direct official count; labeled IRS proxy or licensed source decision needed |
| 07.07 | Billionaires | Forbes | license_required | Automated collection is not authorized by published terms |
| 08.01 | Price of a dozen eggs | Retail/menu TBD | source_required | Geography, freshness, and approved source are unresolved |
| 08.02 | Cup of coffee price | Retail/menu TBD | source_required | Product definition, geography, and approved source are unresolved |
| 08.03 | Big Mac / McDonald's meal price | Private menu data | license_required | License/terms approval required before automation |
| 08.04 | Gasoline price | Fuel data TBD | definition_required | State/metro/station product and update cadence must be selected |
| 08.05 | Electricity price | EIA Electricity | run_now | Published retail price by state, sector, and period |
| 08.06 | Beer price | Private retail/menu data | license_required | Product definition and licensed source required |
| 08.07 | Average consumer debt | Consumer debt TBD | source_required | Debt type, statistic, geography, and approved aggregate source unresolved |
| 08.08 | Student loan debt | Consumer debt TBD | source_required | Balance/delinquency definition and approved aggregate source unresolved |
| 08.09 | Average health insurance cost | Health insurance TBD | definition_required | Premium/cost concept, market, plan type, geography, and source unresolved |
| 09.01 | Fast-food restaurants per 10k residents | USDA Food Environment Atlas | run_now | Published county variable; keep variable-specific reference year |
| 09.02 | Access to a grocery store | USDA Food Environment Atlas | run_now | Published access variable(s); keep definition and reference year |
| 09.03 | Farmers' markets per capita | USDA Food Environment Atlas | run_now | Published county variable; keep denominator and reference year |
| 09.04 | Fitness / recreation centers per capita | USDA Food Environment Atlas | run_now | Published county variable; keep denominator and reference year |
| 09.05 | Parks / recreation facilities | USDA / source TBD | definition_required | Exact Atlas variable and facility concept must be selected |
| 09.06 | PM2.5 | EPA AQS / AirData | run_now | Annual summary where available; monitor/county provenance preserved |
| 09.07 | Ozone | EPA AQS / AirData | run_now | Annual summary where available; standard and monitor provenance preserved |

Planned-state totals for v1: `run_now=46`, `blocked_access=19`,
`definition_required=7`, `source_required=6`, `license_required=3`; total `81`.

### Executable contract required for every `run_now` row

The implementation materializes `field-contract.json`. Each row has:

`field_id, catalog_label, planned_state, source, source_release, acquisition_mode,
source_selector, source_variables, derivation, target_geographies,
unavailable_geography, unit, rate_limit_profile, license_status`.

`unavailable_geography` is always `record_not_available`; adapters may not silently
substitute a coarser geography. Estimate/MOE pairs, source labels, suppression and
source-specific years are retained. These v1 mappings are frozen:

| IDs | Release / selector | Mode | Variables / derivation | Target geography |
| --- | --- | --- | --- | --- |
| 01.01 | Census 2024 ACS 5-year `/groups/B01003` | API | `B01003_001E/M` | state, county, place, tract |
| 01.02 | Census 2024 ACS 5-year `/groups/B01001`, `/groups/B01002` | API | all B01001 age-band E/M values plus `B01002_001E/M` median | state, county, place, tract |
| 01.03 | Census 2024 ACS 5-year `/groups/B01001` | API | sex totals/bands from B01001 E/M variables; shares use `B01001_001E` | state, county, place, tract |
| 01.04 | Census 2024 ACS 5-year `/groups/B03002` | API | all mutually labeled B03002 race/Hispanic E/M variables and total denominator | state, county, place, tract |
| 01.05 | Census 2024 ACS 5-year `/groups/B05002` | API | native/foreign-born E/M values; shares use group total | state, county, place, tract |
| 01.06 | Census 2024 ACS 5-year `/groups/B05006` | API | all published birthplace-country/region E/M variables | state, county, place, tract |
| 01.07 | Census 2024 ACS 5-year `/groups/B05001` | API | all citizenship-status E/M variables and total denominator | state, county, place, tract |
| 01.08 | Census 2024 ACS 5-year `/groups/B05005` | API | all entry-period E/M variables | state, county, place, tract |
| 02.01 | Census 2024 ACS 5-year `/groups/B19013` | API | `B19013_001E/M` | state, county, place, tract |
| 02.02 | Census 2024 ACS 5-year `/groups/B19301` | API | `B19301_001E/M` | state, county, place, tract |
| 02.03 | Census 2024 ACS 5-year `/groups/B25064` | API | `B25064_001E/M` | state, county, place, tract |
| 02.04 | Census 2024 ACS 5-year `/groups/B25077` | API | `B25077_001E/M` | state, county, place, tract |
| 02.05 | Census 2024 ACS 5-year `/groups/B25088` | API | `B25088_001E/M` | state, county, place, tract |
| 02.06 | Census 2024 ACS 5-year `/groups/B25070` | API | all rent/income bins E/M; 30%+ numerator is published bins at or above 30%, denominator excludes not-computed | state, county, place, tract |
| 02.07 | Census 2024 ACS 5-year `/groups/B25003` | API | owner `002E/M`, renter `003E/M`, ratio `002E / 003E` | state, county, place, tract |
| 02.08 | Census 2024 ACS 5-year `/groups/B17001` | API | below-poverty `002E/M`, total `001E/M`, derived share | state, county, place, tract |
| 02.09 | Census 2024 ACS 5-year `/groups/B19001` | API | `$200k+` `017E/M`, total `001E/M`, derived share | state, county, place, tract |
| 02.10 | BEA `SARPP.zip`, state and MSA CSVs, line code 1 | bulk ZIP | all-items RPP rows; preserve GeoFIPS/year | state, metro |
| 03.01 | Census 2024 ACS 5-year `/groups/B15003` | API | bachelor's `022E/M`, denominator `001E/M`, derived share | state, county, place, tract |
| 03.02 | Census 2024 ACS 5-year `/groups/B15003` | API | master's `023E/M`, denominator `001E/M`, derived share | state, county, place, tract |
| 03.03 | Census 2024 ACS 5-year `/groups/B15003` | API | doctorate `025E/M`, denominator `001E/M`, derived share | state, county, place, tract |
| 03.04 | Census 2024 ACS 5-year `/groups/B15003` | API | sum `017E:025E`, denominator `001E/M`, derived share; MOE combined by documented square-root-of-sum-of-squares rule | state, county, place, tract |
| 03.05 | Census 2024 ACS 5-year `/groups/B15003` | API | sum `002E:016E`, denominator `001E/M`, derived share; MOE combined by documented rule | state, county, place, tract |
| 03.06 | BLS API v2 LAUS state/county area-series catalog, latest final annual year | API POST | unemployment-rate series plus employment, unemployment and labor-force supporting series; pack ≤50 series | state, county |
| 03.09 | Census 2024 ACS 5-year `/groups/B08301` | API | worked-at-home `021E/M`, total `001E/M`, derived share | state, county, place, tract |
| 04.01–04.07 | FBI CDE `/summarized/state/{state}/{offense}` for latest complete year | API | exact endpoint offense slug, monthly counts/rates and coverage metadata | state |
| 04.09 | Same seven FBI time series, latest five complete years | derived from API artifacts | annual totals and year-over-year change; no extra transport after source artifacts exist | state |
| 05.14 | CDC PLACES county resource `swc5-untb`, current release | Socrata API/bulk | `measureid=OBESITY`, age-adjusted prevalence, CI and data-value type | county |
| 05.15 | CDC PLACES county resource `swc5-untb`, current release | Socrata API/bulk | `measureid=DIABETES`, age-adjusted prevalence, CI and data-value type | county |
| 05.16 | CDC PLACES county resource `swc5-untb`, current release | Socrata API/bulk | `measureid=LPA`, age-adjusted prevalence, CI and data-value type | county |
| 07.01 | IRS SOI 2022 ZIP release, official national/state CSV/XLSX resolved from release page | bulk file | `N00100`, `A00100`, retain source income-size row | ZIP, derived county/state only with documented ZIP crosswalk |
| 07.03 | Same IRS SOI release | bulk file | `N01000`, `A01000`, retain source income-size row | ZIP, derived county/state only with documented ZIP crosswalk |
| 07.04 | Same IRS SOI release | bulk file | `N00600`, `A00600`, retain source income-size row | ZIP, derived county/state only with documented ZIP crosswalk |
| 08.05 | EIA v2 `/electricity/retail-sales/data`, latest complete annual period | paginated API | `data[0]=price`, facets `stateid` and `sectorid`; page ≤5,000 | state, utility, sector |
| 09.01 | USDA FEA 2025 `food-environment-atlas-csv-files.zip` | bulk ZIP | `FFRPTH20`; retain variable-list unit/year | county |
| 09.02 | Same USDA FEA release | bulk ZIP | `LACCESS_POP19`, `PCT_LACCESS_POP19`; retain definition/year | county |
| 09.03 | Same USDA FEA release | bulk ZIP | `FMRKTPTH18`; retain variable-list unit/year | county |
| 09.04 | Same USDA FEA release | bulk ZIP | `RECFACPTH20`; retain variable-list unit/year | county |
| 09.06 | EPA AirData annual concentration-by-monitor file, latest complete year | bulk ZIP; AQS API calibration fallback | parameter `88101`; preserve monitor/site/county, standard and statistic | monitor, derived county only with explicit aggregation metadata |
| 09.07 | EPA AirData annual concentration-by-monitor file, latest complete year | bulk ZIP; AQS API calibration fallback | parameter `44201`; preserve monitor/site/county, standard and statistic | monitor, derived county only with explicit aggregation metadata |

All 23 Census rows expand group metadata to concrete E/M variable IDs before request
packing; the materialized JSON stores that expansion, not only the group name.

### Versioned adapter configuration

`adapter-config.json` is part of the candidate and contains one record for each active
family: `census_acs, bls_laus, fbi_cde, cdc_places, bea_rpp, irs_soi,
usda_fea, eia, epa_airdata`. Required fields are
`docs_url, docs_checked_at, documented_limits, local_limiter, max_variables_or_series,
max_pages, max_response_bytes, max_attempts, retryable_statuses, stop_conditions,
sanitization_mode`. A run refuses an unknown family or config whose hash differs from
the hash stored in its manifest.

## Calibration bounds and execution order

Each slice has at most two transport attempts per request/download. Any `429` stops that
source immediately, records `Retry-After`, and prevents full enqueue during that run;
the calibration itself does not wait out or retry a `429`. Any byte, page, request, or
wall-time cap breach is `FAIL`, not truncation. Redirects away from the official host,
authentication errors, WAF/challenge pages, schema mismatches, or credential reflection
also stop only that source. These caps bound the calibration, not the later volume plan.

| Source | Exact calibration slice | Max requests | Max pages | Max bytes | Max wall time | Conservative limiter |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Census ACS | California county wildcard; first ≤50-variable executable pack | 2 | 2 | 20 MB | 5 min | sequential, ≤1 request/sec |
| BLS LAUS | one ≤50-series state/county pack, one final annual year | 1 | 1 | 10 MB | 3 min | sequential; registered daily quota shared |
| FBI CDE | one offense endpoint for three states, latest complete year | 3 | 3 | 20 MB | 6 min | sequential, ≤1 request/sec |
| CDC PLACES | one deterministic county page plus dataset metadata | 2 | 2 | 25 MB | 5 min | sequential token traffic; stop on 429 |
| BEA RPP | one `SARPP.zip` release | 1 | 1 | 50 MB | 5 min | one immutable download |
| IRS SOI | one official release file resolved from the 2022 release page | 1 | 1 | 250 MB | 15 min | one immutable download |
| USDA FEA | 2025 CSV ZIP | 1 | 1 | 100 MB | 10 min | one immutable download |
| EIA | latest annual residential prices for all states, first page | 1 | 1 | 10 MB | 3 min | sequential, ≤1 request/5 sec |
| EPA | availability plus one PM2.5 county/week API slice; bulk URL HEAD may replace availability | 2 | 2 | 50 MB | 15 min | strictly sequential, ≥5 sec between calls, ≤10/min |

A source passes calibration only when every requested payload validates, remains within
all caps, records zero `429`, has sanitized provenance, and produces at least one raw
and normalized row (bulk metadata-only requests are insufficient). Only rows owned by
passed sources are enqueued. Thus “enqueue all 46” means all rows whose source passed;
any remainder is `NOT_RUN` with the failed calibration evidence.

1. Materialize and validate the 81-row machine-readable contract without contacting
   providers.
2. Run 5–10 small slices locally: Census ACS, BLS LAUS, FBI CDE, CDC PLACES, BEA RPP,
   IRS SOI, USDA Food Environment Atlas, EIA Electricity, and EPA AQS/AirData. Prefer
   one immutable bulk download per release over per-geography API requests.
3. Produce the calibration report and calculate source-specific expected volume. A
   source with credential failure, unbounded pagination, or repeated `429` remains
   stopped while other independent sources continue.
4. Enqueue the subset of the 46 `run_now` ledger rows whose source passed calibration.
   Pack related source variables into a request/file job and derive rates locally; do
   not create 46 independent downloads when one official response contains them.
5. Persist raw artifacts atomically, then normalize. A job becomes complete only after
   payload validation, sanitized provenance, SHA-256, and manifest write.
6. Run the 81-row Eval. The local process may continue after this interactive turn;
   its PID/status file and progress command become the observable handoff.

The normalized uniqueness key is
`(geo_id, year, field_id, source_release)`. When one field intentionally emits several
source categories (for example age bands or sex categories), the category is part of
`field_id` as a deterministic child suffix while `catalog_field_id` retains the 81-row
parent. A completed immutable job is checked in the manifest before transport; the
resume test instruments transport and must observe zero calls for it.

## Deterministic 48-hour scale verdict

`SCALING-PLAN.md` uses the calibrated ledger and computes, per source:

`source_seconds = max(measured_seconds_per_job × remaining_jobs × 1.25,
documented_min_interval × remaining_requests, shared_quota_days × 86400)`

where `shared_quota_days = ceil(remaining_requests / documented_daily_quota) - 1` for
a documented daily quota and zero otherwise. Bulk parsing uses measured bytes/sec with
the same 25% retry/headroom factor. Storage is
`1.25 × (measured bytes/job × remaining jobs + immutable bulk bytes)` and must fit the
declared available capacity. Provider queues that may legally run in parallel overlap;
jobs sharing an account/application/provider limiter do not. The verdict is:

- `feasible` only when the critical path is ≤48 hours, storage fits, every required
  source has passed calibration, and no estimate relies on proxies or quota evasion;
- `not_feasible` when a measured or documented bound exceeds 48 hours or storage;
- `unknown` when a required cardinality, throughput measurement, access path, or limit
  is absent.

The plan separately reports both the 46-row current-run scope and all 81 rows, so a
`feasible` result for the accessible subset cannot be represented as feasibility for
the unresolved full catalog.

## Current official constraints used by the plan

- Census: pack at most 50 variables per query; a key is already configured. Geography
  batching is preferred to one request per place.
- BLS v2: 500 registered queries/day, 50 series/query, 20 years/query.
- EPA AQS: no more than 10 requests/minute, about five seconds between completed
  requests, at most five parameter codes per request, target under 1,000,000 rows.
- EIA: at most 5,000 JSON rows per response; paginate by documented offset/length.
- Socrata/CDC PLACES: use `X-App-Token`; stable pagination or bulk export. Authenticated
  traffic is not normally throttled unless abusive, but the runner remains bounded.
- FBI CDE: no numeric official quota was found in the checked material; v1 therefore
  uses one sequential worker at no more than one request/second and stops on any `429`
  or `Retry-After` response.
- BEA RPP: use one official immutable `SARPP.zip` download per release; the API is not
  used for row-by-row RPP collection.
- IRS SOI: use one official published release file; no request fan-out. The resolved
  download URL and release-page URL are both retained.
- USDA FEA: use the one official 2025 CSV ZIP (published as about 6.2 MB); no request
  fan-out, and every metric keeps its variable-list reference year.
- CDC WONDER: official API cannot group/filter NVSS mortality by state or county, so
  these rows cannot be fanned out through that API.
- BLS OEWS and HUD PIT: current automated access probes were blocked by Akamai/WAF;
  changing IPs is not the remediation.

Numeric limits are rechecked against official pages before the runner is finalized;
the scale report must distinguish documented limits from conservative local settings.

## Scope and exclusions

- This run covers the 81 catalog rows, not the separate 100-item future-layer backlog.
- Current target is the latest defensible nationwide release at each source's published
  geography. Cross-source years are not forced to match.
- No public publishing, app integration, recurring schedule, remote-server install,
  proxy purchase, or paid license is authorized in this task.
- The existing synthetic UI is unchanged.

## Portable maintainability impact

1. **Outcome/flow:** validate ledger → calibrate locally → enqueue accessible fields →
   inspect progress/Eval. Baseline is a 10-record pilot; delta is a resumable real run.
2. **Owners/consumers:** source adapters own acquisition rules; the ledger owns field
   definitions; normalization owns shared records; Eval reads only manifests and
   normalized output. The UI is not yet a consumer.
3. **Failure/rollback:** raw artifacts are append-only and hash-addressed; manifests are
   atomic; retry is idempotent; blocked sources do not poison independent sources.
   Removing the new collection directory restores the baseline without touching UI.
4. **Reuse/dependencies:** reuse pilot credential loading/redaction and Python standard
   library first. Add a parser dependency only if an official required format cannot be
   handled reliably otherwise; record version/license/update path if added.
5. **Tests/evidence:** ledger schema/counts, request sanitizer tests, mocked retry/resume,
   real bounded calibration, uniqueness checks, artifact hashes, and per-field Eval.
6. **Docs/contracts:** this plan and the task packet are added. README is updated only
   if a stable operator command or new dependency survives verification; project
   `AGENTS.md` is not affected because no durable workflow rule changes.
