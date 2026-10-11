# Map national values, AGI and comparison policies — D3, D4, D6

This opt-in data consumer work does not change ingestion, database schema,
production observations, or the UI adapter. It is tied to the frozen
`app-collected35-20261011` source snapshot, rather than assuming the later medical
38-field publication is the same application. Production reads used Docker
`usa-atlas-postgres`, database `usa_atlas`, a `REPEATABLE READ READ ONLY`
transaction for the 35-field audit, 15-second statement timeouts and 2-second lock
timeouts. Additional component/quality probes used single-query read-only
transactions with tighter timeouts.

## Evidence and reproduction

- `selected-series-audit.json`: all 35 selected subseries, exact snapshot identity,
  stored units, native nation/state/county counts, official Oregon/US example
  observations, and bounded presence probes for other levels. A presence `true`
  confirms the exact subseries/period/release, not merely its parent. The scan
  count is **parent-range rows examined**, not selected-series observations. A
  `null` means the 1,000-row probe cannot establish presence; it is not absence.
- `http-snapshot-crosscheck.json`: the root session's SHA-bound deployed API
  manifest. **All 35 field IDs, periods, releases and stored units match** the
  read-only audit. API state counts exclude Puerto Rico and canonicalize BEA/EIA
  national codes; native database counts preserve these rows.
- `aggregate-evidence.json`: exact underlying inputs and hashes, BLS national
  derived value, IRS source-cell review and raw-state candidate.
- `d2-oregon-national-components.json`: 204 bounded live ACS estimate/MOE rows
  for education, poverty, tenure, rent burden and $200k+ formula examples. These
  were supplied to the separate metric-contract session.
- `quality-evidence.json`: indexed canonical-key probes for the seven counties
  missing selected median rent values compared with population coverage. All
  seven have stored `invalid` quality records. Missing numeric rows alone are
  therefore not labeled suppression. Original sentinel tokens and source
  annotations remain in the evidence.

```bash
python3 database/audit_map_data.py \
  --runtime /opt/usa-atlas-paper-runtime-20261009/app-collected35-20261011 \
  --out research/2026-10-11/map-aggregates/selected-series-audit.json

python3 database/build_map_aggregate_evidence.py \
  --audit research/2026-10-11/map-aggregates/selected-series-audit.json \
  --source-root /path/to/full/runtime/public-20260928 \
  --irs-guide /path/to/23incydocguide.docx \
  --out research/2026-10-11/map-aggregates/aggregate-evidence.json

python3 -m unittest -v database.test_map_aggregates
```

