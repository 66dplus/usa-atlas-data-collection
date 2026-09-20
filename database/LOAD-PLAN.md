# USA Atlas completed-data load plan

Date: 19 September 2026  
Workflow: FULL  
Current gate: Plan  
Goal version: `database-load-v1`

## Before and after

**Before.** PostgreSQL is running locally, but database `usa_atlas` does not exist.
Eight source artifacts are complete and hash-bound with 1,031,001 normalized rows.
Census is failed/interrupted and its partial output is not loadable.

**After.** Local database `usa_atlas` contains the 81-field catalog and exactly the
1,031,001 observations from the eight completed source artifacts. Canonical keys are
unique, every observation retains source/release/URL/retrieval time, every successful
artifact has one ingest run with load completion time, and an immediate rerun creates
no new observations or ingest runs.

## Immutable acceptance target

1. **LD1 — Exact admission.** Before creating/loading the target database, all selected
   artifacts are independently verified as manifest `pass`, SHA-256/row-count bound,
   structurally valid, source/profile attributed, and free of duplicate canonical
   `(geo_id, year, field_id, source_release)` keys. The exact duplicate scan must cover
   intra- and cross-admission collisions with bounded disk and O(1) loader memory;
   a hash-valid duplicate fixture must fail with zero PostgreSQL writes. Census must
   be rejected.
2. **LD2 — Local target.** Create database `usa_atlas` owned by the current local
   PostgreSQL user through maintenance database `postgres` and apply the reviewed
   PostgreSQL 16 schema. Every subsequent `psql` and `\copy` command is explicitly
   pinned to `usa_atlas`, never ambient `PGDATABASE`. A pre-existing target is accepted
   only when its owner is the current role and it is empty, or when it has the exact
   current schema fingerprint and already contains the complete, provenance-consistent
   state for the exact selected manifest artifacts; otherwise stop before mutation.
   Do not alter other databases.
3. **LD3 — Complete load.** Load exactly the eight eligible sources. Database counts
   by source must match the manifest and total exactly 1,031,001 observations. Preserve
   every `geo_type` present in each admitted artifact; do not collapse deeper geography
   to state/county or discard ZIP/monitor rows.
4. **LD4 — Deduplication.** `count(*)` must equal the count of distinct canonical keys;
   all duplicate-key queries return zero. Re-running `load --all` must leave both
   observation and successful-ingest counts unchanged.
5. **LD5 — Provenance.** Every observation has nonempty source, release, sanitized
   URL, and retrieval timestamp; every passed ingest has artifact path/hash, contract
   hash, row count, start time, and completion/load time. Joined provenance queries
   must return no missing load timestamps.
6. **LD6 — Geography report.** Record loaded row/distinct-geography counts by
   `geo_type`, and separately explain the current UI hierarchy and the not-yet-loadable
   Census `place`/`tract` depth without calling tracts named neighborhoods. When the
   final Census artifact later reaches `pass`, the same loader must admit all its
   state/county/place/tract rows without geography filtering. Integration fixtures
   must cover loaded ZIP and monitor rows plus a synthetic manifest-`pass` Census
   artifact containing state, county, place, and tract rows.

An executable final verifier must fail closed unless LD3–LD6 hold. Its JSON output
contains exact per-source/total counts, total-versus-distinct canonical keys, duplicate
groups, missing observation/ingest provenance, passed-ingest count, Census row count,
source × geography rows/distinct geographies, and before/after counts around an
idempotent `load --all` rerun.

After final verification we will have a deduplicated, provenance-complete local SQL
copy of every currently completed artifact, while partial Census remains outside the
database.

## Scope and safety

- Use the already reviewed `schema.sql` and `load.py`; no schema redesign or ORM.
- Load only the eight manifest-`pass` sources; no partial Census salvage.
- The database name is exactly `usa_atlas`; existing databases are untouched.
- No remote server, UI wiring, deployment, or neighborhood-boundary work is included.
- Remove the standalone `init` write path. The only bootstrap is the ordered `load`
  flow below; malformed or duplicate input never creates a database or schema.
- If projected free disk would cross the existing 6 GiB safety floor, stop before
  scratch or target creation. The loader emits available, reserved, and projected-free
  bytes and repeats the check after scratch cleanup and before target creation.

## Ordered load algorithm

1. Read and validate the manifest and 81-row contract, hash and validate every selected
   artifact, and count all records. This phase performs no PostgreSQL command.
2. Measure free space on the filesystem holding the collection/temp directory. Reserve
   `max(256 MiB, 4 × selected artifact bytes)` for the exact duplicate index and reserve
   `6 × selected artifact bytes + 512 MiB` for target tables, staging, indexes, and WAL.
   Refuse before scratch creation unless free space minus both reservations remains at
   least 6 GiB.
