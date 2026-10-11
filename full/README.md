# Local full-data collector

This directory is the local-only collector for the 81 rows in the source catalog.
Credentials are loaded from `~/.config/usa-atlas/credentials.env`; their values are
never written here. The runner uses one sequential limiter per provider, does not use
proxies, and will not enqueue a source that failed calibration.

Run from the repository root:

```bash
python3 research/data-collection/full/build_contract.py
python3 research/data-collection/full/collect.py validate
python3 research/data-collection/full/collect.py calibrate
python3 research/data-collection/full/collect.py run
python3 research/data-collection/full/collect.py status
python3 research/data-collection/full/collect.py eval
```

`run` is resumable. A source marked `pass` is skipped only when the manifest is bound
to the same plan, contract, adapter config and collector-code hashes and its normalized
artifact still matches its recorded hash. Every raw cache file has an adjacent
`.sha256` record; missing, malformed or mismatched records are not trusted. Inside an
existing payload with a missing hash/binding fails closed without transport. Inside an
interrupted source, verified raw jobs are reused only when their binding metadata
matches the same plan, contract, adapter config and collector-code hashes. Calibration
reports carry the same four bindings and a mismatch stops the run. Before a source
passes, its row count and unique key
`(geo_id, year, field_id, source_release)` are checked. The runner checks free disk
before large stages and stops a source instead of filling the disk. Census raw and
normalized records are gzip-compressed deterministically. The source checkpoint owns
one stable normalization retrieval timestamp, so rebuilding an interrupted source from
the same ordered raw jobs produces the same normalized artifact hash.

The committed field contract contains concrete ACS E/M variable IDs. The builder uses
frozen 2024 group bounds to regenerate that expansion without contacting Census.

Generated data:

- `raw/calibration/` and `state/calibration-report.json`: bounded nine-source probes;
- `raw/full/`: immutable source payloads with adjacent SHA-256 records and manifest
  entries;
- `normalized/<source>.jsonl[.gz]`: source-specific normalized output;
- `state/run-manifest.json` and `state/status.json`: progress and resume state;
- `FIELD-EVAL.json`: 81-row expected/observed Eval.

The contract intentionally leaves blocked, undefined and unlicensed fields visible.
`BLOCKED` and `NOT_RUN` do not count as passing data.

## Checked map consumer definitions

`map_metrics.py` is an opt-in read-only calculation layer for map statistics.
It preserves source observations and the existing ingestion contract, validates
exact source variables and metadata, and returns separate derived values with
raw components and uncertainty. `map-metric-definitions.json` contains versioned
definitions and explicit display conversions; it does not change UI defaults.

The [35-field registry and Oregon/US examples](../research/2026-10-11/map-metrics/README.md)
bind the October runtime source hashes to bounded read-only PROD evidence. Build
and check these frozen review artifacts from this repository's root:

```bash
python3 full/build_map_metric_definitions.py
python3 research/2026-10-11/map-metrics/build_registry.py
python3 -m unittest discover -s full -p test_map_metrics.py
```

Broad category choices and compatible crime-rate denominators remain explicit
product/input gaps. Geographic presence is specific to each selected subseries;
unknown presence is not a zero count. `comparison_record()` supplies the scalar
contract for `database.map_quality.MetricObservation` after the caller explicitly
binds geography vintage and seasonal adjustment.
