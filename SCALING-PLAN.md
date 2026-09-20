# Compliant two-day scaling plan

Date: 19 September 2026  
Scope: one local machine plus two servers  
48-hour verdict: `unknown` pending expanded Census storage/throughput measurement  
Buy proxies: `no` (recommendation only; no purchase is authorized)

## Conclusion

Proxies do not improve the critical path. BLS, EPA, EIA and Socrata limits attach to
the registered account, key or application; CDC WONDER's location restriction and
Forbes' automation prohibition are policy/source limits; HUD and OEWS returned access
challenges that must not be bypassed by IP rotation. Extra hosts should separate API
acquisition from bulk parsing and validation, while every provider keeps one shared
limiter.

The measured providers fit comfortably inside 48 hours, but the accessible 46-field
v1 queue remains formally `unknown` until the expanded Census run measures compressed
storage and elapsed time. All 81 fields cannot receive a `feasible` verdict while 35
remain blocked by access, definition, source choice, or licensing.

## Local measurements

The bounded local calibration passed all nine active source families with **13 HTTP
requests, 223,248,068 response bytes, 104.647 aggregate request/download seconds, zero
`429`, and zero terminal retries**. The largest transfer was the 216,173,999-byte IRS
national CSV. The first full-run checkpoint then measured:

- BEA: 884 valid SARPP rows, no second transport call;
- IRS: 827,595 geographic ZIP rows after excluding source code `99999`, about 21
  seconds of local parse, no second transport call;
- USDA: 13,388 rows, 2.2 seconds of local parse, no second transport call;
- CDC PLACES: 8,871 rows from one 1.82 MB request;
- EIA: 310 non-null 2024 price rows from one 61 KB request;
- EPA: 19,583 monitor/statistic rows from one 3.79 MB annual archive in 27.1 seconds;
- BLS LAUS: 157,104 rows from 267 transport attempts (including five successful
  retryable-server retries), 13.99 MB, 487 seconds, and zero `429`.
- FBI CDE: 3,266 actual normalized rows from 364 sequential initial requests; the
  cache-only verification rebuild made zero transport calls.

The corrected cache-only rebuild produced **1,031,001 rows across eight completed
families, zero duplicate normalized keys, and zero transport calls**. The frozen
Census contract materializes 706 unique source variables into 15 packs over 157
geography jobs, or 2,355 data requests. Thirty-six unique raw jobs and 111,804 partial
normalized rows were present at the reviewed checkpoint.

Only about 11 GB was free at launch, below the 20 GB planning assumption. The runner
therefore gzip-compresses Census raw/normalized data and enforces a free-space stop.
Until the expanded 706-variable Census run measures its compressed bytes, the formal
48-hour/storage verdict remains `unknown`, even though the completed provider timings
are individually well below 48 hours.

## Verified limit matrix

| Source | Official path | Documented limit / current constraint | Three-host rule |
| --- | --- | --- | --- |
| [Census ACS](https://www.census.gov/data/developers/guidance/api-user-guide/query-components.html) | API, geography wildcards, ≤50 variables/query | Unkeyed: 500 queries/IP/day; project key configured | One shared provider queue; pack variables before geography sharding |
| [BLS API v2](https://www.bls.gov/developers/api_faqs.htm) | LAUS series POST | Registered: 500 queries/day, 50 series/query, 20 years/query, 50 requests/10 seconds | One key-wide daily counter; ≤50 series/request |
| [BLS OEWS](https://www.bls.gov/oes/tables.htm) | Official bulk archive | Current automated probe received `403` | Obtain one approved archive; never proxy around the block |
| [FBI CDE](https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/docApi) | State/year/offense API | No numeric quota found in checked official material | Start one sequential worker at ≤1 request/sec; honor `429`/`Retry-After` |
| [CDC PLACES / Socrata](https://dev.socrata.com/docs/app-tokens.html) | Bulk export or stable pages | App-token pool normally unthrottled unless abusive | One application-wide limiter; do not split token traffic to multiply rate |
| [EPA AQS](https://aqs.epa.gov/aqsweb/documents/data_api.html) | Prefer annual AirData files; API fallback | Sequential, ≤10 requests/minute, ~5-second pause, ≤5 parameters/request, target <1M rows | One worker only for API; bulk parse may be sharded after one download |
| [EIA v2](https://www.eia.gov/opendata/documentation.php) | Paginated API | ≤5,000 JSON rows/response; excess per-second/hour use temporarily suspends key | One conservative key-wide queue |
| [BEA RPP](https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area) | `SARPP.zip` | One release download | Download once; shard local CSV parsing |
| [IRS SOI](https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-2022-zip-code-data-soi) | National CSV/release files | No row API quota; immutable public files | Download once; shard local rows |
| [USDA FEA](https://www.ers.usda.gov/data-products/food-environment-atlas/data-access-and-documentation-downloads) | 2025 CSV ZIP | Published archive about 6.2 MB | Download once; shard local rows |
| [HUD PIT/AHAR](https://www.huduser.gov/portal/datasets/ahar/2025-ahar-part-1-pit-estimates-of-homelessness-in-the-us.html) | Official PIT/HIC workbooks | Current automated probe received WAF challenge | Owner-approved interactive retrieval only; no proxy rotation |
| [CDC WONDER](https://wonder.cdc.gov/wonder/help/wonder-api.html) | Web/API | One robot, sequential, about one query/two minutes; NVSS API cannot group/filter state/county | Disabled until compliant subnational export/replacement exists |
| [Forbes](https://www.forbes.com/terms-and-conditions/) | Licensed/private | Published terms prohibit automated collection | Disabled unless licensed |

## Three-host layout

- **Host A — control/API:** authoritative job ledger, credentials, provider token
  buckets, leases, retries and all provider requests.
- **Host B — bulk intake/parse:** downloads each approved immutable release once,
  verifies SHA-256, then parses deterministic file/table/state shards.
- **Host C — normalization/Eval:** normalizes immutable artifacts, checks schema,
  uniqueness, coverage and provenance.

Do not put a multi-writer SQLite database on a network filesystem. If servers are
activated later, Host A should expose a small lease API or use a server database. Job
keys are deterministic, for example `census/2024-acs5/CA/variables-02` and
`epa/2025/88101`. Workers write a temporary artifact, validate/hash it, atomically
promote it, and only then complete the lease. `429`/`503` honor `Retry-After`; auth,
schema, WAF and terms failures pause the source.

## 48-hour calculation

The accepted plan defines the exact formula. In summary, remaining job cardinality is
multiplied by measured seconds/job and 1.25 retry headroom, then compared with the
documented minimum interval and shared daily quota. Bulk parsing uses measured
bytes/second plus the same headroom. Legally independent providers may overlap;
requests sharing a provider/account/application limit may not. Storage must fit
`1.25 × (measured bytes/job × remaining jobs + immutable bulk bytes)`.

Verdict rules:

- `feasible`: critical path ≤48 hours, storage fits, all required sources calibrated,
  and no proxy/quota-evasion assumption;
- `not_feasible`: a measured/documented bound exceeds 48 hours or storage;
- `unknown`: any required cardinality, throughput, access path or limit is missing.

The local calibration has replaced most planning assumptions. The current queue has
2,355 Census data calls, ≤500 BLS requests/day, about 350
FBI state/offense calls, one PLACES export, one EIA pagination sequence, two EPA bulk
parameter filters, and no more than 20 GB initial storage. A `feasible` verdict for the
46-field queue must never be presented as feasibility for the unresolved 81-field
catalog.
