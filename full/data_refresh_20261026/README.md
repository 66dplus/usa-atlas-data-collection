# Local data refresh preparation, 2026-10-26

This package prepares the 42 published selections from the supplied scope. It does not write to a database, admit observations, or modify existing collectors or reader contracts. Collector version `2026.10.26.3`, reader contract version `1.0.0`, and each publisher's source release are independent identifiers.

## Run

For public, non-keyed preparation and FBI public state series:

```sh
env -u BLS_API_KEY -u EIA_API_KEY python3 full/data_refresh_20261026/refresh.py --max-bls-queries 0 --max-fbi-items 357
```

The parent has completed BLS collection. To import that run without issuing BLS requests, validate every response, and write a separate local runtime/inventory:

```sh
env -u BLS_API_KEY -u EIA_API_KEY python3 full/data_refresh_20261026/refresh.py \
  --max-bls-queries 0 --max-fbi-items 0 --skip-page-snapshots \
  --bls-prepared-dir /tmp/usa-maps-data-flow-20261026/keyed-collection/prepared \
  --bls-results /tmp/usa-maps-data-flow-20261026/keyed-collection/bls-full-results.json \
  --runtime-dir /tmp/usa-maps-data-flow-20261026/local-integrated-runtime \
  --inventory /tmp/usa-maps-data-flow-20261026/data-results.json
```

The BLS importer checks all 256 raw response hashes and sidecars, queue fingerprints, plan version, prepared file hashes, and semantic counts before copying the publisher-prepared files. It preserves the parent's artifacts and also writes `bls-laus-2025-loader.csv` and a missingness JSONL with source batch SHA-256, timestamp, series ID, request fingerprint, queue hash, and plan version on every row. Its status is `collection_complete_with_source_gaps`, not source-complete.

The worker never calls `load_credentials()` and never reads a credential file. It consumes only `BLS_API_KEY` and `EIA_API_KEY` from the process environment when present. It strips keyed URL parameters from metadata, suppresses raw request errors, and refuses to save a response containing a raw or URL-encoded injected credential. Registered BLS v2 requests batch at most 50 series and stop at 500 actual daily attempts; public requests stop at the public daily budget. Request failures count against the budget. BLS queue order, plan version, batch size, exact ordered series IDs, and raw SHA-256 are verified before resume. The separate runtime and inventory flags allow an independent parent run.

## Prepared sources and boundaries

- BLS LAUS 2025: NSA `LAUST` state series and `LAUCN` county series for unemployment rate, unemployed, employed, and labor force. Monthly observations are kept separate from official annual `M13`; October's published unavailable value stays missing. A missing M13 is never calculated from monthly rates.
- Census PEP Vintage 2025: annual 2023/2024 all-age population and county/state/national under-18 population from single ages 0–17. These are July 1 estimates; child-age counts use the both-sex rows only. Matching-year 2023 population is required for IRS per-resident income.
- IRS SOI 2023: all eight `agi_stub` rows are summed for county A00100; state and national totals sum counties only. Source thousand-USD values are multiplied by 1,000. Missing population does not yield a per-resident value.
- EIA Electric Power Annual 2025: sector ALL, states, annual prices. If `EIA_API_KEY` is injected the package uses the EIA API; otherwise it parses the official annual table. ALL-sector average retail prices are not residential-only tariffs.
- FBI annual 2025: the official SRS estimated-crimes workbook was retrieved from the CDE public catalog locator, preserved as raw bytes, and hash-verified (226,863 bytes; SHA-256 `e7bf3de96b21d00fc10e9d60fee4d8257cba0a095ce5c5fc992047d46fb76486`). Although its catalog filename and HTTP content-type say CSV, the bytes are OOXML XLSX and the parser detects the ZIP signature. The seven annual estimates use their official counts and same-row FBI population to calculate per-100,000 rates. The native US row is retained. Field 04.07 uses revised rape; legacy rape is not substituted. Source footnote markers and their text are retained: note 3 applies to both Florida and North Dakota, and note 4 applies to DC. Monthly reported counts are not summed or substituted.
- Retained USCS 2023, CDC AtlasPlus HIV 2024, and WONDER under-18 deaths 2024 observations are copied as exact prepared-source receipts, then recalculated with matching PEP denominators: 2024 total, age 13+, and under-18 as appropriate. HIV remains provisional. Child-death counts of 9 or fewer remain suppressed. The retained source snapshot hashes, raw publisher/replay response bytes, retrieval receipts, and citations are preserved. The AtlasPlus replay is the actual input for provisional 2024 HIV counts; the separately retained CDC workbook contains tables through 2023. These are prior evidence receipts, not a new fresh collection.
- ACS (2020-2024), PLACES (2023 BRFSS, December 2025 release), and BEA RPP (2024, February 19, 2026 release) are freshness-reviewed as unchanged, suitable current published releases. Their published snapshots are review evidence only, not new raw admissions. IRS, USCS, HIV, CDC WONDER, and USDA fitness are also reviewed. Fitness release metadata remains explicitly unverified; existing retained medical source counts are reused where fresh official downloads returned access errors.

