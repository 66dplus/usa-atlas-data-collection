# County fallback for indicators below tract

This is the 2026-10-02 operating rule: when block-group and tract observations
cannot be obtained, seek a source with county FIPS and retain the finest
defensible geography. Do not copy state values into counties, allocate ZIP
values to counties without an approved crosswalk and weighting method, or
represent a monitoring station as a countywide exposure estimate.

The [current 81-field coverage](catalog-coverage-after-county.csv) has 19
fields with block groups, 7 with tracts but no block groups, 10 with counties
but no tracts, 10 with state data only, and 35 with no numeric rows. The
[55-field county fallback queue](county-fallback-status.csv) lists every field
without tract or block-group data, including the food fields excluded from
new collection. A `t` in coverage means some numeric rows exist, not complete
national county coverage.

## County values added on 2026-10-02

| Field | County source and calculation | Numeric rows | County FIPS |
|---|---|---:|---:|
| `07.01` AGI | IRS 2023 county table, sum `A00100` over published AGI bands 1–8 | 3,143 | 3,143 |
| `07.03` Capital gains | Same table, separately sum `N01000` and `A01000` | 6,286 | 3,143 |
| `07.04` Dividends | Same table, separately sum `N00600` and `A00600` | 6,286 | 3,143 |
| `09.06` PM2.5 | EPA 2025, largest arithmetic mean among qualifying complete monitors in each county | 555 | 555 |
| `09.07` Ozone | Same monitor rule | 721 | 721 |

IRS source: [2023 county AGI file](https://www.irs.gov/pub/irs-soi/23incyallagi.csv).
The county code `000` identifies state totals and is excluded. The two
capital-gains and dividend variables remain distinct count and dollar rows.
These county observations have source year 2023; existing ZIP observations
have source year 2022. `N00100` is not present in the county file, so no
unavailable return-count series was invented for `07.01`.

EPA source: [2025 concentration by monitor](https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_2025.zip).
The original ZIP contains 65,709 data rows; the lossless working table keeps
the 19,583 PM2.5/ozone rows and its original header.
The PM2.5 profile uses parameter `88101`, `PM25 Annual 2024`, quarterly means
of daily means, and 24-hour samples. The ozone profile uses parameter
`44201`, `Ozone 8-hour 2015`, daily maximum of 8-hour running average. Both
require `No Events` and `Completeness Indicator Y`. The county value is the
**maximum of the monitors' published `Arithmetic Mean`**, not the maximum
daily reading or an average over county residents. Only 555 and 721 counties,
respectively, have a matching complete monitor; other counties have no value.
The 2025 [EPA annual AQI by county](https://aqs.epa.gov/aqsweb/airdata/download_files.html)
is a different measure and cannot fill a PM2.5/ozone concentration gap.
The [EPA file format](https://aqs.epa.gov/aqsweb/airdata/FileFormats.html)
defines county code as the monitor's location.

The reviewed source-bound adapters are
[`prepare_irs_county_admission.py`](../../full/prepare_irs_county_admission.py)
and [`prepare_epa_county_admission.py`](../../full/prepare_epa_county_admission.py).
Both are registered in the scheduled pipeline with their code hashes. The
pipeline completed all 45 discovered candidates at 13:25 UTC on 2026-10-02.

## Remaining state-only fields

`02.10` regional price parities, `04.01`–`04.07` and `04.09` crime, and
`08.05` electricity price have state observations but no county observations.
The current state values cannot be relabeled as county values. BEA publishes
RPP for states and metropolitan areas ([BEA API](https://apps.bea.gov/api/signup/)),
so a county RPP needs a separate documented estimation method or a different
county indicator. FBI crime releases need agency jurisdiction, reporting
coverage and deduplication checks before county aggregation
([FBI NIBRS](https://nibrs.fbi.gov/)). EIA lists utility prices and the
counties where utilities operate, and notes that more than one utility may
serve a county ([EIA county-price FAQ](https://www.eia.gov/tools/faqs/faq.php?id=448&t=10));
this is not a directly measured county residential price. These remain in the
county-source queue. The 35 fields without numeric rows require their source,
access, definition, or license issue to be resolved first; four food-price
fields are outside the current collection scope.
