# USA Atlas data collection

[![CI](https://github.com/66dplus/usa-atlas-data-collection/actions/workflows/ci.yml/badge.svg)](https://github.com/66dplus/usa-atlas-data-collection/actions/workflows/ci.yml)

Reproducible collectors, source contracts, tests, a fail-closed database loader,
checkpointed resumable runs, and systemd-based operations for the USA Atlas data
pipeline. It is the data side of a two-repository system and is intentionally
separate from the UI prototype. Released under the [MIT license](LICENSE).

This repository owns source acquisition, normalization, provenance, stable
field/geography semantics, the PostgreSQL schema and admission. It does not own
map rendering or product interaction.

Related reading:

- [DATA-COLLECTION-PLAN.md](DATA-COLLECTION-PLAN.md) — the original collection
  plan: source families, constraints, and the staged path from probes to bulk
  collection.
- [SCALING-PLAN.md](SCALING-PLAN.md) — the rate-limit and throughput analysis
  behind the permission-first collection design (no proxies, one limiter per
  provider).
- [GEOGRAPHY-DEPTH-ROADMAP.md](GEOGRAPHY-DEPTH-ROADMAP.md) — the planned
  expansion from state/county through city, tract, and block group.
- [SERVER-RUNBOOK.md](SERVER-RUNBOOK.md) — server bootstrap, monitoring,
  restart, and result-retrieval flow.
- [database/README.md](database/README.md) — schema, loading, and verification
  guide.

## Repository boundary

This is the data side of a two-repository system. The separate UI repository is
[`66dplus/usa-atlas-design-lab`](https://github.com/66dplus/usa-atlas-design-lab).

The published atlas is **https://usa-xray.online**. That site is built and shipped
from the UI repository, not from this one: this repository owns the pipeline that
feeds the `usa_atlas` database, and the public runtime reads the admitted
observations from that database through the UI's read-only adapter. No collector
code, credentials or unpublished series reach the public site.

The integration boundary is the admitted `usa_atlas` PostgreSQL schema plus the
versioned field and geography contract exported under
[`database/reader/v1`](database/reader/v1/contract.json). That immutable bundle
contains only the app-facing catalog, observation and ingest-run reader schema,
plus small disposable fixtures. UI access is read-only. Collector code and
provider credentials are never dependencies of the UI runtime. Changes to field IDs,
`geo_type`, geography identifiers, normalized record shape or database objects must
declare compatibility/migration requirements and be verified by the UI adapter against
the exact data revision. Pure collector changes may ship independently when this
published contract remains unchanged.

The minimum reader contract is the 81-row `catalog_field`, the 13-column
`observation` view, and `ingest_run` admission by `status = 'pass'`, joined through
`ingest_id`. The observation key is `(geo_id, period, field_id, source_release)`;
period and source release remain explicit text labels, and provenance stays
available on each observation. The pipeline stores a 12-column observation input
in `observation_data`; the public 13-column read view adds normalized source URL
and methodology text. These contracts are distinct.

The reader shape matches the source schema's admission snapshot dated
2026-09-22. This says nothing about deployed identity: local `data/main` also
differs in loader and field-contract content, and no local branch history proves
what is currently deployed. The bundle's `deployed_binding` therefore remains
`unverified`.

## View admitted data in the UI

The collector and the separate [USA Atlas UI](https://github.com/66dplus/usa-atlas-design-lab)
connect through the same PostgreSQL database, <code>usa_atlas</code>. The UI does not import this
repository, read provider credentials, or consume local collection files. It calls a
small adapter that runs <code>psql</code> in read-only transactions against the canonical
<code>usa_atlas.catalog_field</code>, <code>usa_atlas.observation</code> and <code>usa_atlas.ingest_run</code> objects.

For a local end-to-end workflow:

1. Follow the [database loading guide](database/README.md) for the prepared collector
   artifacts and verify the admitted data with <code>python3 database/load.py verify --all</code>.
2. In a separate UI checkout, follow its [quick start and database setup](https://github.com/66dplus/usa-atlas-design-lab).
   Configure that UI process to connect to the same <code>usa_atlas</code> database with a
   dedicated read-only PostgreSQL role and a password file outside both repositories.
3. Open <code>/ux/</code>. The UI loads the database catalog and fetches each selected series
   on demand. Reload the page after a new admission to fetch the updated catalog.

The original transfer checkpoint has eight completed providers and an interrupted
`census_acs` run. The committed `full/raw/full/census_acs/` payloads let another
machine resume Census without repeating verified requests. Bulk normalized output,
non-Census raw downloads, process state, database files, and credentials are not
versioned. The small completed `fbi_cde.jsonl` and `eia.jsonl` artifacts are retained
only as hash-bound integration fixtures used by the database tests.

## Data boundary

The collector retains provider geography rather than pretending that every metric
is city-level. Depending on the source, normalized rows may be state, county, metro,
ZIP, or EPA monitor records. Counties are not city neighbourhoods, and the current
UI's state/city hierarchy does not make deeper provider geographies equivalent to
city districts. The current map consumes state and county observations whose
identifiers map exactly to its Census 2017 geometry. Other collected geography
types and generic source records remain available in the database but are not
displayed as county estimates. Keep field IDs, geography types and IDs, units,
periods, releases and provenance compatible when changing the contract; coordinate
a consumer change in the UI repository before publishing an incompatible schema or
catalog revision.

The reader artifact version, producer commit, schema fingerprint and artifact
hashes are distinct from collector code versions and admitted observation/source
release versions. `deployed_binding` is intentionally unverified; this repository
does not infer production identity from local Git history.

## Operations status and history

### Automatic database admission — running since 1 October 2026

The [scheduled admission pipeline](ops/AUTO-PIPELINE.md) connects completed
downloads to bounded, resumable PostgreSQL imports. Its installed systemd timer
runs every 15 minutes, with transactional checkpoints, retries and process
restarts. Two registered adapters currently cover 22 national snapshots and
21 regional, federal and research datasets. Food-related collection is excluded.

The v3 extension committed at 08:50 UTC on 1 October; the timer is enabled and
registered with the watchdog. The first 250,000-record batch committed at
08:51 UTC, including numeric updates and quality flags. The remaining backlog
continues automatically. Detailed deployment and live-progress records are kept
in the operator's dated research archive outside this repository.

### Actual coverage and cleanup status — 29 September 2026

The actual production inventory of that date confirmed 31 populated fields out
of 81 (28 of 74 non-food fields). At the 29 September snapshot, production had
**no block-group rows**. The automatic admission started on 1 October; newer
records in the research archive supersede this older inventory as live state.

The 81-field coverage audit separates national, regional, source-table and
production coverage. ACS/CDC source data covers 26 of 74 non-food fields; 19
fields have native block-group inputs. Ten regional datasets cover parts of
seven jurisdictions, including new TX/CO/WA collections and 248 PWC data-center
building records. The 52-jurisdiction discovery service has completed a bounded
catalog pass with no unresolved query errors. Its scheduled batches rotate
through missing-topic queries; catalog candidates still require source review.

Database compaction **completed at 15:17 UTC on 29 September**. All 49,206,438
observations and their 13 original fields were preserved. Facts plus indexes
and provenance dictionaries shrank from 63.94 GB to 17.79 GB, saving 46.14 GB
(72%). At that checkpoint the whole database was 17.80 GB and free disk space
was about 143.13 GB; new collection and admission change those sizes.
Both backups are retained. The compatibility view and matching production loader
are deployed. The completed maintenance record and result evidence live in the
operator's dated research archive. The online compact lookup-index switch that
followed is recorded in
[database/LOOKUP-INDEX-MIGRATION.md](database/LOOKUP-INDEX-MIGRATION.md).

### Research and collection — 28 September 2026

The live operations report of that date covers the production database
maintenance history, the completed 21-table ACS + CDC collection, six federal
bulk downloads, and the installed local-portal discovery service. Run
`python3 ops/collection_status.py` for current checkpoints and process status.
The installed [scraper watchdog](ops/MONITORING.md) checks workers every two
minutes, detects stalled progress and performs bounded recovery after failures.

The four-workstream handoff of 28 September records the storage audit, recovery
of partial Census observations, deeper collection tooling, new-topic aggregates,
and US search-demand research. It distinguishes recovered and collected
artifacts from planned or blocked work. Food-related fields are excluded from
this expansion. Research artifacts are not production admissions; the dated
research records mentioned in this section live in the operator's local archive,
not in this repository.

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

The database integration tests run against a temporary PostgreSQL cluster created
inside the test. They require `initdb`, `pg_ctl`, `createdb`, and `psql` from a
PostgreSQL server installation on `PATH`; no running database is needed. The
pinned catalog matches the deployed compact-index shape described in
[LOOKUP-INDEX-MIGRATION.md](database/LOOKUP-INDEX-MIGRATION.md).

Credentials belong in `~/.config/usa-atlas/credentials.env` with mode `600`. Never
copy that file into this repository.

## License

Released under the [MIT license](LICENSE). Copyright © 2026 Dmitrii Rybkin.
Collected source data keeps each provider's own terms; every research artifact
records its origin, and provider permissions are never substituted by automation.
