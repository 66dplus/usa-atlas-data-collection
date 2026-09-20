# USA Atlas data collection plan

Updated 19 September 2026

Workflow: DIRECT  
Current gate: Direct

## Outcome and current baseline

The source catalog contains 81 metric rows across demographics, housing, work, crime, mortality and health, homelessness, taxes and wealth, prices, food access, recreation, and air quality. The original file is preserved at `source/us_map_statistics_catalog.docx`; its SHA-256 is `f4460c959b951f286b0fb0854c434102febf843749d48645a611aad589969f1b` and matches the supplied file byte for byte.

Before this task, the project had no real-data collection path and explicitly used synthetic values for design exploration. After this pilot, the project has a repeatable small probe, seven normalized sample records, a source-by-source constraint audit, and a staged plan for collecting approved data without treating IP rotation as a substitute for provider permission.

### Current pilot acceptance

1. **P1 Source preservation.** The supplied DOCX is stored inside the project and its SHA-256 matches the original.
2. **P2 Source audit.** Every named source family or unresolved source class has an observed status, relevant limit or obstacle, and next acquisition path.
3. **P3 Small collection.** The repeatable probe produces normalized records from at least five independent source families and does not require paid credentials.
4. **P4 Verification.** The probe compiles, raw archives validate, normalized records match the minimum schema, and their source keys are unique.

## Final goal

Build a repeatable, policy-compliant pipeline that collects every approved catalog metric at its defensible geographic resolution, retains raw source evidence and methodology, and reports unsupported or unlicensed metrics explicitly instead of silently substituting data.

### Will be done

1. **DC1 Catalog contract.** Every one of the 81 metric rows has a stable `metric_id`, exact definition, source, source release, geography, unit, transformation, update cadence, and license status. Verification: the catalog validator reports 81 mapped rows and zero undefined required fields.
2. **DC2 Source access.** Every chosen source has a tested API, bulk-download, or licensed acquisition path plus credentials and a documented quota. Verification: one representative raw response and one normalized record per source family, or an explicit `blocked`, `source_unselected`, or `not_authorized` result.
3. **DC3 Data integrity.** Raw counts, rates, suppression, coverage, confidence intervals, and source caveats survive normalization. Verification: fixture comparisons against the source for at least one state and one county, with hashes for downloaded releases.
4. **DC4 Small end-to-end pilot.** California and Alameda County are collected for one recent period where the source supports them. Verification: ingestion produces a coverage report, normalized records, and no duplicate `(geo_id, year, metric_id, source_release)` keys.
5. **DC5 Scalable execution.** Three machines can share work through one job ledger while obeying one provider-wide rate limiter per source. Verification: retrying or reassigning a job does not duplicate output; a simulated `429` honors `Retry-After`; interrupted bulk downloads resume or restart with checksum verification.
6. **DC6 Commercial and ambiguous metrics.** Retail/menu prices, consumer debt, insurance cost, millionaire counts, and billionaire residence data are either defined and licensed or remain disabled with a visible reason. Verification: no production job runs for a source whose license status is not `approved`.
7. **DC7 Full-scale readiness.** A dry run estimates requests, bytes, duration, and refresh cost before nationwide collection. Verification: the plan records expected and observed volume per source, then a nationwide run starts only after the estimate fits quotas and storage limits.

After final verification we will get a data pipeline with explicit coverage and provenance, not merely a scraper that happens to return rows.

## Pilot result

Run:

```bash
python3 research/data-collection/pilot/run_pilot.py
```

The credentialed pilot reads `CENSUS_API_KEY`, `EPA_AQS_EMAIL`, `EPA_AQS_KEY`,
`EIA_API_KEY`, `BLS_API_KEY`, `SOCRATA_APP_TOKEN`, and `BEA_API_KEY` from
`~/.config/usa-atlas/credentials.env`. That file must remain outside the project and
have mode `600`. The pilot never falls back to `DEMO_KEY`: it exits nonzero until all
six credentialed provider probes pass. Keys may be supplied through the process
environment for isolated tests, but must never be written to project files or shell
history.

The 19 September 2026 run produced 10 normalized records: Alameda County population, median household income, and median gross rent from Census ACS; California unemployment; California violent crime; three Alameda County CDC PLACES measures; California residential electricity price; and California regional price parity. Manual probes also parsed a 2022 IRS SOI state workbook, a 2025 USDA Food Environment Atlas archive, and a CDC WONDER XML result. Exact machine-readable status is in `pilot/probe-results.json`; normalized records are in `pilot/normalized/pilot-samples.json`.

