# USA Atlas load evidence

Verified at `2026-09-19T16:47:48Z` (UTC) against the completed collector manifest.

## Commands

- `python3 research/data-collection/database/load.py load --all`: exit 0; all 8
  manifest-`pass` sources loaded.
- A second `load --all`: exit 0; all 8 sources reported `skipped` and no counts
  changed.
- `python3 research/data-collection/database/load.py verify --all`: exit 0;
  `checks.idempotent=true`.

## Database assertions

| Assertion | Observed |
|---|---:|
| Target database | `usa_atlas` |
| Catalog fields | 81 |
| Total observations | 1,031,001 |
| Distinct canonical keys | 1,031,001 |
| Duplicate groups | 0 |
| Passed ingest runs | 8 |
| All ingest runs | 8 |
| Missing observation provenance | 0 |
| Missing ingest provenance | 0 |
| Census rows | 0 (Census manifest status is `fail`) |

Every ingest run has its source, normalized artifact path/hash, contract hash,
row count, `started_at`, and `completed_at`; observations retain source,
release, sanitized URL, and `retrieved_at` in PostgreSQL.

## Source × geography inventory

| Source | Geography | Rows | Distinct geographies |
|---|---|---:|---:|
| bea_rpp | state | 884 | 52 |
| bls_laus | county | 154,608 | 3,221 |
| bls_laus | state | 2,496 | 52 |
| cdc_places | county | 8,871 | 2,957 |
| eia | state | 310 | 62 |
| epa_airdata | monitor | 19,583 | 1,694 |
| fbi_cde | state | 3,266 | 52 |
| irs_soi | zip | 827,595 | 27,588 |
| usda_fea | county | 13,388 | 3,142 |

The unrelated `elderly_mvp` database remains present and unchanged. No `place`,
`tract`, city-neighborhood, or city-district rows are in this load; those become
eligible only after a complete Census artifact reaches manifest `pass`.
