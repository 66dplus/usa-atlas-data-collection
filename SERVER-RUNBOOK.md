# Census server runbook

The server job is deliberately scoped to `census_acs`, the only unfinished provider
in the transferred checkpoint. The committed raw payloads are verified before reuse;
missing jobs continue through the existing sequential Census rate limiter.

## 1. Bootstrap

Clone the repository or clone the supplied Git bundle, then enter its root. Python
3.11+, Git, network access to `api.census.gov`, and at least 6 GiB of free disk are
required.

```bash
git clone /path/to/usa-atlas-data-collection.bundle usa-atlas-data-collection
cd usa-atlas-data-collection
git status --short --branch
python3 full/server_runner.py validate
```

Create the credential file outside the checkout. Do not paste the key into a command,
unit file, Git config, log, or URL saved as an artifact.

```bash
mkdir -p ~/.config/usa-atlas
chmod 700 ~/.config/usa-atlas
${EDITOR:-vi} ~/.config/usa-atlas/credentials.env
chmod 600 ~/.config/usa-atlas/credentials.env
```

For this scoped run the file must contain `CENSUS_API_KEY=...`. The collector loads it
without printing the value.

## 2. One manual probe

Calibration is a small real request. It is reused on subsequent starts when its hash
bindings still match.

```bash
python3 full/server_runner.py calibrate-if-needed --source census_acs
python3 full/server_runner.py run --source census_acs
```

The state-changing commands use `full/state/server-runner.lock` and immediately exit
with code 75 if another copy is active. Do not run several Census copies against the
same checkout.

## 3. Monitor and restart

Install `ops/usa-atlas-census.service` as a user unit and replace the sample
`WorkingDirectory` with the absolute checkout path.

```bash
mkdir -p ~/.config/systemd/user
cp ops/usa-atlas-census.service ~/.config/systemd/user/
${EDITOR:-vi} ~/.config/systemd/user/usa-atlas-census.service
systemctl --user daemon-reload
systemctl --user enable --now usa-atlas-census.service
loginctl enable-linger "$USER"
```

Operational checks:

```bash
systemctl --user status usa-atlas-census.service
journalctl --user -u usa-atlas-census.service -f
python3 full/server_runner.py status --source census_acs
df -h .
```

The service retries failures after five minutes. The collector keeps completed raw
jobs, rebuilds normalized Census output deterministically, and records the selected
source in `full/state/run-manifest.json`. A successful service exit means the Census
source passed; the server checkout intentionally does not contain the other providers'
normalized output even though their prior pass evidence remains in the manifest.

Before updating code, stop the unit, pull or replace the checkout, and start it again.
Changing `collect.py`, `adapter-config.json`, or `field-contract.json` intentionally
invalidates old cache bindings; do not override that failure.

## 4. Retrieve the result

After `census_acs` is `pass`, copy both files back over an authenticated channel:

- `full/normalized/census_acs.jsonl.gz`
- `full/state/run-manifest.json`

Verify the normalized file against the `normalized_artifact.sha256` value under
`sources.census_acs` in the manifest before loading it locally. Database loading stays
on the local machine so the server does not need database credentials or access.
