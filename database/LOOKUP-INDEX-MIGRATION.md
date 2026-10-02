# Compact observation lookup index

Applied online to the production `usa_atlas` database on 2026-10-02. The
measured outcome and coverage snapshot are in
[`research/2026-10-02`](../research/2026-10-02/README.md).

The old index stored `value`, `unit`, `field_id`, and `source_release` in every
lookup entry. Those columns are already in the heap and do not participate in
the lookup key. Omitting them permits B-tree duplicate-key compression. The
resulting index has the same lookup prefix:
`(catalog_field_id, geo_type, geo_id, period DESC)`.

The production operation was:

```sql
CREATE INDEX CONCURRENTLY observation_lookup_compact_idx
  ON usa_atlas.observation_data
  (catalog_field_id, geo_type, geo_id, period DESC);
-- Confirm pg_index.indisvalid and pg_index.indisready are both true,
-- and inspect pg_get_indexdef before proceeding.
DROP INDEX CONCURRENTLY usa_atlas.observation_lookup_idx;
ALTER INDEX usa_atlas.observation_lookup_compact_idx
  RENAME TO observation_lookup_idx;
```

`CREATE INDEX CONCURRENTLY` and `DROP INDEX CONCURRENTLY` must each run outside
a transaction. Do not replay these statements blindly: on the current database
`observation_lookup_idx` is already compact, and the intermediate name is
absent. A failed concurrent build can leave an invalid intermediate index; drop
that index concurrently before retrying. Keep sufficient free disk for both
indexes and PostgreSQL's temporary sort files until the switch completes.

This operation changes only the index. The loader's `schema.sql` byte hash is
still pinned by `database/pipeline-schema-manifest.json`; changing that file
alone would stop automatic admissions. On a new installation, update the
bootstrap DDL and its pipeline schema pin together, or apply this storage
migration after the pinned bootstrap. The old schema DDL uses
`CREATE INDEX IF NOT EXISTS`, so it does not replace the compact index during
normal operation.

## Pipeline catalog pin after the online switch

The pipeline also pins a document hash of the live database catalog, including
the index definition. Immediately after the switch, admission was deferred
with `database_catalog_pin_mismatch`. On 2026-10-02 the expected catalog SHA
was changed from
`29ab269cdd70e8f096a7c831b5d94eecf1a96f8cc3465c4ba35d9e159772734c`
to
`9a9b11d1266ec0e16e517b7eed08a2d069d8b2979880dd3d870308799f085f10`.
The local and production `database/load.py`,
`database/pipeline-schema-manifest.json`, deployed code pins, and private v3
migration staging copies were updated together. The original files are backed
up under `/srv/usa-atlas/maintenance/20261002-lookup-pin/`. `schema.sql` SHA
remains `e541b91a152b039d2993df92dd066d686d12578a2d396ad77aee24a965574b5f`.
The migrator returned `already_pass`, the installer restored the systemd timer
and watchdog, and the 13:25 UTC pipeline cycle completed 45/45 candidates.
