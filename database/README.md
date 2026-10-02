# PostgreSQL storage

Current production measurements, all 81 catalog indicators, geography depth,
and the October storage work are in the
[2 October coverage and storage report](../research/2026-10-02/README.md).
The online index operation is recorded in the
[lookup-index migration note](LOOKUP-INDEX-MIGRATION.md).

## Automatic collection admission: v3 deployed

The additive v3 migration committed on 2026-10-01 at 08:50 UTC, and the
automatic timer is installed. The first real admission committed at 08:51 UTC.
Production, local schema and both legacy loaders have matching v3 pins.
See [the admission protocol](ADMISSION-PROTOCOL.md),
[the migration runbook](PIPELINE-MIGRATION.md), and
[the scheduled pipeline installer](../ops/install_auto_pipeline.py).

The v3 extension adds `usa_atlas_pipeline.dataset`, `snapshot_batch` and
`generic_record` in the same `usa_atlas` database. Canonical numeric rows continue
to use the compact observation table. Source records that do not fit the 81-field
catalog remain typed JSON records with source provenance. Missing or suppressed
canonical values are stored as quality records, never as numeric zero.

Read the latest completed generic source snapshot with:

```sql
SELECT r.dataset_key, r.record_key, r.payload
FROM usa_atlas_pipeline.generic_record r
JOIN usa_atlas_pipeline.dataset d
  ON d.dataset_key=r.dataset_key AND d.latest_snapshot_id=r.snapshot_id
WHERE r.kind='source_record';
```

Quality flags describe currently published canonical chunks, so read them without
the completed-snapshot join:

```sql
SELECT dataset_key, record_key, payload
FROM usa_atlas_pipeline.generic_record
WHERE kind='observation_quality';
```

During an unfinished refresh, quality rows may belong to both the previous and
the incoming snapshot. Each numeric replacement or invalidation and its quality
flag commit together. Old dataset-owned rows are pruned only after all source
ranges complete. Historical `ingest_run.row_count` remains the original artifact
count; current ownership and actual updates are tracked in `snapshot_batch`.

## Compact provenance storage (September 2026)

Production migration completed on **2026-09-29 at 15:17 UTC** with all 49,206,438
rows preserved, 101 exact ranges and zero mismatches. Facts, indexes and
dictionaries used 17.79 GB instead of 63.94 GB at that checkpoint. The subsequent
v3 extension preserves that compact representation; backups are retained. See the
[completed maintenance record](../research/2026-09-29/CLEANUP-NEXT.md).

New databases use `observation_data` as the physical facts table. Repeated URLs
and methodology notes live in `source_resource` and `methodology`; foreign keys
preserve every original value. The `observation` view exposes the same 13 columns
and canonical observation key used by existing readers. Imports still use the
unchanged staging tables and `finish_ingest`, which now deduplicates metadata.

`schema.sql` initializes an empty database. **Do not apply it to an existing v1
database.** The production migration requires a backup, exact preservation checks,
an atomic cutover, and the matching schema fingerprint in the loader. See the
[live operations report](../research/2026-09-28/LIVE-OPERATIONS.md) for execution
status. Audit disk space on `observation_data` and its dictionaries after cutover;
the compatibility view itself stores no observations.

The deployed loader already has additional append guards absent from this older
checkout. Migration stages a narrowly patched copy of that deployed loader so
those production safeguards remain present.

This directory stores the normalized collector output in PostgreSQL 16. The loader
uses only Python's standard library and the `psql` client. It admits a source only when
the run manifest marks it `pass`, the artifact and contract hashes match, and every row
belongs to that source's runnable catalog fields. Partial Census output is rejected.

The following legacy libpq example is only for an operator-created empty database
in a separate development environment. **It is not the production connection.**
Production automation uses only Docker container `usa-atlas-postgres`, database
`usa_atlas`; this host's localhost port 5432 belongs to a different service and
must not be used for USA Atlas maintenance.

Set any development libpq connection variables outside the project. The loader pins every
maintenance operation to `postgres` and every target operation to `usa_atlas`; do
not set `PGDATABASE` to redirect it. The guarded `load` command creates the target
database only after manifest/hash/contract validation, disk-headroom checks, and an
exact duplicate scan:

```bash
export PGHOST=localhost PGPORT=5432 PGUSER="$USER"
python3 database/load.py load --all
```

The legacy initial-load flow admits every currently completed source. A
single-source bootstrap is intentionally not exposed by the CLI because it would
leave a partial target that the guarded `--all` admission must reject:

```bash
python3 database/load.py load --all
```

After loading, run the fail-closed verifier. It checks exact totals, distinct
canonical keys, provenance, source-by-geography inventory, Census exclusion/inclusion,
and a second no-op `load --all` rerun:

```bash
python3 database/load.py verify --all
```

Loading is streaming and idempotent. Reusing the same passed artifact is skipped;
a new artifact is admitted only when the target already has a complete state for the
same selected manifest; matching canonical keys are protected by the database primary
key. A duplicate in the selected artifacts fails before PostgreSQL is created or
written. An advisory lock at `full/state/.usa-atlas-load.lock` serializes processes;
only one loader may run at a time.

Useful verification queries:

```sql
SELECT source, count(*) FROM usa_atlas.observation GROUP BY source ORDER BY source;
SELECT status, count(*), sum(row_count) FROM usa_atlas.ingest_run GROUP BY status;
SELECT count(*) FROM usa_atlas.catalog_field; -- 81
SELECT source, geo_type, count(*), count(DISTINCT geo_id)
FROM usa_atlas.observation GROUP BY source, geo_type ORDER BY source, geo_type;
SELECT count(*) - count(DISTINCT (geo_id, period, field_id, source_release)) AS duplicate_rows
FROM usa_atlas.observation; -- 0
```

Census becomes eligible automatically only after its final artifact is hash-bound and
the manifest source status is `pass`; partial Census output is never admitted.

Run the unit and temporary-PostgreSQL integration check:

```bash
cd database
python3 -m unittest -v test_database.py
```
