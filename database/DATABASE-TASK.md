# SQL database task packet

Workflow: FULL  
Current gate: Closing  
Goal version: `database-v1`  
Acceptance IDs: `DB1`–`DB6`

## Bound inputs

- Normalized record producer: `../full/collect.py`
- Field contract: `../full/field-contract.json`
- Run manifest: `../full/state/run-manifest.json`
- Plan: `DATABASE-PLAN.md`
- Global policy SHA-256:
  `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`
- Workspace is not a Git repository.

## Gate evidence

Plan SHA-256: `f5f156b925b50e6da8b0fbb09c3f1509e5a2f4ec90613c966e88fa1948e28186`.  
PlanPass: `PASS`, independently issued for plan
`f5f156b925b50e6da8b0fbb09c3f1509e5a2f4ec90613c966e88fa1948e28186`,
goal `database-v1`, IDs `DB1`–`DB6`, and global policy
`7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.  
Candidate manifest: `DATABASE-CANDIDATE.md`, candidate digest
`95df3b9f5b45a4407b981c9159d1845915c95023a587c19d87901b9a0c189b33`.  
ReviewPass: `PASS`, independently issued for plan
`f5f156b925b50e6da8b0fbb09c3f1509e5a2f4ec90613c966e88fa1948e28186`,
candidate `95df3b9f5b45a4407b981c9159d1845915c95023a587c19d87901b9a0c189b33`,
and global policy `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.
The reviewer verified PostgreSQL 16.13 DDL, exact PK/FKs, 12-field round-trip,
transactional/idempotent merge, zero-write admission failures, current source
preflight, failed-Census exclusion, and indexed O(1)-memory idempotency lookup.  
GoalPass: `PASS`, independently issued for goal `database-v1`, IDs `DB1`–`DB6`,
plan `f5f156b925b50e6da8b0fbb09c3f1509e5a2f4ec90613c966e88fa1948e28186`,
candidate `95df3b9f5b45a4407b981c9159d1845915c95023a587c19d87901b9a0c189b33`,
and global policy `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.
All six acceptance IDs passed against PostgreSQL 16.13; the evaluator confirmed exact
schema/key behavior, 12-field round-trip, safe zero-write admission, 81-field
provenance, a real 3,266-row FBI load/rerun, and the documented storage boundary.

## Current todo

1. Report the completed database preparation and deferred full-load boundary.

Prior plan `dcce46deb1876600927f6c26fc12f348c8d316faf6f729c8de61753d0177c3e4`
received `REVISE`. The revised plan requires contract-to-manifest binding, exact
12-field round-trip evidence, source/catalog attribution checks, and zero database
writes for every preflight rejection.

Plan `f699028bf0ee918662d05f60ffe286058deacfb64f5ad479df702aaa2b3bd8a1`
received `REVISE`. The revised plan additionally requires every admitted
`catalog_field_id` to belong to a `run_now` contract row whose `rate_limit_profile`
equals the selected manifest source, with a zero-write mismatched-profile fixture.

Candidate `efc230dbd71e22f052f88382af17497d77d100e2deecc9981f818a81a2393471`
received `FAIL`. The current candidate fully validates all 16 required properties,
types, IDs, planned-state totals, executable/disabled mappings, lists, and profiles for
all 81 contract rows before the first `psql` call. A malformed but hash-matching
contract now has an explicit zero-write PostgreSQL regression case.

Candidate `a8156b08c0a63f5fe4ddfb309081880a9dfde8a4a2231cac7e32570d1a48adbc`
received `FAIL`. The current candidate replaces the unbounded set of historical passed
artifact hashes with one partial-index-backed `SELECT EXISTS` for the selected,
preflight-verified SHA-256, keeping idempotency lookup O(1) in loader memory.
