# Local data refresh preparation, 2026-10-26

This package prepares the 42 published selections from the supplied scope. It does not write to a database, admit observations, or modify existing collectors or reader contracts. Collector version `2026.10.26.1`, reader contract version `1.0.0`, and each publisher's source release are independent identifiers.

## Run

For public, non-keyed preparation and FBI public state series:

```sh
env -u BLS_API_KEY -u EIA_API_KEY python3 full/data_refresh_20261026/refresh.py --max-bls-queries 0 --max-fbi-items 357
```

For the parent’s secure keyed collection, reuse the reviewed local runtime (including the completed FBI raw snapshots) while writing a distinct inventory:

```sh
python3 -c 'import sys; sys.path.insert(0, "pilot"); import run_pilot; run_pilot.load_credentials(); sys.argv=["refresh.py", "--runtime-dir", "full/runtime/data_refresh_20261026", "--inventory", "/tmp/usa-maps-data-flow-20261026/keyed-results.json", "--max-bls-queries", "500", "--max-fbi-items", "0"]; from full.data_refresh_20261026.refresh import main; raise SystemExit(main())'
```

The worker never calls `load_credentials()` and never reads a credential file. It consumes only `BLS_API_KEY` and `EIA_API_KEY` from the process environment when present. It strips keyed URL parameters from metadata, suppresses raw request errors, and refuses to save a response containing a raw or URL-encoded injected credential. Registered BLS v2 requests batch at most 50 series and stop at 500 actual daily attempts; public requests stop at the public daily budget. Request failures count against the budget. BLS queue order, plan version, batch size, exact ordered series IDs, and raw SHA-256 are verified before resume. The separate runtime and inventory flags allow an independent parent run.

## Prepared sources and boundaries

- BLS LAUS 2025: NSA `LAUST` state series and `LAUCN` county series for unemployment rate, unemployed, employed, and labor force. Monthly observations are kept separate from official annual `M13`; October's published unavailable value stays missing. A missing M13 is never calculated from monthly rates.
- Census PEP Vintage 2025: annual 2023/2024 all-age population and county/state/national under-18 population from single ages 0–17. These are July 1 estimates; child-age counts use the both-sex rows only. Matching-year 2023 population is required for IRS per-resident income.
- IRS SOI 2023: all eight `agi_stub` rows are summed for county A00100; state and national totals sum counties only. Source thousand-USD values are multiplied by 1,000. Missing population does not yield a per-resident value.
- EIA Electric Power Annual 2025: sector ALL, states, annual prices. If `EIA_API_KEY` is injected the package uses the EIA API; otherwise it parses the official annual table. ALL-sector average retail prices are not residential-only tariffs.
- FBI CDE 2025: resumable monthly counts and rates for the seven selected offenses in 50 states and DC. The FBI released annual CIUS estimates on August 14, 2026, but this package has not captured and verified a state-by-offense annual table. The inventory keeps annual FBI readiness unresolved; it never sums rates or treats monthly coverage as annual admission.
- Retained USCS 2023, CDC AtlasPlus HIV 2024, and WONDER under-18 deaths 2024 observations are copied as exact prepared-source receipts, then recalculated with matching PEP denominators: 2024 total, age 13+, and under-18 as appropriate. HIV remains provisional. Child-death counts of 9 or fewer remain suppressed. The retained source snapshot hashes and original publisher citations are preserved; these are prior prepared observations, not original publisher-file bytes.
- ACS, PLACES, BEA, IRS, USCS, HIV, CDC WONDER, and USDA fitness freshness findings are included in the 42-row matrix. Fitness release metadata remains explicitly unverified; retained medical source snapshots are used even where fresh official downloads returned access errors.

ACS share numerators and denominators remain from their same ACS release; annual PEP denominators support matching-year IRS/medical rate calculations and do not replace ACS share denominators. Raw publisher bytes and derived files are written under ignored `full/runtime/data_refresh_20261026/`. Source hashes, URLs with credentials removed, retrieval timestamps, licenses/reuse notes, and missingness are included in runtime metadata. The machine-readable output inventory is `/tmp/usa-maps-data-flow-20261026/data-results.json`. `ready` is always false: local preparation is not admission, and any partial source or missing coverage remains unresolved.

`definition_matrix.json` records the definitions and denominators of all 42 published fields, including freshness review status, period types, latest suitable releases, release dates, limitations, and preparation status. `loader_input_mapping.json` describes prepared-file field mapping to reader v2, including annual/monthly separation, adjustment, numerator/denominator, and provenance. `eia-2024-2025-before-after-ranks.csv` compares the existing published ALL-sector 2024 state values/ranks with prepared annual 2025 values/ranks. `fbi-2023-baseline-2025-annual-pending.csv` retains prior published 2023 values/ranks and null 2025 annual values until the official state-by-offense CIUS estimate table is verified/captured. Existing monthly 2025 CDE series are not used as annual substitutions.

## Checks

```sh
python3 -m unittest -v full.data_refresh_20261026.tests.test_refresh
```
