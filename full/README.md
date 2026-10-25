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

The 2024 `housing-stock-metrics.json` defines the three all-housing-units tenure shares
derived from the `02.07` variables: owner-occupied, renter-occupied, and vacant or
seasonal.

The approved 2017-2021 artifact uses a separate period-specific contract so the 2024
`02.07` rows remain unchanged:

```bash
python3 research/data-collection/full/collect_housing_stock_2021.py \
  --boundary-manifest /path/to/operator-boundaries/manifest.json \
  --boundary-manifest-sha256 <manifest-sha256>
```

When boundary validation is requested, supply an operator-managed, versioned
geometry bundle. Its manifest must contain `artifact_version`, each state's
`id` and geometry-file `sha256`; verify the manifest hash with the required
CLI argument. The collector does not fetch geometry or depend on a neighboring
UI checkout. Omitting the optional boundary arguments preserves the existing
collection and validation flow.

It writes `normalized/housing_stock_2021.jsonl.gz` and
`normalized/housing_stock_2021.manifest.json`. The contract is
`housing-stock-2021-contract.json`; UI definitions are in
`housing-stock-2021-metrics.json`. The artifact has 3,142 counties, 51 states and one
US record. Chugach (`02063`) and Copper River (`02066`) are summed into the 2017
Valdez-Cordova (`02261`) boundary, with MOEs combined by root-sum-square. The artifact
is deterministic across reruns; the manifest records the retrieval timestamp.

Generated data:

- `raw/calibration/` and `state/calibration-report.json`: bounded nine-source probes;
- `raw/full/`: immutable source payloads with adjacent SHA-256 records and manifest
  entries;
- `normalized/<source>.jsonl[.gz]`: source-specific normalized output;
- `state/run-manifest.json` and `state/status.json`: progress and resume state;
- `FIELD-EVAL.json`: 81-row expected/observed Eval.

The contract intentionally leaves blocked, undefined and unlicensed fields visible.
`BLOCKED` and `NOT_RUN` do not count as passing data.
