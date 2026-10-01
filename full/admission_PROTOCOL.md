# National ACS/CDC admission adapter

`prepare_admission.py` converts completed, hash-verified national collection artifacts into the `usa_atlas_admission_v1` protocol agreed with `database/auto_ingest.py` and `ops/auto_pipeline.py`. It makes no database connections and changes no source artifacts or collector configuration.

## Scope and identities

Discovery currently finds 22 source jobs: 19 ACS tables, the B17021/B05012 extensions, and CDC PLACES tract. Every source run/job must be complete; raw and normalized byte sizes/SHA-256, original collector/contract bindings, and required metadata are checked. A failed or incomplete run is never a ready candidate. Food IDs are excluded.

ACS uses the existing production convention, confirmed against `/srv/usa-atlas/artifacts/census_acs.jsonl.gz`:

- `field_id = <existing catalog parent>:<actual Census variable with E or M suffix>`;
- `source = census_acs`, `source_release = 2024-acs-acs5`, `year = 2024`, `unit = source_defined`;
- one scalar record per requested estimate or MOE, mapped to every existing contract parent that requests that variable. Age/Sex and other shared source series retain the existing parent mappings;
- B17021 uses parent 02.08 and its actual B17021 variable IDs; B05012 uses 01.05 and its actual B05012 IDs. Their identities are not renamed to B17001/B05002. Equivalence metadata must show no common county/tract mismatch;
- no ratios, growth, shares or other unimplemented formulas are invented.

CDC uses distinct `05.14/05.15/05.16:crude_prevalence` series, with `:ci_low` and `:ci_high` components. Its observation year is 2023, tract vintage 2023, release `PLACES-2025`, unit `%`. These keys do not overwrite the older county age-adjusted series.

Native GEOIDs remain strings: nation `US`, state 2 digits, county 5, place 7, tract 11, BG 12. No geography is manufactured or downscaled.

## Numeric and quality records are an atomic pair

The existing wire format has **12 keys**; the server adds `ingest_id` to form the 13-column database representation:

```text
geo_id geo_type year field_id catalog_field_id value unit source
source_release source_url methodology_note retrieved_at
```

`observations.jsonl.gz` contains finite observed numbers only. The old artifact contains numeric `-555555555` MOE sentinels; the new adapter represents those as quality, never as numeric estimates or zeros.

`quality.jsonl.gz` has the same keys except `value`, plus `quality_status`, `raw_value`, and `annotation` — **14 keys**. Status is one of `missing`, `suppressed`, `not_applicable`, `invalid`, `sentinel`. The exact source token remains a string or null. `annotation` is a JSON string retaining the exact source status and annotation availability. Missing CDC confidence intervals retain their raw CI text. For ordinary observed ACS values, source annotation availability is explicit in methodology.

Both files are required, including an empty quality file. Admission must apply them atomically. Quality for an existing matching source/catalog/key must replace the misleading old numeric sentinel through the loader's approved correction path; it is not an ordinary zero-valued observation. Cross-source/cross-dataset overwrite is outside this adapter's authority.

## Commands

```bash
python3 full/prepare_admission.py discover --json

python3 full/prepare_admission.py prepare \
  --candidate full/runtime/admission-20260929-refrozen/acs-summary-B01003-candidate.json \
  --out full/runtime/admission-20260929-refrozen/B01003-000000000000 \
  --max-rows 100000 --cursor null
```

`discover` returns `{ "candidates": [...], "blocked": [...] }`. Each candidate has a stable `dataset_id`, content `revision`, source manifest path/hash, and source artifacts with path/bytes/hash. Candidates are immutable descriptions of the exact input revision. Every manifest/job failure is isolated in `blocked`, with `dataset_id`, `source_manifest_path`, `status`, `reason`, and diagnostic `error`; healthy jobs remain discoverable. Missing or incomplete manifests are visible rather than silently skipped. Discovery exit 0 means the scan completed; consumers must inspect `blocked` to distinguish full readiness from partial readiness.

`--max-rows` bounds **input CSV rows**. An additional fixed limit of **250,000 combined numeric + quality output records** stops only between complete input rows. This bounds shared-variable parent expansion. The returned opaque cursor contains the next input-row index, uncompressed gzip offset, source/header hashes, and previous-line anchor; pass it unchanged as JSON. Gzip seeking can decompress the preceding prefix again, but does not materialize a full source file or all observations in memory.

