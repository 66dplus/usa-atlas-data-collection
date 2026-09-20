# USA Atlas data collection

## Repository boundary

This is the data side of a two-repository system. The separate UI currently lives at
`usa-atlas-design-lab/` in the local workspace and will have its own Git origin. This
repository owns source acquisition, normalization, provenance, stable field/geography
semantics, PostgreSQL schema and admission. It does not own map rendering or product
interaction.

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

The current transfer checkpoint has eight completed providers and an interrupted
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
