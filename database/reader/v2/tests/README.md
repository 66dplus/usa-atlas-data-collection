# Candidate v2 schema checks

Run `schema.sql`, `fixtures/reader-fixture.sql`, then `invariants.sql` in a uniquely named disposable PostgreSQL database. `invariants.sql` expects duplicate-grain, invalid-month, office/geography, and observed-value violations to be rejected; M13 annual, NULL-aware Senate contest identity, explicit no-election, and absent-party zero semantics are checked. PostgreSQL 15 or later is required for `UNIQUE NULLS NOT DISTINCT`.

Do not run against an owner, shared baseline, or production database. Tests do not read or write the released v1 schema.
