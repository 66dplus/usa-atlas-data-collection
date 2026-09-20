# USA Atlas SQL database plan

Date: 19 September 2026  
Workflow: FULL  
Current gate: Plan  
Goal version: `database-v1`

## Before and after

**Before.** Completed source families are stored as normalized JSONL files. There is
no SQL schema, transactional ingest path, database uniqueness enforcement, or database
query contract. Census is still being written, and the local disk has too little free
space to duplicate the full collection safely.

**After.** PostgreSQL 16 can be initialized with one schema and populated by a
streaming loader. The loader imports the 81-row field contract and only normalized
artifacts whose source is `pass` and whose SHA-256 matches the run manifest. Each
source merge is idempotent and the database enforces the collector's canonical key.
The live partial Census file is never admitted.

## Immutable acceptance target

1. **DB1 — PostgreSQL schema.** `schema.sql` applies cleanly to PostgreSQL 16 and
   creates the `usa_atlas` schema, `catalog_field`, `ingest_run`, typed staging tables,
   and `observation`. Verification: a clean temporary cluster applies the file with
   `ON_ERROR_STOP=1` and catalog/observation constraints are visible in `pg_catalog`.
2. **DB2 — Exact observation contract.** `observation` stores every normalized JSONL
   field without lossy renaming; `year` is stored as text `period` because some sources
   publish values such as `2024-M12`. The primary key is exactly
   `(geo_id, period, field_id, source_release)`, matching the collector. Verification:
   a duplicate fixture is merged without increasing the row count, a conflicting value
   updates the same key, and one real normalized row round-trips all 12 input fields
   exactly, with only the documented `year` → `period` column rename and its catalog
   reference intact.
3. **DB3 — Safe admission.** The loader imports only sources marked `pass`, verifies
   the compressed-or-plain artifact bytes against `normalized_artifact.sha256`, checks
   that the field-contract bytes equal the manifest's top-level `contract_sha256`,
   checks all 12 required JSON fields and finite numeric values, requires every row's
   `source` to equal the selected manifest source, and requires every
   `catalog_field_id` to resolve to a `run_now` row in the verified 81-row contract
   whose `rate_limit_profile` equals the selected manifest source. A partial, missing,
   mismatched, cross-source, or otherwise misattributed artifact is rejected before any database write.
   Verification: focused tests cover accepted, partial, missing, hash-mismatch,
   contract-mismatch, source-mismatch, unknown-field, and mismatched-profile fixtures.
4. **DB4 — Field provenance.** All 81 contract rows are upserted into
   `catalog_field`; observations reference `catalog_field_id`; each load records source,
   artifact path/hash, contract hash, row count, timestamps, and terminal status in
   `ingest_run`. Verification: the smoke database contains 81 catalog rows and the
   loaded source has one successful run whose count equals its observations. Every
   preflight-rejection test also asserts that both `observation` and `ingest_run` counts
   remain unchanged; rejected artifacts have no database run row.
5. **DB5 — Real smoke load.** A temporary PostgreSQL 16 cluster loads one completed
   real source, verifies counts and representative round-trip values, reruns the same
   artifact, and observes no duplicate rows. Verification: an executable integration
   check exits zero and reports expected/observed counts.
6. **DB6 — Operator handoff.** README documents initialization, loading one/all
   completed sources, verification queries, storage caveat, and the rule that Census
   is loaded only after its manifest status becomes `pass`. No credentials or database
   password are stored in the project.

After final verification we will have a database schema and loader ready for the
completed collection, proven against real normalized data, without copying the active
partial Census dataset or exhausting local disk.

## Scope and exclusions

- PostgreSQL 16 is the database target; no ORM or application API is introduced.
- `double precision` preserves the collector's current Python-float representation.
- One loader process at a time is supported; concurrent ingestion is out of scope.
- PostGIS geometry, geography names/boundaries, aggregation/materialized views,
  replication, remote deployment, and full-data loading are deferred until the target
  server/storage is selected.
- The loader uses Python standard library plus the installed `psql` client. No runtime
  package is added.

## Maintainability impact

1. Outcome: `schema.sql` + streaming loader proves the shortest operator flow.
2. Owners: the collector owns JSONL; SQL constraints own stored integrity; the loader
   owns admission and conversion.
3. Failure/rollback: source merge is transactional; staging can be truncated; schema
   removal is an explicit operator action and is not automated.
4. Reuse/dependencies: PostgreSQL and Python standard library only.
5. Checks: unit validation plus an ephemeral PostgreSQL integration load and rerun.
6. Docs: database README is added; root/project UI instructions are not affected.