## Source and limit audit

| Source family | Pilot | Confirmed limit or obstacle | Collection path |
| --- | --- | --- | --- |
| [Census ACS](https://www.census.gov/data/developers/guidance/api-user-guide/query-components.html) | Credential needed on the current shared IP | Up to 50 variables per query and 500 queries per IP per day without a key; the observed request redirected to `missing_key.html` | Register one project key, batch variables, query all counties in a geography batch, cache by release |
| [BLS LAUS API](https://www.bls.gov/developers/api_faqs.htm) | Pass | Unregistered: 25 queries/day, 25 series/query, 10 years; registered: 500 queries/day, 50 series/query, 20 years | Register, pack series into each request, store release metadata |
| [BLS OEWS files](https://www.bls.gov/oes/tables.htm) | Blocked from this environment by Akamai `403` | State ZIP and all-data files exist; current flat file exceeds 50 MiB | Use an approved downloader or operator-acquired release file, then process locally once |
| [FBI CDE](https://cde.ucr.cjis.gov/) | Pass | No numeric public request quota was found in the official material checked; local coverage varies | Start at one request/second, collect by state/year, honor `429` and preserve reporting-coverage metadata |
| [CDC WONDER API](https://wonder.cdc.gov/wonder/help/wonder-api.html) | Pass for national XML; unsuitable for required county mortality | One robot, sequential requests, about one query every two minutes; NVSS API cannot group or filter by state/county | Do not fan out. Use an approved subnational export or replacement public dataset and retain suppression/caveats |
| CDC and NCHS life expectancy | Dataset unselected | The catalog names a family, not an exact release or measure | Choose a county/state life-expectancy release, confirm vintage and suppression, then add a bulk adapter |
| [CDC PLACES](https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-County-Data-20/swc5-untb) | Pass | Socrata defaults to 1,000 rows per request; unauthenticated calls share an IP pool. [App tokens](https://dev.socrata.com/docs/app-tokens.html) receive a higher pool and are not normally throttled unless abusive | Prefer bulk export; otherwise use a project app token and stable pagination |
| [HUD PIT and AHAR](https://www.huduser.gov/portal/datasets/ahar/2025-ahar-part-1-pit-estimates-of-homelessness-in-the-us.html) | Published links found; download blocked by AWS WAF challenge | Direct XLSB returned `202` with `x-amzn-waf-action: challenge`; browser automation was also blocked | Obtain the official release through an approved interactive or alternate bulk path, hash it, then ingest locally |
| [BEA RPP](https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area) | Pass via 39 KB bulk archive | API needs an active key, but the official regional ZIP is available without per-row requests | Download `SARPP.zip` once per release and parse locally |
| [IRS SOI ZIP data](https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-2022-zip-code-data-soi) | Pass; Delaware workbook parsed | No numeric API quota applies to the published release files | Download one national or state release once, hash it, and derive AGI, dividends, gains, and high-income-return proxies locally |
| [USDA Food Environment Atlas](https://www.ers.usda.gov/data-products/food-environment-atlas/data-access-and-documentation-downloads) | Pass; Alameda rows parsed | Current CSV ZIP is about 6.4 MB compressed and contains measures from different reference years | Download once per release, join variable definitions, and keep each variable's own year |
| [EPA AQS](https://aqs.epa.gov/aqsweb/documents/data_api.html) | Own key needed; shared test account returned `429` and `Retry-After: 86400` | No more than 10 requests/minute, wait about 5 seconds between sequential requests | Register a project account; one source-wide worker; use annual bulk files when they reduce requests |
| [EIA API](https://www.eia.gov/opendata/documentation.php) | Historical baseline passed with `DEMO_KEY`; the credentialed pilot requires a project key | Maximum 5,000 rows per response | Use a project key, filters, and explicit pagination; cache annual releases |
| [Forbes Billionaires](https://www.forbes.com/terms-and-conditions/) | Not authorized for automated collection | Forbes terms prohibit automated scraping or collection | Obtain a license or replace the source; do not rotate IPs or proxies |
| Retail and menu prices | Source unselected | Eggs, coffee, Big Mac, and beer do not share one official county-level source | Define geography/freshness first, then license a provider or narrow the metric |
| Gasoline price | Metric and source unselected | Regional, state, and station prices are different products with different licenses and update cadences | Choose geography and whether the layer is an official regional estimate or licensed station feed |
| Consumer debt | Metric and source unselected | Balance, delinquency, and debt type are different products; granular panel data may be restricted | Select a public aggregate and exact geography before implementation |
| Health insurance cost | Metric and source unselected | Premium, employer contribution, marketplace benchmark, and uninsured rate are not interchangeable | Choose one definition; ACS can supply uninsured rate, while premium metrics need a separate source |
| Millionaires | No direct official count | County-level counts are usually commercial | Use IRS high-income returns as a labeled proxy or license a wealth dataset |

## Collection architecture

Use adapters by access mode rather than one generic scraper:

- **API adapters:** Census, BLS LAUS, FBI CDE, CDC PLACES, EPA AQS, and EIA. Each adapter owns request packing, pagination, rate limits, and source-specific error handling.
- **Bulk-release adapters:** BEA, IRS, USDA, HUD, and BLS OEWS. Download one immutable release, verify SHA-256, retain the raw file, and transform locally.
- **Restricted adapters:** CDC WONDER subnational mortality and commercial data remain disabled until a compliant acquisition path exists.

The normalized table keeps the document's proposed fields and adds `source_release`, `retrieved_at`, `raw_sha256`, `query_hash`, `suppression_flag`, `coverage_note`, `confidence_low`, `confidence_high`, and `license_status`. Raw artifacts are append-only by release; normalized data can be rebuilt from them.

## Three-machine scaling

The local computer and two servers should increase local processing capacity and resilience, not multiply a provider's quota.

1. Keep one small job ledger with deterministic job keys such as `source/release/geography/page`.
2. Give each source one global token bucket shared by all three machines. A worker leases a job, obtains a source token, writes an atomic raw artifact, and records its checksum.
3. Shard independent work: one machine can download bulk releases, while the others normalize and validate already-downloaded files. API geography shards are allowed only inside the provider's documented quota.
4. Cache immutable releases and use conditional requests where supported. Do not fetch the same release independently from every machine.
5. Honor `Retry-After`, exponential backoff, and jitter. Stop a source after repeated authorization, schema, or policy failures instead of changing IPs.
6. Keep proxies off by default. A proxy is acceptable only when the provider permits it for network routing or reliability, and it must still use the same project identity and global rate limiter. Proxy rotation to evade quotas, WAFs, or terms is out of scope.

## Execution phases

### Phase 1 Definitions and credentials

Freeze the ambiguous product definitions, register official project keys, and build the 81-row metric contract. This is the only stage that needs owner decisions about paid/licensed data.

### Phase 2 California and Alameda pilot

Complete DC2-DC4 for one state, one county, and one recent period. Add Census and EPA after credentials; resolve HUD and OEWS acquisition; choose a subnational mortality path. Compare every normalized value with its source and record suppression and coverage.

### Phase 3 Nationwide official data

Run bulk sources first, then low-request APIs, then slower sources. Measure `expected requests/bytes -> observed requests/bytes` per source. Two consecutive runs without improved coverage require changing the acquisition path rather than adding more workers.

### Phase 4 Commercial fun layers

Evaluate license, refresh frequency, geographic coverage, and cost on 5-10 representative locations. Only approved sources enter the job ledger.

### Phase 5 Production refresh

Schedule by source cadence, retain release manifests and raw hashes, alert on schema/coverage changes, and publish only after completeness and provenance checks pass.

## Maintainability impact

1. Outcome: replace synthetic-only data exploration with a separately auditable real-data path; the existing design lab remains untouched.
2. Owners: each source adapter owns acquisition; normalization owns the shared schema; the UI only consumes published normalized releases.
3. Failures and rollback: raw releases are immutable; a bad normalized release can be removed and rebuilt without re-fetching. Suppression and partial coverage are explicit.
4. Reuse and dependencies: prefer official APIs, release files, and the Python standard library. Add format libraries only when a required official format such as XLSB cannot be parsed reliably otherwise.
5. Tests and evidence: source fixtures, schema checks, coverage counts, hashes, a real one-state/one-county run, and a combined nationwide dry-run report.
6. Documentation: this plan and the source catalog are the current documentation. `PRODUCT.md` and the app README change only when real data becomes user-visible or new run commands become part of the product workflow.
