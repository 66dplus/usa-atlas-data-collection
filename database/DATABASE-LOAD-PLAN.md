# USA Atlas completed-data load plan

Date: 19 September 2026  
Workflow: FULL  
Current gate: Plan  
Goal version: `database-load-v1`

## Before and after

**Before.** PostgreSQL 16.13 is running locally with unrelated database `elderly_mvp`.
USA Atlas has eight `pass` normalized artifacts totaling 1,031,001 rows; Census is
`fail` after a timeout and has only partial output. The USA Atlas schema exists as SQL
and has been proven on a temporary cluster, but no persistent USA Atlas database is
loaded.

**After.** A separate local database `usa_atlas` contains only the eight passed
artifacts. Every admitted row passed the existing contract/hash preflight, the database
primary key enforces `(geo_id, period, field_id, source_release)`, and each source has
one successful ingest record with source, artifact hash, row count, and start/end time.
The same load command can be rerun without increasing observation or ingest counts.

## Immutable acceptance target

1. **LOAD1 — Isolated database.** Create `usa_atlas` without modifying `elderly_mvp`.
   Verification: PostgreSQL lists both databases and `usa_atlas` has the expected
   `usa_atlas` schema.
2. **LOAD2 — Deduplicated completed data.** Load every manifest source with `status=pass`
   using the reviewed loader. Verification: eight source rows are admitted, SQL
   `count(*)` equals 1,031,001, SQL `count(*)` equals
   `count(DISTINCT (geo_id, period, field_id, source_release))`, and no Census row is
   present.
3. **LOAD3 — Provenance and time.** Each source has a `pass` `ingest_run` with artifact
   path, SHA-256, contract SHA-256, row count, `started_at`, and `completed_at`.
   Verification: all eight runs have non-null values and their row counts sum to
   1,031,001.
4. **LOAD4 — Idempotent rerun.** Run the same `--all` command again. Verification:
   every artifact reports `skipped`, observation count and ingest-run count remain
   unchanged, and the original hashes/timestamps remain intact.
5. **LOAD5 — Geography inventory.** Produce a SQL inventory by source and `geo_type`
   and compare it with the normalized artifacts. Verification: the inventory is saved
   in the task evidence; it distinguishes state, county, zip, monitor, and metro data
   and does not claim city-district coverage that was not collected.

After final verification we will have a persistent, deduplicated local database for all
currently complete sources, with auditable provenance and a repeatable no-duplicate load.

## Scope and exclusions

- Only the existing local PostgreSQL instance and the eight manifest `pass` artifacts
  are in scope. The unrelated `elderly_mvp` database is read-only out of scope.
- Partial/failed Census output is not loaded. It becomes eligible only after a final
  artifact and manifest `pass` are produced.
- No database drop, destructive cleanup, proxy purchase, remote deployment, or UI
  migration is performed.
- Geography names/boundaries and city council/neighborhood districts are not invented;
  the loaded `geo_type` inventory is the source of truth.

## Maintainability impact

1. The reviewed loader remains the single admission/merge owner.
2. PostgreSQL constraints own deduplication; `ingest_run` owns provenance/time.
3. The new database name isolates unrelated local data; rerun is recoverable and safe.
4. No new runtime dependency or schema variant is introduced.
5. SQL counts, source runs, and a second identical load are the observable gates.
6. README and this packet document the operator command and geography boundary.
