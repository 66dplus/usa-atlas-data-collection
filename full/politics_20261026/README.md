# Politics and AIAN preparation (reader v2 candidate)

Status: `2.0.0`, local review only, not admitted or released. The preparation emits deterministic JSONL from already prepared local research files; it does not collect, admit, deploy, or access a live database.

## Reproduce locally

```sh
python3 full/politics_20261026/prepare.py \
  --input-dir /path/to/politics-native \
  --output-dir /path/to/new-empty-output \
  --county-geography-contract full/politics_20261026/county-geography-contract.json \
  --boundary-zip /path/to/cb_2024_us_cd119_500k.zip \
  --house-official-metadata /path/to/pinned-IG0UN2-v15-metadata.json
```

The boundary ZIP must match the pinned Census SHA-256 in `prepare.py`. Alternatively supply `--boundary-geojson PATH --boundary-geojson-sha256 HASH` with an exact trusted hash. Missing, malformed, or mismatched geometry fails closed. Supply the pinned public Dataverse v15 metadata JSON with `--house-official-metadata`; the command reconstructs and verifies the original source byte identity before producing output. Output must be a new or empty directory. Inputs and output paths are explicit; the repository has no machine-specific data path defaults. `validate_real.py` is a separate optional check that compares all 33,805 House output source records to the prepared CSV, verifies the DC identity/share, and checks the US AIAN input control.

## Prepared election contract

All prepared history is retained: President 2000–2024 (94,151 rows), House 1976–2024 (33,805), Senate 1976–2024 (3,945). `csv.DictReader` parses each normalized prepared file and the validator checks exact source-record equivalence for every House row. The original raw-source SHA remains in the inventory. Candidate `candidatevotes` and per-row `totalvotes` text, original party, normalized party, source version, stage, special/runoff flags, mode, write-in/fusion flags and the complete prepared row are retained. The selected-party vocabulary emits `DEMOCRAT` and `REPUBLICAN` for the current app selector.

Contest adjudication uses only `TOTAL`. It stores one consistent positive denominator at contest grain, never sums repeated `totalvotes`, never adds mode subtotals, sums candidate votes by normalized party, and divides by all contest votes. A fusion flag alone is not a quarantine: distinct source candidate rows remain adjudicable when candidate/party identities are clear. Duplicate ordinary candidate/party rows, cross-party ambiguity, invalid values, inconsistent denominators, unknown parties, and candidate totals exceeding the reported total quarantine the aggregation. Raw source-value validity remains separately recorded. An absent party becomes an observed zero only for a validated complete contest; otherwise share and votes remain null. `election_availability` distinguishes explicit Senate no-election from missing scheduled source observations.

Blank source election modes remain a distinct `UNSPECIFIED` contest and are quarantined with `source_mode_unspecified`; the raw blank mode and valid numeric candidate values are both preserved. They are not treated as `TOTAL`. For 2024 President, 3,154 county IDs include 2,778 counties with explicit `TOTAL`, 367 blank-only counties, and 9 vote-center-only counties. Publisher semantics for the blank mode remain unverified, so no party share or absent-party zero is inferred for those contests.

Field IDs coordinate with the current application catalog: AIAN extends `01.04` (`aian_broad_share` / `01.04:aian_share`); President is `12.01`, Senate `12.02`, House `12.03`. Existing `11.01`–`11.03` have other meanings and are not reused.

2024 general House records map to exact Census 119th Congress feature IDs. An at-large district is `00`; DC is Census `1198` (nonvoting delegate), never fabricated `1100`. No county geometry substitutes for House districts. Historical House observations have no 2024 boundary join. The 2024 Census CD119 boundary has 441 features and is pinned to SHA-256 `2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a`.

## AIAN definition and geography

AIAN broad share is B02010_001E / B01003_001E × 100 from the same 2024 ACS 5-year product, at nation, state, and county levels. The metric includes AIAN alone or in combination and all Hispanic origins; race responses overlap, so shares are not expected to sum to 100%. Raw estimate and MOE fields are retained, with no derived share MOE. The prepared US estimate `7,990,799` is only a source-file control. Exact county FIPS matching preserves 3,133 matched source IDs and 11 source-only IDs as nonmapping; no value is redistributed to another county. The Census 2017 county map has nine map-only IDs. Source and map geography differences remain explicit.

## Provenance and limits

- President mirror bytes and MD5 match the public Dataverse VOQCHQ version 20 metadata; no guestbook submission was made.
- Senate prepared bytes and SHA-256 match the official public download. The metadata MD5 describes a distinct processed serialization; that distinction is recorded rather than used to block the byte-verified download.
- House v15 identity is verified by deterministic single-string-column reconstruction from the pinned mirror, matching official original size, MD5, SHA-256 and one-column UNF. Preparation and admission execute the check; no guestbook submission was made.
- AIAN raw US/state/county inputs retain their SHA-256 values in the source inventory.

Collector preparation version, reader contract version, and each source observation release are separate. The local loader is a guarded disposable-review utility only; it labels its batch `local_review`. Its successful local load is not production admission. Application queries must filter through `ingest_run.status='pass'` and `reader_batch.candidate_status='admitted'` after a separately reviewed release.