3. Create a temporary SQLite database on that measured filesystem. Store the four key
   fields as separate `TEXT` columns in a composite `PRIMARY KEY ... WITHOUT ROWID`—no
   delimiter or lossy hash serialization. Set `page_size`, cap `max_page_count` from the
   scratch reservation, disable the discardable temp journal, and stream each admitted
   record into the index. A uniqueness violation, capacity failure, or repeated selected
   artifact rejects the whole selection. Check the file never exceeds the reservation,
   then close and remove it. Fixtures cover duplicates within one artifact and across
   two admissions; both prove that no PostgreSQL command ran.
4. Re-measure free space after scratch cleanup and require the 6-GiB floor after the
   target-load reservation. Only now query maintenance database `postgres`, always with
   explicit `--dbname=postgres`; ignore a poisoned ambient `PGDATABASE`.
5. Resolve the current role and target catalog entry. If `usa_atlas` is absent, create
   it through `createdb --maintenance-db=postgres --owner=<current role> usa_atlas`. If
   present, require the same owner. A target is empty only when it has no non-system
   schemas other than an object-free `public`, no user relations, routines, defined
   types/domains, or non-default extensions; this exact predicate is evaluated from
   `pg_namespace`, `pg_class`, `pg_proc`, `pg_type`, and `pg_extension`. Only such an
   empty target may receive the schema. A nonempty target must pass the existing-target
   admission below before any schema or data write.
6. Apply the schema and load admitted sources. Every schema query, verifier query, and
   `\copy` explicitly includes `--dbname=usa_atlas`; no target operation relies on
   `PGDATABASE`.

## Existing-target admission

- The schema adds a one-row metadata table recording the SHA-256 of the exact
  `schema.sql` template. Initial schema application and fingerprint insertion are an
  all-or-nothing transaction. This is provenance, not proof of physical structure.
- The loader also carries an independently generated expected physical-schema digest.
  Its canonical catalog document enumerates **all** non-system objects, not only the
  required names: user schemas and owners; extensions; every relation/index with
  persistence/kind; ordered columns with `format_type`, nullability/default/generated
  properties; all types/domains; ordered `pg_get_constraintdef` constraints; ordered
  `pg_get_indexdef` indexes; normalized `pg_get_functiondef` bodies/signatures; and
  any non-internal triggers, rules, policies, operators, collations, or conversions.
  The accepted set is exactly the fresh schema's `usa_atlas` objects, an object-free
  `public` schema, and PostgreSQL's default extension set. Any additional user schema,
  table, index, type, function, extension, or other user object changes the digest and
  fails before mutation; schema ownership must also match the current role. The
  implementation generates the expected digest by applying the exact
  reviewed schema to a fresh temporary PostgreSQL 16 database; tests bind the constant
  to that fresh result. Every newly initialized target is checked immediately, and a
  nonempty target must recompute the same canonical digest from its own `pg_catalog`
  before mutation. Added/dropped/changed required objects fail the check even if the
  stored template hash or relation names were preserved.
- A recognized nonempty target is accepted only as an idempotent rerun: its passed
  ingest artifact hashes, sources, contract hash, row counts, and count of runs exactly
  equal the selected admissions; it has no loading/failed/extra ingest rows; it has 81
  catalog rows; source and total observation counts match the selected manifest; and
  provenance/dedup checks are clean. Anything partial, stale, extra, structurally
  incompatible, or owned by another role fails before mutation.
- Tests cover a poisoned `PGDATABASE`, owner mismatch, incompatible schema, partial or
  stale data, an added unexpected user object, hash-valid duplicate input, and exact
  idempotent rerun. They verify no
  schema/run/observation write to either the target or the poisoned ambient database on
  every rejected path.

## Maintainability impact

1. Outcome: one local PostgreSQL database with exact manifest counts.
2. Owners: manifest owns admission; PK owns uniqueness; ingest run owns load provenance.
3. Failure/rollback: each source merge is transactional; database removal is not
   automated and requires an explicit later owner request.
4. Reuse/dependencies: existing reviewed loader and local PostgreSQL 16 only.
5. Checks: pre-load duplicate scan, source counts, distinct-key equality, provenance
   completeness, and idempotent rerun.
6. Docs/contracts: update the database README to remove `init`/ambient `PGDATABASE`,
   document the single guarded `load --all` bootstrap and verifier, and execute that
   documented bootstrap form in integration tests; geography findings are reported
   from current artifacts and UI source.