The raw IRS artifacts stay in the existing collector workspace. Their manifest
hashes are verified before reuse. The reviewed
[2023 IRS county guide](https://www.irs.gov/pub/irs-soi/23incydocguide.docx) is
pinned by SHA-256 in the evidence builder; a changed guide requires a new review.
The audit's initial source discovery uses state ranges, with county ranges for
native county-only AGI and fitness. This bounded discovery does not by itself
prove that another geography has no newer release; the independent API snapshot
cross-check establishes the match with the current deployed selector.

## D3: use official US observations before deriving anything

23 selected ACS series have native national rows in the exact ACS 2024
five-year publication. Their reference period remains **2020–2024**, even though
the database's period key is `2024`. BEA all-items RPP and EIA all-sector
electricity also have published US values, encoded in stored `state` rows with
IDs `00000` and `US`. The pure `select_national` function recognizes only these
verified source aliases, requires the exact field/definition/source/period/
release/unit/universe/adjustment, and retains original geography provenance.
It rejects ambiguous duplicates and derived rows. Units such as
`source_defined` must first be resolved by the checked metric registry.

The current BLS selected series has no published national row. The validated
sum over **50 states plus DC**, excluding Puerto Rico (`72`) and every county,
is:

| Component | December 2024, BLS-LAUS-2024 |
|---|---:|
| Unemployed people | 7,064,407 |
| Civilian labor force | 170,575,454 |
| Derived unemployment rate | 4.141514405701069% |

The inputs are state `LASST` series, which are **seasonally adjusted**. This is
an explicitly derived sum of state counts; it is not labeled an official CPS
national estimate. [BLS methodology](https://www.bls.gov/lau/laumthd.htm) and
[seasonal-adjustment guidance](https://www.bls.gov/lau/lauseas.htm) distinguish
state SA series and national controls. The NSA real-time benchmarking relationship
does not establish equivalence of this SA aggregate with a separately published
CPS national rate. Published rounded state percentages are retained independently.

The function fails for missing DC, duplicate states, extra territories, county
rows, incompatible releases/periods/definitions/adjustment, suppressed or invalid
counts, and nonpositive denominators. It never averages percentages or combines
state and county counts. National availability of the other source families must
be established from their own official series; no generic sum is permitted.

## D4: Oregon AGI is a disclosed publication sum, with a separate state candidate

All 36 Oregon county IDs have all eight mutually exclusive source AGI classes;
there are 288 published county cells, no duplicate classes and no explicit
nonnumeric A00100 tokens. Every live county value matches its hash-bound raw
source sum.

| Result | Thousand USD |
|---|---:|
| Sum of disclosed county A00100 values | 181,860,432 |
| Same county-file state-code-000 classes, excluded from county aggregation | 181,860,432 |
| Separate native IRS state table, Oregon AGI_STUB=0 | 181,808,743 |
| County publication minus separate state table | 51,689 |

The county sum is **$181.860432 billion in published disclosure-protected
amounts**. Same-publication state-code-000 matching is reconciliation evidence;
it does not prove complete underlying taxpayer amounts or make the separate
state publication interchangeable. The derived result records complete
geographic coverage, unknown underlying amount completeness, and
`usable_as_full_statewide_tax_total=false`.
The aggregate validates the fixed disjoint county FIPS roster directly and
performs no geometry join. Its unknown boundary vintage remains explicit;
this does not certify a map boundary join or a county comparison domain.

Three published zero band cells occur at 41021/class 1, 41055/class 1 and
41069/class 8. The IRS guide explains that small classes may be combined, small
county items excluded and dominant individual cells protected. Thus an explicit
numeric source token is preserved, while true underlying zero/suppression cannot
be inferred from CSV token alone. No protected cell is reconstructed. Returns
with missing/unmatched ZIP codes and certain non-US addresses are excluded; tax
return addresses do not necessarily represent residence or the full population.
These limitations are documented by the
[IRS county publication](https://www.irs.gov/statistics/soi-tax-stats-county-data-2023).

The existing separate state artifact
[`23in55cmcsv.csv`](https://www.irs.gov/pub/irs-soi/23in55cmcsv.csv) supplies
Oregon's native all-AGI row and N1=2,067,600 rounded returns. Its exact raw
tokens, artifact hashes and URL are preserved as an **unadmitted candidate**.
It is not silently substituted for county totals. **Total AGI versus AGI per
return remains a product decision**; no denominator or per-return result has
been selected. N1 is not silently substituted for N00100.

## D6: statistical domains and compatibility, without UI changes

`database/map_quality.py` compares only equal exact field/definition, source,
period, release, universe, unit, statistic, adjustment, geography level and
verified geographic vintage. Formula-derived fields get the stable identity
provided by the metric registry. The registry's explicit `comparison_record`
bridge supplies `MetricObservation`; it never guesses source geography from the
UI's 2017 geometries. Unknown geographic vintage remains unknown and blocks a
verified comparison/domain.

Missing observations, suppression, unavailable geography and load errors have
different reasons. Zero is an observed number. Share differences are reported
in percentage points. Median source values cannot be averaged into a new
regional median by the aggregate policies.

`summarize_domain(..., geo_type='state'|'county'|...)` chooses one level before
computing minimum/maximum/median and competition ranks. It rejects mixed
definitions/snapshots/units and duplicate geography IDs. Ties share rank; the
next rank skips tied positions. Rank means descending numerical magnitude, not
desirability. Sorting is O(n log n), avoiding quadratic tract/BG ranking costs.
The actual BLS state distribution is included in the evidence. The IRS county
domain remains blocked by unknown geographic vintage until that source metadata
is verified; raw county values remain accessible.

These functions return descriptive statistics and preserved values. Color ramps,
visual scaling, map/Compare presentation and integration with the UI are still
frontend work. The current UI's mixed state/county min/max policy is not changed
by this data commit.

## Validation

16 unit tests cover exact national field identity, aliases and ambiguity;
weighted counts and complete state coverage; suppression, invalid values and
geography mixing; AGI source review and reconciliation; separate missingness
reasons; percentage-point differences; level-specific domains, ties and constant
values. Live evidence additionally verifies all 35 snapshots against the deployed
read-only adapter, 102 BLS count inputs and 36 Oregon county source totals.
