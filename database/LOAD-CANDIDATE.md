# Load candidate manifest

Workflow: FULL  
Goal version: `database-load-v1`  
Plan SHA-256: `f75dedbfbecd57c5940cbc3bf33ab916b72dbe23abb62eb118134679d4fac775`  
Global policy SHA-256: `7ffbb97fa06dc153aaef643a165a8cacee56bc920ef651f1fbbc5b70fe45157f`  
Candidate SHA-256: `0dc8f2c3ddfa18dfbdfaad786e0a904c11698c84da6497ef03d2fa39877fd8ed`

The workspace has no Git repository; the manifest therefore binds the exact
filesystem bytes used for review and runtime verification.

| Path | SHA-256 |
|---|---|
| `research/data-collection/database/LOAD-PLAN.md` | `f75dedbfbecd57c5940cbc3bf33ab916b72dbe23abb62eb118134679d4fac775` |
| `research/data-collection/database/LOAD-TASK.md` (packet, bound separately) | `a479290f25347c03b04e953f575a4badfbba7edaaa3eb638d980e928ebedc1b8` |
| `research/data-collection/database/README.md` | `879e40158d6593d8ed21e248a68cafb8047cb53f67eb9f7b4a62353cdc02ec74` |
| `research/data-collection/database/load.py` | `9b24fe59b75b2e4f1446715a0c7a6471f5578dbf75a46ef3e8e3cdf6d910a2af` |
| `research/data-collection/database/schema.sql` | `85cf4e458eea7b859563ceb6c4b8ade5eec66237ce190b290720674a176bea9a` |
| `research/data-collection/database/test_database.py` | `244cfeeb51ba079937375587e41dac5fcf123f65612c8f18f19b18534b311618` |

The candidate digest is the SHA-256 of canonical JSON containing the plan hash,
global policy hash, and the five implementation files above (`LOAD-PLAN.md`,
`README.md`, `load.py`, `schema.sql`, and `test_database.py`), sorted by path.
The task packet is separately bound by its own file hash to avoid a circular digest.
