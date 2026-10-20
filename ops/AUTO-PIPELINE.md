# Automatic loading of collected data

The new pipeline ties the existing collectors to verified adapters and
transactional loading into the same USA Atlas database. It reuses ready local
artifacts and does not start a second instance of the live collectors.

**Deployment status:** on 1 October 2026 at 08:50 UTC the v3 migration completed,
the timer is enabled, the first cycle started and registered with the watchdog.
At 08:51 UTC the first batch of 250,000 records committed to the database. The
queue of 43 datasets is processed automatically. See the live progress record
kept in the workspace research archive.

The preparation record of 2026-09-29: the first bounded batch of 22 national
datasets and 21 full regional snapshots contained 5,394,180 observations,
105,819 quality records and 156,140 generic records — 80,834,722 bytes of
prepared payload. As of 29 September the national datasets were not yet fully
prepared and no database writes had happened; that historical snapshot precedes
the 1 October launch. All manifest paths, hashes and limits are in
`auto-pipeline-preparation.json` in the workspace research archive. The code
passed static review; real preparation, migration and the first production
loads were performed. The test suites were not run.

## Data flow

1. A registered adapter discovers completed snapshots of known sources.
   Publishing a candidate requires a link to the source manifest plus SHA-256
   digests of the source files. The pipeline re-verifies those hashes.
2. The adapter prepares a separate batch. The initial limit is 250,000 input
   rows; the national adapter additionally bounds the number of numeric and
   quality cells.
3. `database/auto_ingest.py` checks the manifest, artifacts, contracts and
   current schema pins, then admits the batch in one transaction. Re-admitting
   an already accepted batch returns `already_pass`.
4. Only a confirmed receipt with the same manifest hash lets the cursor
   advance. If a run stops after a commit, the next run re-checks the same
   batch; repeated rows are not duplicated.

Adapters are registered once in `ops/auto-pipeline.json`, with reviewed code and
pinned hashes. Subsequent completed snapshots of those sources are admitted
automatically. Unknown catalog discovery results remain candidates until an
adapter with verified units, geography and schema is built and registered for
them. New data is never treated as permission to execute code received from a
source.

## Commands

From the data repository root:

```bash
python3 ops/install_auto_pipeline.py --plan
python3 ops/install_auto_pipeline.py --stage
python3 ops/auto_pipeline.py --once --prepare-only
python3 ops/auto_pipeline.py --status
```

`--plan` only shows the proposed configuration. `--stage` files the not-yet-
installed pipeline code inside the workspace. This mode is refused when its
units are already installed or its configuration is enabled for the database.

`--prepare-only` builds the first bounded batch of each current snapshot, stores
`prepared` and **does not call the database loader**. The admitted-data cursor
does not advance. Its outputs are consumed by the later regular load. `--once`
without extra flags performs read-only discovery and scheduling; a disabled
configuration returns `disabled`.

Once the migrator, adapters and loader code are agreed and actual
systemd/Docker access exists:

```bash
python3 ops/install_auto_pipeline.py --apply --register-watchdog
```

The installer:

- checks systemd access, the `usa-atlas-postgres` container and the units
  directory;
- refuses to update the pipeline while its service is still running;
- preserves previous configurations and unit files;
- invokes the separate transactional `database/migrate_pipeline.py` and
  requires a `pass` or `already_pass` receipt; `prepared` does not mean an
  installed schema. The loader performs no hidden migration;
- pins the final hashes of adapters, the loader and schema files;
- installs and enables `usa-atlas-auto-pipeline.timer` and starts the first
  cycle;
- with an explicitly passed `--register-watchdog`, registers the new process
  with the already installed watchdog. Without the flag the old watchdog is
  untouched.

On a deployment failure the configurations and units are restored. An already
applied incremental database schema is not removed automatically: its state and
a separate receipt are kept for a safe resume.

## Schedule and limits

