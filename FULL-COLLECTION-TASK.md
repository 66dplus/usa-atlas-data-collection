# Full collection task packet

Workflow: FULL  
Current gate: Closing  
Owner request: locally launch real collection for all catalog fields, define per-field
Eval, and separately plan compliant acceleration using one local machine and two
servers.  
Goal version: `full-collection-v1`  
Acceptance IDs: `FC1`, `FC2`, `FC3`, `FC4`, `FC5`, `FC6`

## Bound inputs

- Catalog: `source/us_map_statistics_catalog.docx`
- Catalog SHA-256: `f4460c959b951f286b0fb0854c434102febf843749d48645a611aad589969f1b`
- Baseline plan: `DATA-COLLECTION-PLAN.md`
- Existing pilot: `pilot/run_pilot.py`
- Credentials: external mode-600 file; values must never be inspected, logged, or
  copied into this packet.
- Global policy SHA-256:
  `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`

## Acceptance target

The immutable target is the `Immutable acceptance target` section of
`FULL-COLLECTION-PLAN.md`, goal version `full-collection-v1`, IDs `FC1`–`FC6`.

## Scope and exclusions

Implement the smallest local collector that satisfies the accepted plan. Do not edit
the UI, install on remote servers, purchase proxies/licenses, scrape prohibited private
sources, or convert blocked/not-run fields into passes.

## Required impact checklist

1. Outcome/baseline/delta: recorded in the bound plan.
2. State owners/interfaces/consumers: recorded in the bound plan.
3. Failures/compatibility/rollback: recorded in the bound plan.
4. Reuse/dependencies: recorded in the bound plan.
5. Tests and boundary evidence: recorded in the bound plan.
6. README/AGENTS/contracts: recorded in the bound plan.

## Gate evidence

Plan hash: `8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781`.  
PlanPass: `PASS`, independently issued for plan
`8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781`,
goal `full-collection-v1`, IDs `FC1`–`FC6`, and global policy
`7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.  
Candidate manifest: `FULL-COLLECTION-CANDIDATE.md`, candidate digest
`7d9760d8f9463e616f8a06b74dfed834a3f725d7fe6812dcfc0420e81f34c46d`.  
ReviewPass: `PASS`, independently issued for plan
`8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781`,
candidate `7d9760d8f9463e616f8a06b74dfed834a3f725d7fe6812dcfc0420e81f34c46d`,
and global policy `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.
The reviewer recomputed every candidate member and digest, ran 20 tests, and verified
81 contract rows, 706 concrete Census variables, 13,096 BLS series IDs, 685 bound raw
payloads, 13 calibration artifacts, normalized outputs/Eval, and FC1–FC6 review scope.  
GoalPass: `PASS`, independently issued for goal `full-collection-v1`, plan
`8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781`,
candidate `7d9760d8f9463e616f8a06b74dfed834a3f725d7fe6812dcfc0420e81f34c46d`,
and global policy `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.
FC1–FC6 each received `PASS`; evaluator-confirmed evidence includes 81 contract rows,
nine calibration families, 1,031,001 completed normalized rows across eight sources,
zero duplicate keys, honest 81-row Eval, and the `unknown` scale verdict with `no`
proxy recommendation.

Prior candidate `678d66d6f3652de4fdc01e9e201d3c5eb4660d2844c6f50ba79862ea8df4b027`
received `FAIL`. Its findings were addressed by the new candidate: duplicate-key
elimination, per-field evidence hashes, true calibration raw-row counts, hash-verified
resume cache, manifest plan/config/contract/code binding, factual FBI row count, and a
content-level USDA/email security scan.

Candidate `c3c157076cdf24060ca18e80b066978f6aa81b9a7c10e73ee2e473453b3ed04e`
also received `FAIL`. The current candidate adds per-artifact binding metadata for the
plan, contract, adapter config and collector code; rejects incompatible calibration or
raw cache; verifies calibration artifacts before parsing; and enforces EIA's configured
`max_pages` cap.

Candidate `a67e765a2051add64f784a5dc76ad5e4eeaff189f95920f170f2b3f41926fce0`
received `FAIL`. The current candidate materializes all Census group placeholders into
concrete frozen E/M IDs, validates every declared calibration payload before full-run
admission, preserves a source-owned normalization timestamp across interruption, uses
deterministic gzip metadata, and adds an interrupted-vs-uninterrupted artifact-hash
test.

Candidate `ddace34b947fec4523ac3d11c637593cf999969bbae8eab95083022de70bec10`
received `FAIL`. The current candidate expands the remaining Census range placeholders
into concrete E/M IDs, treats an existing cache artifact without complete sidecars as
a fail-closed integrity error without network transport, and replaces the synthetic
resume assertion with a `run_full` interruption/resume integration test that verifies
no repeat transport and byte-identical normalized output.

Candidate `3a2bfb89b1a4879fae5dc6d6d18371376ba84565954c47d48c69523952a88cc6`
received `FAIL`. The current candidate replaces the BLS prose/ellipsis placeholders
with eight deterministic LAUS state/county templates for measures `03`–`06`, validates
that exact ordered set, derives outbound series IDs from the contract, and verifies all
13,096 already-collected BLS series IDs against those templates with zero mismatches.

## Current todo

1. Resume Census from the verified local checkpoint and leave collection running.
2. Report the live process and current checkpoint to the owner.
