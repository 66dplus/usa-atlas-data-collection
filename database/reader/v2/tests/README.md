# Candidate v2 schema checks

Run `python3 -m database.reader.v2.tests.run_disposable_integration --prepared-dir <prepared-dir-under-approved-task-tmp>` against the task's approved disposable PostgreSQL socket. The runner creates and drops unique `reader_v2_worker_*` databases only. It tests v1 bootstrap, additive migration, loading the prepared local 2024 election slice and ACS observations, read selectors, zero/no-election/missing distinctions, duplicate NULL grain, M13, source/quality constraints, and office/geography checks. It also runs the SQL fixture and invariants in a second disposable database. The loader guard refuses all database targets except the explicitly configured task socket/name pattern. PostgreSQL 15 or later is required for `UNIQUE NULLS NOT DISTINCT`.

Do not run against an owner, shared baseline, or production database. Tests do not read or write the released v1 schema.