| Parameter | Value |
| --- | --- |
| Timer | Every 15 minutes UTC, `Persistent=true`, plus a check 120 seconds after boot |
| One cycle | At most 45 minutes and 100 batch attempts |
| Batch scheduler | One batch per source per round, so large tables never starve small ones |
| Runner free space | At least 12 GiB before preparation and before loading |
| Preparation / load timeout | 900 seconds each, further bounded by the remaining cycle time |
| Service restart | `Restart=on-failure`, 300-second pause, at most three starts in 15 minutes, counting normal starts |
| Temporary dataset-failure retry | Growing pause from 60 to 3600 seconds with jitter; at most six attempts in a 24-hour window |
| Maintenance/load locks | Wait for the next cycle; the loader re-checks locks authoritatively |

The loader additionally requires `16 GiB + max(512 MiB, 4 × uncompressed batch)`
of free space on both file volumes: the repository and PostgreSQL (`/srv`). The
12 GiB threshold applies only to the runner pre-check.

The pipeline uses a real `flock`; it has no expiring "lease" and never forces
someone else's lock open. The maintenance-lock check runs before preparation and
admission, but the lock is not held by the pipeline — the loader takes it
itself. Preparation with `--prepare-only` is independent of database state.

On timeout only the child process group created by this runner is terminated:
first TERM, then, when needed, KILL, then waiting for completion. No global
`pkill`, no migration shutdown, no database restart.

Empty and malformed values, original suppression codes and quality intervals are
parsed by the registered adapter. A "data-center building record" field never
becomes a count of operating data centers; point geometry never becomes a Census
block group without a corresponding verified transformation.

## Failures and observation

- A temporary error gets `retry_wait`, a deadline and the stored cursor.
- Maintenance gets `deferred_maintenance` without losing the prepared batch.
- A hash, schema or cursor mismatch, or an unknown content error, moves the
  affected snapshot to `quarantine`; other sources continue.
- A new version of a verified adapter or a new completed snapshot creates a new
  job identity. No per-run re-approval is required.
- A source schema fix is made in the adapter code with updated pinned hashes;
  the scrapers themselves never rewrite code.

```bash
python3 ops/auto_pipeline.py --status
systemctl status usa-atlas-auto-pipeline.timer
journalctl -u usa-atlas-auto-pipeline.service -n 60 --no-pager
```

Working files live in the Git-ignored directory `full/runtime/auto-pipeline/`:

- `state.json` — cursors, attempts, per-source results and the checksum cache;
- `pipeline.lock` — the single active runner instance;
- `batches/<candidate hash>/<cursor hash>/` — immutable candidates, prepared
  manifests, payloads, logs and database receipts;
- `events.jsonl` — admission/quarantine events, rotated after 4 MiB;
- `installations/<UTC timestamp>/` — saved configurations and
  migration/installation results.

`accepted_rows_total` is the number of rows in accepted batch operations,
including updates to existing records. It is not the number of distinct
observations in the database. `prepared` means a file ready for admission, not
loaded data.

## Bounding the growth of prepared files

After successful admission, payload files are kept for seven days. Then the
pipeline removes at most 25 accepted batches per cycle, having verified the
pass-receipt, the manifest hash and the hash of every removed file. Only
generated `observations`, `quality` and `records` files inside their own batch
directory can be removed. Source downloads, manifests and receipts are kept. An
incomplete current batch and a payload without database confirmation are never
removed.

If, after restoring an old checkpoint, an already cleaned batch must repeat, its
payload is rebuilt from the verified sources; the previous metadata and receipt
remain for comparison. After 30 days, completed ledger entries that no longer
belong to current snapshots move to a compressed monthly archive. These
duplicate ledger archives are kept 24 months; individual admission manifests and
receipts stay separate. A pre-deletion check failure is recorded as
`retention.errors` and marks the pipeline state as needing attention. An
unfinished cleanup marker also needs attention and does not trigger further
deletion of that batch automatically.

For a planned stop, stop exactly this timer and service:

```bash
systemctl stop usa-atlas-auto-pipeline.timer usa-atlas-auto-pipeline.service
```

After changing `enabled` in the configuration, update the matching watchdog pin
as part of approved deployment. The existing collectors and their schedules keep
running independently of the pipeline.
