# USA Atlas data collection

## Automatic database admission — running since 1 October 2026

The [scheduled admission pipeline](ops/AUTO-PIPELINE.md) connects completed
downloads to bounded, resumable PostgreSQL imports. Its installed systemd timer
runs every 15 minutes, with transactional checkpoints, retries and process
restarts. Two registered adapters currently cover 22 national snapshots and
21 regional, federal and research datasets. Food-related collection is excluded.

The v3 extension committed at 08:50 UTC on 1 October; the timer is enabled and
registered with the watchdog. The first 250,000-record batch committed at
08:51 UTC, including numeric updates and quality flags. The remaining backlog
continues automatically. See the [deployment and live progress record](research/2026-10-01/PROGRESS.md).

## Actual coverage and cleanup status — 29 September 2026

The [actual production inventory](research/2026-09-29/production-coverage.json)
confirmed 31 populated fields out of 81 (28 of 74 non-food fields). At that
29 September snapshot, production had **no block-group rows**. The automatic
admission started on 1 October; use the newer progress record above for its
committed coverage rather than interpreting this older inventory as live state.

The [81-field coverage audit](research/2026-09-29/coverage-audit/README.md)
separates national, regional, source-table and production coverage. ACS/CDC
source data covers 26 of 74 non-food fields; 19 fields have native block-group
inputs. Ten regional datasets now cover parts of seven jurisdictions, including
[new TX/CO/WA collections](research/2026-09-29/regional-expansion/README.md) and
[248 PWC data-center building records](research/2026-09-29/data-center-expansion/README.md).
The [52-jurisdiction discovery service](research/2026-09-29/nationwide-portals/README.md)
has completed a bounded catalog pass with no unresolved query errors. Its scheduled batches rotate
through missing-topic queries; catalog candidates still require source review.

Database compaction **completed at 15:17 UTC on 29 September**. All 49,206,438
observations and their 13 original fields were preserved. Facts plus indexes
and provenance dictionaries shrank from 63.94 GB to 17.79 GB, saving 46.14 GB
(72%). At that checkpoint the whole database was 17.80 GB and free disk space
was about 143.13 GB; new collection and admission change those sizes.
Both backups are retained. The compatibility view and matching production loader
are deployed. See the [completed maintenance record](research/2026-09-29/CLEANUP-NEXT.md)
and [result evidence](research/2026-09-28/storage/postgres-cleanup-result.json).

## Research and collection — 28 September 2026

The [live operations report](research/2026-09-28/LIVE-OPERATIONS.md) covers the
production database maintenance history, completed 21-table ACS + CDC collection,
six federal bulk downloads, and the installed local-portal discovery service.
Run `python3 ops/collection_status.py` for current checkpoints and process status.
The installed [scraper watchdog](ops/MONITORING.md) checks workers every two
minutes, detects stalled progress and performs bounded recovery after failures.

The [four-workstream handoff](research/2026-09-28/README.md) records the storage
audit, recovery of partial Census observations, deeper collection tooling,
new-topic aggregates, and US search-demand research. It distinguishes recovered
and collected artifacts from planned or blocked work. Food-related fields are
excluded from this expansion. Research artifacts are not production admissions.

## Repository boundary

This is the data side of a two-repository system. The separate UI repository is
[`66dplus/usa-atlas-design-lab`](https://github.com/66dplus/usa-atlas-design-lab), checked
out locally at `usa-atlas-design-lab/` in the USA-MAPS workspace. This repository owns
source acquisition, normalization, provenance, stable field/geography semantics,
PostgreSQL schema and admission. It does not own map rendering or product interaction.

The integration boundary is the admitted `usa_atlas` PostgreSQL schema plus the
versioned field and geography contract. UI access is read-only. Collector code and
provider credentials are never dependencies of the UI runtime. Changes to field IDs,
`geo_type`, geography identifiers, normalized record shape or database objects must
declare compatibility/migration requirements and be verified by the UI adapter against
the exact data revision. Pure collector changes may ship independently when this
published contract remains unchanged.

This repository contains the reproducible collectors, source contracts, tests,
database loader, and the verified partial Census cache for the USA Atlas data
pipeline. It is intentionally separate from the UI prototype.

The original transfer checkpoint has eight completed providers and an interrupted
`census_acs` run. The committed `full/raw/full/census_acs/` payloads let another
machine resume Census without repeating verified requests. Bulk normalized output,
non-Census raw downloads, process state, database files, and credentials are not
versioned. The small completed `fbi_cde.jsonl` and `eia.jsonl` artifacts are retained
only as hash-bound integration fixtures used by the database tests.

## Local checks

Python 3.11+ is sufficient; the collector and server runner use only the standard
library.

```bash
cd full
python3 collect.py validate
python3 -m unittest -v test_collect.py test_server_runner.py

cd ../pilot
python3 -m unittest -v test_run_pilot.py

cd ../database
python3 -W error::ResourceWarning -m unittest -v test_database.py
```

Credentials belong in `~/.config/usa-atlas/credentials.env` with mode `600`. Never
copy that file into this repository. See [SERVER-RUNBOOK.md](SERVER-RUNBOOK.md) for
the server bootstrap, monitoring, restart, and result-retrieval flow. The planned
expansion from state/county through city, tract, and block group is recorded in
[GEOGRAPHY-DEPTH-ROADMAP.md](GEOGRAPHY-DEPTH-ROADMAP.md).

## Data boundary

The collector retains provider geography rather than pretending that every metric
is city-level. Depending on the source, normalized rows may be state, county, metro,
ZIP, or EPA monitor records. Counties are not city neighbourhoods, and the current
UI's state/city hierarchy does not make deeper provider geographies equivalent to
city districts.
