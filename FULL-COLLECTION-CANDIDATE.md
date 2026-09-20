# Full collection candidate manifest

Goal version: `full-collection-v1`  
Acceptance IDs: `FC1`–`FC6`  
Plan SHA-256: `8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781`  
Global-policy SHA-256: `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`  
Baseline commit: not applicable — workspace is not a Git repository  
Candidate digest: `7d9760d8f9463e616f8a06b74dfed834a3f725d7fe6812dcfc0420e81f34c46d`

The digest is SHA-256 of the following sorted lines exactly as shown by
`<sha256><two spaces><path><newline>`:

```text
1a8a60c9b30afe63e7b756855a43f86c2a3d95a7eba0b06d08bfa57f2a87d72c  research/data-collection/full/collect.py
311d41698d8b0d05c7b23a7d93601a35889d7c3d3916aed1a60b03a24e18f8b9  research/data-collection/SCALING-PLAN.md
38c6e9c0ff119f9196c595b69fa62d1c70ad9bf595dc8a6ac771f55d441c413a  research/data-collection/full/build_contract.py
5c3218041778bcd293951941ee580518544effb21146225065e210a8ccf2ff2a  research/data-collection/full/test_collect.py
7f949db21a832f397035b327eb9e3742e14a58e1aed3bafa94b2ec9538887c01  research/data-collection/full/adapter-config.json
8b9ac1e9c6696eb43d97830332712376500b467e91287f9b968e35424822c781  research/data-collection/FULL-COLLECTION-PLAN.md
e03e10e847613af67be9b82213218707a59edeccc590ef1f5494a169e6af3a84  research/data-collection/full/README.md
e321baf79add3320961fab36f1e3c62630f46ad2c886e3e77b2a8099bb73603e  research/data-collection/full/field-contract.json
ec6b0fe2da1c3de01d739969dda4257f6fce700bf5495a2ac56bbe339f76f0a4  research/data-collection/FULL-COLLECTION-CHECKPOINT.json
```

All listed paths are untracked workspace files because no Git repository exists.
`FULL-COLLECTION-TASK.md` is the mutable gate packet and is intentionally excluded to
avoid a self-referential hash. Generated `full/raw`, `full/normalized`, `full/state`,
and `full/FIELD-EVAL.json` are runtime state and excluded from the candidate digest;
their immutable checkpoint facts and bound hashes are frozen in
`FULL-COLLECTION-CHECKPOINT.json`.
