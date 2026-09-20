# FULL task packet — USA Atlas API credentials

- Route: `FULL`
- Current gate: `Goal Eval`
- Owner request: implement the approved six-credential plan
- Goal version: `v1`
- Acceptance IDs: `K1`, `K2`, `K3`, `K4`
- Canonical plan: `API-CREDENTIALS-PLAN.md`
- Repository state: project directory is not a Git repository; candidate identity
  will therefore use a sorted SHA-256 path manifest plus the global-policy hash.
- Plan hash: `dc2b3f77d8b5d2ce383a48a6c9a2b4883784eea1e63c7170bc7cf1da5ae38147`
- Global policy hash: `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`
- PlanPass: `PASS` by `/root/plan_critic`, bound to goal `v1`, acceptance IDs
  `K1`–`K4`, plan hash
  `dc2b3f77d8b5d2ce383a48a6c9a2b4883784eea1e63c7170bc7cf1da5ae38147`,
  and global-policy hash
  `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.
- Candidate manifest: `API-CREDENTIALS-CANDIDATE.md`; candidate tree digest
  `b1924c3bb803df9226a247c7dbf4c3edcd19702451dae9e696803a0401370952`.
- ReviewPass: `PASS` by `/root/code_reviewer`, bound to goal `v1`, acceptance
  IDs `K1`–`K4`, manifest SHA-256
  `bfb474f6c7e7bc4ab273adfa848a9b46ba792d9e40f79b7399f6d13ee10c41e1`,
  candidate tree digest
  `b1924c3bb803df9226a247c7dbf4c3edcd19702451dae9e696803a0401370952`,
  plan hash
  `dc2b3f77d8b5d2ce383a48a6c9a2b4883784eea1e63c7170bc7cf1da5ae38147`,
  and global-policy hash
  `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`.
- GoalPass: not issued. `/root/goal_eval` returned `FAIL` for K2 because the EIA
  form submitted before the required action-time user confirmation. K1, K3, and
  K4 passed. Remediation requires owner-authorized EIA credential rotation with a
  confirmed final submission, or an explicit goal amendment and re-hash.

The six-item maintainability checklist and immutable verification target are in the
canonical plan. No credential values or personal email may be added to this packet.
