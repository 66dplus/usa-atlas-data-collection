# Completed-data load task packet

Workflow: FULL  
Current gate: Closing
Goal version: `database-load-v1`  
Acceptance IDs: `LD1`–`LD6`

## Bound inputs

- Schema: `schema.sql`
- Loader: `load.py`
- Manifest: `../full/state/run-manifest.json`
- Contract: `../full/field-contract.json`
- Global policy SHA-256:
  `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`
- Workspace is not a Git repository.

## Gate evidence

Plan SHA-256: `f75dedbfbecd57c5940cbc3bf33ab916b72dbe23abb62eb118134679d4fac775`.  
PlanPass: PASS by independent critic, bound to plan
`f75dedbfbecd57c5940cbc3bf33ab916b72dbe23abb62eb118134679d4fac775`.  
Candidate manifest: `LOAD-CANDIDATE.md`, SHA-256
`0dc8f2c3ddfa18dfbdfaad786e0a904c11698c84da6497ef03d2fa39877fd8ed`.  
Load evidence: `LOAD-EVIDENCE.md`, SHA-256
`1441a14aa789704b1cb3ae5418f333a4a405c2e85aa1112150d498d06c3ac954`.  
ReviewPass: PASS by independent reviewer, bound to candidate
`0dc8f2c3ddfa18dfbdfaad786e0a904c11698c84da6497ef03d2fa39877fd8ed`, plan
`f75dedbfbecd57c5940cbc3bf33ab916b72dbe23abb62eb118134679d4fac775`, task packet
`c1ea240584dfa083d280ccd77f6e26d14a3014f89c30dc3b2c24de7a9d7e35e7`, and evidence
`1441a14aa789704b1cb3ae5418f333a4a405c2e85aa1112150d498d06c3ac954`.  
GoalPass: PASS by independent evaluator, bound to plan
`f75dedbfbecd57c5940cbc3bf33ab916b72dbe23abb62eb118134679d4fac775`, candidate
`0dc8f2c3ddfa18dfbdfaad786e0a904c11698c84da6497ef03d2fa39877fd8ed`, ReviewPass,
and evidence `1441a14aa789704b1cb3ae5418f333a4a405c2e85aa1112150d498d06c3ac954`.

## Current todo

1. Complete — candidate received independent ReviewPass.
2. Complete — `usa_atlas` contains all eight eligible sources.
3. Complete — counts, provenance, idempotency, and geography verified.
4. Complete — independent GoalPass for `LD1`–`LD6`.

Plan `f65aadc73b57b94212f527f7a4597a6ec0227a280b0778d4fc766c3fd1ed537a`
received `REVISE`. The revised plan pins all commands to an ownership-checked
`usa_atlas` target, requires bounded-disk exact duplicate detection before writes,
enforces the 6-GiB projected-free floor, and adds an executable final verifier plus
deep-geography fixtures.

Plan `d379f942eae216e4af2d45395d88d829c4b42bcad283af8eb2fcf1fd200b0983`
also received `REVISE`. The next revision removes the standalone write path, defines
the ordered no-write bootstrap, uses a capped collision-free SQLite composite-key
index with reserved scratch space, and admits an existing nonempty target only when
its exact schema fingerprint and complete selected-manifest state match.

Plan `61bb1ae77baafe806ad25cc43a735ae736fe439bf03ce7a8f1f09ce82c1a6c9c`
received `REVISE`. The next revision defines an exact empty-database predicate, binds
nonempty targets to a recomputed canonical `pg_catalog` physical-schema digest, and
requires README/bootstrap-command verification.

Plan `f4b5be25c828fbf5c2c9c6d0446c9f0af958fa36928ab831979c5b2b7fac4bfc`
received `REVISE`. The next revision expands the physical digest from named required
objects to the complete non-system catalog and rejects any unexpected user object.
