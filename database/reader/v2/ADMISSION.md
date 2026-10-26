# Reader v2 admission and rollback

Reader v2.0.0 is a candidate contract with no release tag. Admission is a separate operator action after source review. The ordinary v1 reader remains governed by its existing manifest and is unchanged.

## Bundle preparation

`admission.py prepare` binds the politics, refresh, and BLS inventories, every prepared output, source receipts, reader code, v2 schema, loader mapping, contract hash, completeness counts, candidate ingest IDs, and exact relation row counts. It records quality gates and writes either `blocked` or `ready_for_independent_review`; it never changes a database. Missing source inputs, stale artifact hashes, contract-hash mismatches, and House source identity uncertainty block production readiness. House source eligibility is based on executable reconstruction from its pinned mirror, exact official v15 metadata, original MD5 and byte size, reconstructed SHA-256, and the publisher one-column UNF. The CLI reruns that proof when preparing and validating an admission bundle.

## Portable stage/import

`admission.py export` runs only against an approved disposable local-review target. It writes deterministic PostgreSQL COPY text for the v2 relations and selected passing ledger rows, plus additive schema, source/prepared/code bytes, and SHA-256 receipts under relative content-addressed paths. The source manifest remains byte-identical as an opaque receipt. Imported ledger artifact paths use the portable `reader-v2-bundle://<artifact-sha256>` identity; no absolute task-machine path is required after transfer.

`admission.py stage` defaults to a dry run. `--apply` requires a separate receipt bound to the portable bundle hash, contract hash, target ID, reviewer, and expiry. One bounded transaction applies the additive schema, inserts only the named `ingest_run` rows and v2 relations as `local_review`, and rechecks canonical relation content hashes. Any mismatch rolls back. It does not write v1 catalog or observation rows. Stage and admission remain separate actions. Bundle paths reject absolute paths, traversal, and symlinks.

The same portable `bundle.json` is accepted by the later `admit` action. Stage receipts bind the manifest SHA-256; admission and revocation receipts bind the exact `bundle.json` file SHA-256 printed by their dry run. Both actions require a target-specific review receipt and `--apply`.

## Operator action

The operator supplies a target config whose `target_id` is declared in `production-target-policy.json`. No default target exists. A bundle-bound review receipt must match the bundle SHA-256, contract SHA-256, target ID, reviewer, and expiry. The CLI is dry-run by default. `--apply` is mandatory to write. No connection credentials are stored in the config; the operator's approved runtime provides connection authentication.

The admission transaction has a bounded lock and statement timeout, takes a PostgreSQL advisory transaction lock, rechecks every bound artifact and candidate batch ledger/hash/count, checks quality/period/geography/source invariants, appends `reader_v2_admission_event`, marks only the named v2 batches/catalog contracts admitted, and grants `SELECT` on declared reader relations to the declared read role. It does not update or delete v1 observations or overwrite released v1 catalog metadata. A failed check rolls back the transaction.

`admission.py revoke` requires an explicit review receipt and moves the exact admitted batch IDs back to `local_review`, appending a `revoked` event. It retains data and history. The v2 production read filter requires both `ingest_run.status = 'pass'` and `reader_batch.candidate_status = 'admitted'`, so the revoke restores the pre-admission reader behavior.

## Worker validation scope

Producer workers may test only unique disposable databases declared by the target policy. Workers may run only against the unique disposable target in the target policy. A production bundle is still blocked by any remaining independent source/readiness gates, including incomplete or mismatched source inventories. A test fixture is never a production source bundle and must never be described as production admission. Parent owns protected merges, production database access, release tagging, and deployment.
