# PostgreSQL storage

This directory stores the normalized collector output in PostgreSQL 16. The loader
uses only Python's standard library and the `psql` client. It admits a source only when
the run manifest marks it `pass`, the artifact and contract hashes match, and every row
belongs to that source's runnable catalog fields. Partial Census output is rejected.

Set any libpq connection variables outside the project. The loader pins every
maintenance operation to `postgres` and every target operation to `usa_atlas`; do
not set `PGDATABASE` to redirect it. The guarded `load` command creates the target
database only after manifest/hash/contract validation, disk-headroom checks, and an
exact duplicate scan:

```bash
export PGHOST=localhost PGPORT=5432 PGUSER="$USER"
python3 research/data-collection/database/load.py load --all
```

The production operator flow always admits every currently completed source. A
single-source bootstrap is intentionally not exposed by the CLI because it would
leave a partial target that the guarded `--all` admission must reject:

```bash
python3 research/data-collection/database/load.py load --all
```

After loading, run the fail-closed verifier. It checks exact totals, distinct
canonical keys, provenance, source-by-geography inventory, Census exclusion/inclusion,
and a second no-op `load --all` rerun:

```bash
python3 research/data-collection/database/load.py verify --all
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
cd research/data-collection/database
python3 -m unittest -v test_database.py
```
