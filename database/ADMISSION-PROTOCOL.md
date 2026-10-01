# Automatic admission v1

CLI: `python3 database/auto_ingest.py --manifest PATH --apply --result PATH`.
The loader never bootstraps a schema during ingestion. v3 installation and pins
must already be deployed through the coordinated migration.

The UTF-8 JSON manifest has these fields:

```json
{
  "format": "usa_atlas_admission_v1",
  "status": "complete",
  "batch_id": "64 lowercase hexadecimal characters",
  "dataset_key": "stable/source/release/table",
  "kind": "observations",
  "source": "census_acs",
  "source_release": "2024-acs-acs5",
  "snapshot_id": "one SHA-256 shared by every chunk of this snapshot",
  "snapshot_at": "2026-09-29T00:00:00+00:00",
  "adapter_version": "adapter version",
  "adapter": {"path": "relative path to adapter", "sha256": "..."},
  "scope": {
    "type": "input_row_range",
    "start_row": 0,
    "end_row_exclusive": 1000,
    "total_input_rows": 1000
  },
  "completeness": {"complete": true, "basis": "source completeness evidence"},
  "contract": {"path": "field-contract.json", "sha256": "..."},
  "inputs": [{"path": "relative immutable input path", "sha256": "..."}],
  "observations": {"path": "observations.jsonl.gz", "sha256": "...", "rows": 1000, "bytes": 1234, "uncompressed_bytes": 5678},
  "quality": {"path": "quality.jsonl.gz", "sha256": "...", "rows": 0, "bytes": 20, "uncompressed_bytes": 0},
  "records": null
}
```

`kind` is `observations` or `records`. Records batches use `records` and may set
`contract`, `observations` and `quality` to null. Observations batches include
both observations and quality descriptors, including an empty quality artifact.
Payloads may be JSONL or gzip JSONL. Descriptors always count decompressed records.
All output payloads must be inside the manifest directory. Bound input, adapter
and contract paths may contain `..` but must resolve inside the repository.

The canonical wire format has the existing **12** fields:
`geo_id, geo_type, year, field_id, catalog_field_id, value, unit, source,
source_release, source_url, methodology_note, retrieved_at`.
The loader maps `year` to `period` and assigns `ingest_id`, giving 13 DB columns.
Quality rows have the same fields except `value`, plus `quality_status`,
`raw_value`, and `annotation`: 14 keys. Allowed status values are `missing`,
`suppressed`, `not_applicable`, `invalid`, `sentinel`. Raw source tokens and JSON
annotations are preserved. Numeric and quality records cannot share a canonical
key in the same snapshot. Missing values never become zero or numeric sentinels.
The national adapter emits `raw_value` as a string or null and `annotation` as
a JSON-encoded string or null.

Generic rows are `{ "record_key": "stable key", "kind": "source_record",
"payload": { ... } }`. Scope and payload carry the source's semantic category;
discovery catalog entries are not represented as measured observations.

Chunks of one snapshot share `dataset_key`, `snapshot_id`, `snapshot_at`, source,
release, contract and total input row count. Each has a unique stable `batch_id`
and nonoverlapping input range. The last chunk alone cannot mark a snapshot
complete: committed ranges must cover `0..total_input_rows` without gaps.
`completeness.complete=true` proves an individual chunk, not the entire dataset.
Final snapshot completion is determined inside the DB transaction. Empty full
snapshots are represented by the sole range `0..0` with explicit source proof.

Batch IDs bind source input hashes, adapter version/hash, contract hash, scope
range, and output hashes. Snapshot IDs exclude chunk ranges/output hashes and
bind the entire immutable source snapshot. Paths and preparation wall-clock time
do not define identities. Files/manifests in a prepared batch directory must stay
immutable. A different manifest representation with the same exact admission
semantics can return `already_pass`; conflicting reuse of a batch ID is rejected.

The output row cap applies to **observations + quality + generic records**;
wide Census tables must not expand 250,000 input geographies into tens of millions
of rows in one transaction. Adapters stop on a whole input record boundary.

Success output statuses are `pass` / `already_pass` (exit 0). Retryable outcomes
are `transient_failure` / `deferred_maintenance` (exit 75), including a
`retry_after_seconds` value. Invalid or ambiguous content returns `quarantine`
(exit 65). Reports include reason, batch/dataset IDs, manifest and artifact SHA,
row counts, ingest ID and whether the complete snapshot was committed.
Without `--apply`, the result is `plan` (exit 0); this is validation evidence,
not a database admission receipt and cannot authorize payload retention cleanup.

The loader takes the local and deployed loader flocks and advisory lock
`66280928`, verifies v3 schema/catalog pins, streams COPY into transaction-local
staging, validates keys and provenance, then atomically publishes the chunk.
Each SQL statement has a ten-minute timeout; idle transactions expire after
60 seconds. Shutdown cancellation is restricted to this invocation's unique
application name, backend PID and database.
Legacy key adoption is available only to the bound reviewed national adapter and
requires identical source/catalog/geography identity. Other source/dataset key
ownership conflicts are rejected. Old dataset-owned keys are deleted only after
all chunks of a new snapshot have committed. Original legacy ingest row counts
remain historical admission counts. Old production load/append commands must
decline pipeline-managed state and direct operators to this loader.

Readers of `generic_record.kind='source_record'` join `dataset.latest_snapshot_id`
to `generic_record.snapshot_id` to read the latest complete snapshot. An
incomplete newer snapshot does not replace it. After completion, old source
payloads are removed; at most the latest three snapshot ledgers are kept.
Retried older snapshots cannot roll back newer data.

Quality readers filter `kind='observation_quality'` by dataset and canonical key,
without a latest-complete-snapshot join. Canonical chunks and their quality flags
become visible atomically per chunk. During a refresh, current quality rows can
span old and new snapshot IDs; filtering by the latest completed snapshot would
hide a newly missing value after its numeric observation was removed. Dataset
completion is explicit and never inferred from one chunk.

Use one partitioning policy per dataset snapshot. The scheduled queue uses its
250,000-input cap plus the adapter's 250,000-output cap. Reference bundles made
with a different input cap are not mixed into this queue: overlapping ranges or
conflicting semantic reuse of a batch ID are rejected, rather than double loaded.
