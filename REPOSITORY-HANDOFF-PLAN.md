# Collector repository handoff plan

Date: 20 September 2026  
Workflow: FULL  
Current gate: Plan  
Goal version: `collector-repository-v1`

## Before and after

**Before.** `research/data-collection` is part of a non-Git workspace. Runtime data
occupies about 696 MB, credentials live outside the workspace, eight providers are
complete, and Census stopped on timeout with a verified resumable raw cache.

**After.** `research/data-collection` is a standalone Git repository and transferable
Git bundle. It contains the collector, contracts, tests, database tooling, the current
Census manifest/checkpoint cache, and an operator flow that runs only Census under a
single-process lock. Generated bulk outputs, unrelated UI assets, local credentials,
and transient state are excluded.

## Immutable acceptance target

1. **RH1 — Repository.** Initialize a standalone repository on `main` with two logical
   commits: safe baseline import, then server-runner/operations additions.
2. **RH2 — Secret and size safety.** No credential/env file or literal credential is
   tracked; `node_modules`, Python caches, bulk normalized outputs, non-Census raw
   payloads, database files, and transient status/lock files are ignored. No tracked
   file exceeds 25 MiB.
3. **RH3 — Resume checkpoint.** Track `full/state/run-manifest.json` and only the
   verified `full/raw/full/census_acs` cache. Manifest collector/config/contract hashes
   must match the committed files, and every tracked cache payload must match its
   `.sha256` and binding sidecars.
4. **RH4 — Server runner.** Add a standard-library wrapper that can
   `calibrate-if-needed`, `run`, and inspect one explicit source without changing
   `collect.py`; it serializes state-changing runs with a nonblocking file lock.
5. **RH5 — Operations.** Document credential placement, bootstrap, status/log checks,
   restart behavior, disk expectations, result retrieval, and a systemd user-service
   template for Census with bounded restart delay.
6. **RH6 — Transfer artifact.** Collector and database tests pass as applicable, the
   Git tree is clean, a bundle containing `main` passes `git bundle verify`, and the
   final report provides its exact path and SHA-256.

After final verification we will have a compact, secret-free repository artifact that
the server agent can clone, monitor, and restart while reusing the current Census cache.

## Scope and exclusions

- Repository root is `research/data-collection`, not the UI/design workspace.
- No remote repository is created or pushed because no Git host/remote was specified.
- No proxy, quota bypass, credential rotation, server login, or deployment is included.
- Runtime output remains outside Git; completed data already stored in local PostgreSQL
  is not copied into this repository.

## Maintainability impact

1. Outcome: one portable collector repository and bundle for the remaining Census run.
2. Owners: `collect.py` owns collection semantics; the wrapper owns source selection,
   locking, and server entrypoints; systemd owns restart policy.
3. Failure/recovery: collector cache and manifest remain resumable; state-changing
   wrapper commands refuse concurrent execution.
4. Dependencies: Python standard library, Git, and optional systemd only.
5. Checks: existing tests, wrapper tests, cache sidecar verification, secret/size scan,
   clean Git status, and bundle verification.
6. Docs: repository README and server runbook are updated; UI docs are not affected.
