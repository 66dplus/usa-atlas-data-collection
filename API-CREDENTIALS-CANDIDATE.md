# USA Atlas API credentials — candidate manifest

- Goal version: `v1`
- Acceptance IDs: `K1`, `K2`, `K3`, `K4`
- Baseline commit: unavailable; this workspace is not a Git repository.
- Classification: all listed files are non-Git workspace material.
- Plan hash: `dc2b3f77d8b5d2ce383a48a6c9a2b4883784eea1e63c7170bc7cf1da5ae38147`
- Global policy hash: `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`
- Candidate tree digest: `b1924c3bb803df9226a247c7dbf4c3edcd19702451dae9e696803a0401370952`
- External secret material: `/Users/dmitrijrybkin/.config/usa-atlas/credentials.env`
  is intentionally excluded from the candidate and repository; only its mode and
  variable-presence checks are evidence.

## Sorted path SHA-256 values

```text
dc2b3f77d8b5d2ce383a48a6c9a2b4883784eea1e63c7170bc7cf1da5ae38147  research/data-collection/API-CREDENTIALS-PLAN.md
fac9b1c3ce8de07659c07838df95cceb6360399866b2c30222cbda705f6c9c77  research/data-collection/DATA-COLLECTION-PLAN.md
2f81fa4be7edbd370ca1095489e70a886b45b0b5c05bdea2c984746a6709d7a9  research/data-collection/pilot/normalized/pilot-samples.json
0ce7c3db1361bfcd032b22250f15b3fce58d3d2bf4cb3428eca88877f9f1a5d8  research/data-collection/pilot/probe-results.json
38713c6224c4c26ae020ffecd4549b82dca84f43d34f93dfdb43f4070cf011da  research/data-collection/pilot/raw/bea-sarpp.zip
193c9695dfcf60f4279b6860896ce7f767b673e3585a21ed768320d27aee9ce3  research/data-collection/pilot/raw/bls-laus.json
48986ea30b3ff04ee20cf8719468210c6a23bedbbe2a579a326f59d8ddca18c0  research/data-collection/pilot/raw/cdc-places-alameda.json
4ed7b32d958d95bd73132d3f970a1b0ff600eaf7bde1df6396399d1cea27d66f  research/data-collection/pilot/raw/census-acs-alameda.json
b329686e7fb221c617606464ac8ff5ef24808e1205f33e865b1b2988ca0e75e4  research/data-collection/pilot/raw/eia-electricity-price.json
5d77ce6dd6774c57f09d430eac5a11edcb0cb7fca931725c66598c71e8ee22fd  research/data-collection/pilot/raw/epa-availability.json
8d153c5563da057b3f6978aa4ceb06f4c158edbd62d329935cecaa705b2a5ee9  research/data-collection/pilot/raw/epa-pm25-alameda.json
da3466166bde7723e68d3e7444a7fa704733069b95611c53eeaca36b5bc77e6a  research/data-collection/pilot/raw/fbi-cde-violent-crime.json
146217a663ce140faf0a785ee52a51ae858df8bb23d9006af558d7fdddae0d9c  research/data-collection/pilot/run_pilot.py
57a87b3ee38d10e2639e88c8d4e6bf16eabce0ea826fbff089ad0cab2a33f1d1  research/data-collection/pilot/test_run_pilot.py
```

## Implementation evidence

- Full live pilot: exit `0`; all six credentialed probes report `pass`; 10
  normalized records.
- Unit tests: 9 passed.
- Syntax check: `run_pilot.py` and `test_run_pilot.py` compile.
- Credential file: mode `600`; all seven environment variables are present (EPA
  uses separate email and key variables).
- Credential-value scan under the project root: 0 matches.
- Persisted pilot-artifact scan for sensitive query-parameter names: 0 matches.
- Runtime/artifact scan for `DEMO_KEY` and the shared EPA test account: 0 matches.
