# Completed-data load task packet

Workflow: FULL  
Current gate: Plan Critic  
Goal version: `database-load-v1`  
Acceptance IDs: `LOAD1`–`LOAD5`

Plan: `DATABASE-LOAD-PLAN.md`  
Plan SHA-256: `54922d5baca70b104cb0d6e898dcdc8825c3b978179335d3a7dc9d1a4a103ae5`.  
Global policy SHA-256:
`7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`

Existing schema/loader candidate: `95df3b9f5b45a4407b981c9159d1845915c95023a587c19d87901b9a0c189b33`.

PlanPass: pending.  
Candidate: existing reviewed database candidate; no code changes planned.  
ReviewPass: pending.  
GoalPass: pending.

Current todo:

1. Obtain PlanPass for the exact load plan.
2. Create isolated `usa_atlas` database and run the reviewed loader.
3. Verify counts, deduplication, provenance/time, rerun, and geography inventory.