Each output directory is bound to candidate, adapter code, cursor, and limits. Repeating the identical request verifies source/output hashes and reuses the complete bundle. A different request requires a different output directory. Incomplete temporary files never become a complete admission manifest.

## Bundle protocol

`admission-manifest.json` is published atomically only after streaming validation, completion of both gzip outputs, and a second verification of source hashes. It includes:

```text
format=usa_atlas_admission_v1, status=complete, kind=observations
batch_id, snapshot_id, dataset_key, source, source_release, snapshot_at
adapter_version, adapter={path,sha256}
scope={type:input_row_range,start_row,end_row_exclusive,total_input_rows,...}
completeness={complete:true,basis:...}
contract={path,sha256}, inputs=[{path,sha256,bytes},...]
observations={path,sha256,rows,bytes,uncompressed_bytes}
quality={path,sha256,rows,bytes,uncompressed_bytes}
records=null
```

`dataset_key` is the stable source/release/table identity. `snapshot_id` includes input hashes, adapter version/code and contract, and remains the same across chunks. `batch_id` includes snapshot identity, row interval and output hashes, without preparation timestamps or filesystem paths. `snapshot_at` is the source retrieval watermark. Equal snapshot timestamps permit multiple chunks; older snapshots must not roll back newer admitted data.

`completeness.complete` refers to the exact **bounded interval**, not an entire national dataset. Dataset completion/GC requires all intervals from 0 to `total_input_rows` under the same snapshot. Do not publish a partial snapshot as national completion.

`prepare-result.json` provides the orchestrator interface:

```text
status=ready, manifest=admission-manifest.json, manifest_sha256
next_cursor=<object|null>, complete=<dataset EOF>, prepared_rows
prepared_input_rows, observation_rows, quality_rows
request_sha256, batch_id, snapshot_id
```

Source inputs and adapter paths are relative to the manifest directory and may contain `../`, resolving within the repository. Output paths are local to the batch directory. The contract is copied into the batch and checked against the original input hash. Runtime bundles remain under ignored `full/runtime/`.

Exit 0: ready/discovery success; 65: quarantine/schema/hash/cursor failure; 75: transient filesystem/resource failure. A per-output-directory `flock` prevents concurrent preparation. At least 1 GiB disk headroom is maintained. This adapter does not install a timer or run tests; the orchestrator owns scheduling, retries, and calls to the transactional loader.

Preparation failures emit JSON on stdout and stderr with `status`, machine-readable `reason`, `error`, and `retry_after_seconds`. When the batch lock is held and the filesystem permits it, the same failure is atomically saved to `prepare-result.json`. A previously ready result is never overwritten with an error. Invalid cursor types and malformed/empty CSV input are quarantined without publishing a complete bundle.

Changing this adapter's code changes its pin and snapshot identity. Bundles prepared with an earlier code hash remain immutable historical artifacts and must not be passed to the current loader; regenerate into a new directory after coordinating the scheduler pin. The completed CDC/B01003 bundles in `full/runtime/admission-20260929/` predate the discovery isolation fix and are obsolete for current admission.

## Current prepared reference artifacts — 2026-09-29

The current adapter SHA-256 is `a02d1f4f1ec1990797f4227c13ae7810a81079f1c84394d65c5e506909b7afad`. Discovery under this code returned 22 candidates and no blocked jobs. Full operational preparation produced these immutable bundles under `full/runtime/admission-20260929-refrozen/`:

| Source job | Complete input rows | Bundles | Numeric records | Quality records | Combined gzip bytes |
|---|---:|---:|---:|---:|---:|
| CDC PLACES 2025 tract | 250,566 | 4 | 709,335 | 42,363 | 11,981,789 |
| ACS B01003 | 363,284 | 4 | 723,252 | 3,316 | 8,559,739 |

`preparation-summary.json` lists exact manifest paths, manifest hashes, contiguous input ranges, and snapshot IDs. These counts describe prepared files, not admitted database rows. No tests or database writes were performed by this adapter work.

**Use only bundles produced by the scheduled pipeline for admission.** The standalone bundles above are `reference_only_not_for_scheduler_admission`: they use a 100,000 input-row cap, while the scheduled pipeline uses 250,000. Mixing those bundles under the same snapshot creates incompatible partitions (B01003) or the same batch identity with different operational scope (CDC). They must not be loaded before, alongside, or as a continuation of scheduler bundles. The scheduler's consolidated report is authoritative for scheduled admission readiness.