ACS share numerators and denominators remain from their same ACS release; annual PEP denominators support matching-year IRS/medical rate calculations and do not replace ACS share denominators. Raw publisher bytes and derived files are written under ignored `full/runtime/data_refresh_20261026/`. Source hashes, URLs with credentials removed, retrieval timestamps, licenses/reuse notes, and missingness are included in runtime metadata. The machine-readable output inventory is `/tmp/usa-maps-data-flow-20261026/data-results.json`. `ready` is always false: local preparation is not admission, and any partial source or missing coverage remains unresolved.

`definition_matrix.json` records every one of the 42 published fields with freshness evidence, period types, latest suitable releases, release dates, limitations, and preparation status. Audit-only additions such as 2023 AGI per resident appear in `additionalRows`, separate from the published 42. `loader_input_mapping.json` defines stable field IDs, prepared columns, annual/monthly kind, adjustment, numerator/denominator, and provenance expected by reader v2. BLS components use canonical `03.06:*` IDs and do not reuse ACS IDs; source-derived IRS and medical fields use their explicit `07.01:derived:*` and `11.0*:derived` IDs. Medical, IRS, and EIA before/after files under the runtime preserve published snapshot values, prepared values, ranks, and unavailable geography flags. These snapshots are comparison evidence, not original producer admissions. Cancer uses 2023 cases and matching 2023 PEP population, including the actual publisher national count. HIV and child-death national rows are omitted because retained inputs have no publisher national count; state counts are not summed.

The package can import the verified raw workbook with `--fbi-annual-raw PATH`, or reuse `raw/fbi/estimated_crimes_1979_2025.bin` under the selected runtime when its SHA-256 matches. An optional `--download-fbi-annual` follows the public CDE signed-locator flow in memory; the signed locator is never logged or persisted. Annual input is prepared to `fbi-annual-estimates-2025.csv` (364 offense/geography rows: seven fields × 51 states/DC plus native US) and `fbi-2023-baseline-2025-annual-ranks.csv`. The latter is cross-product rank context only: its 2023 values are frozen published API evidence using a 2024 ACS denominator, while 2025 uses official FBI annual estimates and FBI source populations. No direct trend claim is made from those ranks.

Generated large and derived files remain in ignored/local runtime directories. The machine-readable inventory is `/tmp/usa-maps-data-flow-20261026/data-results.json`. `ready` is always false: local preparation is not admission, and incomplete source coverage remains unresolved.

## Checks

```sh
python3 -m unittest -v full.data_refresh_20261026.tests.test_refresh
```

## Immutable final inventory consolidation

`consolidate_inventory.py` creates a new versioned runtime from the correct integration inputs. It copies content-addressed source receipts, copies only the correctly bound prepared outputs, writes row counts and SHA-256 values, and validates every results output binding before publishing the inventory. It rejects duplicate prepared names, missing files, hash mismatches, mixed cancer inputs, and event/denominator year mismatches. It never rewrites an existing final runtime.
