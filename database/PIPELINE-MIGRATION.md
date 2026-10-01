# Automatic admission v3 migration

## Deployment and target

The target is Docker container `usa-atlas-postgres`, database `usa_atlas`.
The extension committed on 2026-10-01 at 08:50:10 UTC after host access was
restored. The installer enabled the timer at 08:50:12 UTC and the first real
batch committed at 08:51:19 UTC. No test suite was run.
Installation receipts are in `full/runtime/auto-pipeline/installations/20261001T085009Z/`.
Deployed catalog SHA-256: `29ab269cdd70e8f096a7c831b5d94eecf1a96f8cc3465c4ba35d9e159772734c`.

Baseline compact v2 schema SHA-256:
`6cf64be22ec298c4b99eadb862bb9759b4c0dd44195ef58bffe8b10a9216042d`.
Baseline complete catalog SHA-256:
`2aeb4cff27010265581b0c1a200963b8eb88e3f1a9d60e2e586f041f31cb117d`.
Prepared full v3 schema SHA-256:
`e541b91a152b039d2993df92dd066d686d12578a2d396ad77aee24a965574b5f`.

`full/state/pipeline-migration-v3/preparation.json` binds both original loaders,
both original schemas, all v3 schema copies and loader templates. Production's
additional append safeguards are retained. Static preparation records the
load/append/verify entrypoints protected by the pipeline-managed-target guard.

## Commands and receipts

From the repository root, preparation performs no database connection:

```bash
python3 database/migrate_pipeline.py \
  --result full/state/pipeline-migration-v3/prepare-result.json
```

Deployment is normally called by `ops/install_auto_pipeline.py` after its own
capability and code-binding checks. Its explicit migration command is:

```bash
python3 database/migrate_pipeline.py --apply \
  --result full/state/pipeline-migration-v3/apply-result.json
```

Successful DB receipts are `pass` or `already_pass` (exit 0). A preparation-only
receipt is `prepared`, which the installer must not treat as installed. Blocked
access, lock contention or an unresolved deployment returns exit 75 with a
specific reason. Private PostgreSQL stderr stays in the private state directory.

The code bindings required by installation are `database/auto_ingest.py`,
`migrate_pipeline.py`, `pipeline_schema.sql`, the resulting `schema.sql` and
`load.py`, and the generated `pipeline-schema-manifest.json`. Adapter hashes are
bound separately by the scheduler and every admission manifest.

## Transaction and compatibility

The migrator acquires its own lock, both existing loader flocks and the existing
database advisory lock. It requires the exact v2 catalog and schema metadata.
It rechecks all prepared hashes, then executes the bound extension bytes inside
one transaction. No observation table is copied or rewritten.

Before publishing code, it requires the entire original catalog to be unchanged,
and accounts for the new namespace's three tables, eight indexes, column order,
29 constraints, composite types, owners and storage settings. Unexpected
executable objects or policies cause rollback. All three new tables must be empty.

The canonical catalog hash observed inside that transaction becomes the v3 pin.
The migrator materializes both loader copies from their separately preserved v2
versions, verifies every output and deployed hash, and updates schema metadata.
The local and deployed legacy load/append/verify entrypoints refuse a target once
pipeline datasets exist, directing operators to `auto_ingest.py`. The old 81-field
catalog and compact observation view remain unchanged.

The v3 catalog hash was obtained from the actual PostgreSQL transaction. It is recorded in
`database/pipeline-schema-manifest.json`, the staged `catalog-v3.json`, and the
deployment receipt only after actual transactional catalog inspection.

## Recovery

Keep the entire migration staging directory and all original compact-migration
backups. Before COMMIT, an ordinary error restores v2 code while transactional
DDL rolls back. A hard process interruption is resolved by rerunning the same
migrator with the unchanged prepared files and hashes.

If the COMMIT response is ambiguous, the migrator leaves the v3 code and metadata
in place and records `ambiguous_commit_retry_with_locks`. It closes the original
session; it does not infer rollback from a concurrent connection that might still
see the old catalog. The next `--apply` reacquires all locks, including the DB
advisory lock, before inspecting the authoritative state:

- Exact v2 catalog and v2 schema metadata: restore bound v2 files and retry the
  transaction.
- Exact recorded v3 catalog, v3 schema metadata, extension hash and all bound
  deployed files: return `already_pass` without repeating DDL.
- Any other state: stop with a recovery reason. Never overwrite unknown code or
  restore v2 files over an unverified committed v3 database.

Automatic ingestion checks the full v3 code, schema metadata and catalog bindings
before every transaction, so an intermediate code/DB mismatch stops loading.
The installer enables the timer only after a successful migration receipt and
rebinding the final deployed hashes. Repeated batch admission uses its own ledger
and transactional rollback; it never bootstraps the schema as a side effect.
