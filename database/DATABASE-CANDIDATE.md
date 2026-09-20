# SQL database candidate manifest

Goal version: `database-v1`  
Acceptance IDs: `DB1`–`DB6`  
Plan SHA-256: `f5f156b925b50e6da8b0fbb09c3f1509e5a2f4ec90613c966e88fa1948e28186`  
Global-policy SHA-256: `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`  
Baseline commit: not applicable — workspace is not a Git repository  
Candidate digest: `95df3b9f5b45a4407b981c9159d1845915c95023a587c19d87901b9a0c189b33`

The digest is SHA-256 of the following sorted lines exactly as shown by
`<sha256><two spaces><path><newline>`:

```text
762470d2cc1690f9471ab02416e7db579640b3eef3b6cf2ab11025960db9e044  research/data-collection/database/README.md
9194e5d7eb072a08d01b584f4769c1e8bf3b8bf6fb0c790d0825c321aa1ce6fe  research/data-collection/database/schema.sql
9d93d3df47e2de6e697920601ac49fa82c8a7b3216fd2271156241ca987d67f3  research/data-collection/database/load.py
dd9c1fedc1183aec19d9f764dfd05a28bc597b52101c4ad919f2de1173df2557  research/data-collection/database/test_database.py
f5f156b925b50e6da8b0fbb09c3f1509e5a2f4ec90613c966e88fa1948e28186  research/data-collection/database/DATABASE-PLAN.md
```

All paths are untracked workspace files because no Git repository exists.
`DATABASE-TASK.md` is the mutable gate packet and is excluded to avoid a
self-referential hash. Runtime PostgreSQL cluster files are temporary and excluded.
