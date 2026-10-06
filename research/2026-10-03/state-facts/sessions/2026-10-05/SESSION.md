# USA Atlas research session — 2026-10-05

## Result

Added four verified, media-led stories to `stories/batch-20261005/stories.json`. They remain research records (`production_admitted: false`) and do not replace or count the 115 baseline fact cards.

1. **IRS flows into Palm Beach County, filing years 2022–2023** (`irs-palm-beach-ny-origins-2022-2023`). MIAMI REALTORS' March 24, 2026 analysis reports $7.070679B domestic AGI inflow and $4.031929B outflow. IRS tables confirm the gross totals and the derived **+$3.038750B net AGI**, while matched returns were 39,704 inbound versus 40,922 outbound. Separate NY-origin routes list Nassau 959 returns, New York County (Manhattan) 734, and Suffolk 732. The three county routes are not summed as the entire New York flow. Exact selected IRS cells and hashes are in [primary-evidence.json](primary-evidence.json).
2. **Public Storage principal office Glendale → Frisco** (`public-storage-glendale-frisco-2026`). Houston Chronicle reporting, the company's February 12 release, and SEC Form 8-K support the headquarters change; the SEC report dates the principal-office change to February 10. The company says it will retain a long-term Glendale presence. This is not a count of staff who moved or a claim that the business left California.
3. **Texas data-center permit directive** (`texas-tceq-data-center-permit-pause-2026`). The Texas Tribune and the governor's September 21 letter verify a TCEQ directive to pause data-center permits pending ERCOT review. The governor requested a compliance update by October 19. Agency implementation, a permit count, and residential bill effects remain unverified.
4. **California data-center load forecast** (`california-datacenter-load-forecast-and-pipeline-2026`). CEC's Planning Forecast says about 1,000 MW / 2% of California ISO peak demand in early 2026 and projects 4,500 MW / 9% by 2040. Axios's September 28 Cleanview map is retained as media context, but its August facility/capacity claims are not merged with or used to verify the CEC load forecast; Cleanview's directly opened tracker now shows an October snapshot.

## Candidate and correction ledger

Five additional items are preserved outside the verified corpus in `stories/batch-20261005/candidate-leads.json`:

- Two October 1 THE CITY housing items remain unverified. The feed channel says “The City Reporter”; the lead URLs use `thecityreporter.nyc`, while the publisher registry is THE CITY. Corresponding article paths on `thecity.nyc` returned “not accessible via this tool.” Canonical URL, publisher identity and story claims need normal source verification; no alternate copy was used.
- A San Francisco Chronicle story says about 180 Chevron employees were expected to relocate from San Ramon to Houston by September 1, 2026, and attributes this to an EDD notice. That date has passed; the exact employer notice and completed moves are unresolved. Search-indexed WARN summaries call it a layoff, while the article quotes the company describing relocation rather than termination. It is not recorded as 180 completed moves or layoffs.
- Axios's Cleanview facility counts are kept as a lead because its August 2026 snapshot was not independently reconciled. They are distinct from the CEC demand forecast.
- MIAMI REALTORS' March 2026 “millionaires” label is retained as a correction lead. Its article clarifies that the figures refer to returns reporting at least $1 million AGI, not people or net worth. IRS 2022 state data, row `AGI_STUB=10`, yields CA 128,900; FL 77,670; NY 69,780; TX 73,930. The media article says FL 77,760, a 90-return difference. The legacy IRS table guide could not be decoded here, so the threshold mapping and discrepancy remain in the queue. The figures are not admitted as millionaire or wealth counts. The pre-existing rejected “12,000 millionaires left New York last year” claim remains rejected and was not revived.

No new health comparison was promoted. I reviewed the read-only compact medical inventory: HIV diagnosis rows distinguish diagnoses from infections acquired; the selected 2024 state series uses age 13+ and crude rates per 100,000. Cancer incidence by type in the current inventory covers 2019–2023, age-adjusted to the 2000 U.S. standard, with under-16 pooled cases suppressed; infant mortality is 2024 final data with county suppression/unstable-rate rules. The opened Axios melanoma article did not establish a matching data vintage and estimator for a state-by-state comparison. Existing health stories were not edited. Any future rates must remain population descriptions, not individual diagnoses or risk predictions.

## Monitoring receipt

Ran the documented bounded command at 09:31 UTC:

```bash
python3 stories/sources/collect_sources.py --limit 8 --budget-seconds 240
```

Run `20261005T093103095104Z` selected 8 feeds; BLS, NPR Business, Texas Tribune, CalMatters, NPR Technology, The Colorado Sun and THE CITY returned usable metadata. Total: 70 new leads, 7 topic matches, 88 cumulative unique leads. Census returned HTTP 200, but the parser reported the exact error `no usable title/link records in feed`; there was no retry. Per-feed endpoints, response metadata, hashes and receipts are in `stories/sources/snapshots/20261005T093103095104Z/manifest.json` and `receipts.json`. No article bodies were archived. Next due feed refresh is October 6 per the registry.

## Coverage and rebuild

Ran `python3 stories/build_library.py` after writing the batch and after tightening the California story's scope. Final output: **66 verified**, **11 candidate**, **1 rejected**, **121 source URLs**, **62 comparison actions**, **no invalid records**. Baseline cards remain separately excluded (`baseline_cards_not_counted: 115`). Thirty-three states have at least one verified story; DC remains separate at zero. Current story coverage: CA 23, TX 20, NY 10, FL 21. The New York–Florida collection grew from 5 to 6 stories; California–Texas grew from 14 to 15. Palm Beach comparisons retain county geographies; the three Atlas actions use the existing county-supported `median-household-income` metric. The CA–TX context actions use existing registered state metrics and do not claim a migration measure, causal reason, or household-bill effect.

Updated `stories/README.md`, `stories/sources/README.md`, and `stories/research-queue.csv`. The queue retains the NY-city housing access work, Texas compliance follow-up, Chevron status, the IRS AGI/wealth distinction and data-code reconciliation, melanoma vintage/suppression verification, and the next source refresh.

## Sources opened

- [MIAMI REALTORS: Palm Beach County and IRS migration data](https://www.miamirealtors.com/2026/03/24/palm-beach-county-1-in-the-nation-in-net-inflow-of-income-from-domestic-migration-per-latest-irs-tax-data/)
- [IRS county migration data, 2022–2023](https://www.irs.gov/statistics/soi-tax-stats-migration-data-2022-2023)
- [Houston Chronicle: Public Storage headquarters move](https://www.houstonchronicle.com/business/article/public-storage-headquarters-california-texas-21938751.php)
- [Public Storage announcement](https://investors.publicstorage.com/news-events/press-releases/news-details/2026/Public-Storage-Announces-PS4-0--A-New-Era-of-Leadership-Growth-and-Value-Creation/default.aspx) and [SEC Form 8-K](https://www.sec.gov/Archives/edgar/data/1393311/000119312526048660/d793613d8k.htm)
- [Texas Tribune: TCEQ directive](https://www.texastribune.org/2026/09/21/texas-data-center-moratorium-water-energy/) and [governor's letter](https://gov.texas.gov/uploads/files/press/TCEQ_Data_Center.pdf)
- [Axios: California data-center map](https://www.axios.com/local/san-diego/2026/09/28/data-centers-how-much-power-california) and [California Energy Commission forecast/context](https://www.energy.ca.gov/programs-and-topics/topics/data-centers)
- [San Francisco Chronicle: Chevron planned workforce relocation](https://www.sfchronicle.com/bayarea/article/chevron-layoffs-san-ramon-houston-22340583.php), retained as candidate only



## Second batch: seven additional verified stories

The second research batch was completed at approximately 10:50 UTC. It appended seven records to stories/batch-20261005/stories.json without replacing the first four records already present:

1. Missouri, Iowa, Kansas and Nebraska net domestic-migration components from Census PEP Vintage 2025, linked to the reported Portland, Oregon → Kansas City, Missouri family interview. PEP CSV: 53,555 bytes; SHA-256 92188e29cb0a67dcf95afa7d6c47359409782f086478b70ea4128eb70e223ca9. Summed DOMESTICMIG2021–DOMESTICMIG2025: MO +57,454; IA −8,906; KS −22,373; NE −13,330, for 2020-07-01 through 2025-07-01. Nebraska Public Media's accessible article did not expose its publication date, so published_date remains null.
2. Meta's Lebanon, Boone County, Indiana data-center groundbreaking and planned campus, checked against Indiana Economic Development Corporation. More than $10 billion and construction/operations job counts remain announced projections; delivery or operation is not inferred.
3. PORTS/Pike County, Ohio proposed AI campus and power plan, checked against DOE and AP. DOE's 10 GW generation commitment and AP's report of up to 10 GW including 9.2 GW gas remain separately attributed; a groundbreaking ceremony is not operating capacity.
4. Virginia SCC/Dominion final order: historical base-bill estimates of +$11.24/month in 2026 and +$2.36/month in 2027 for a typical 1,000-kWh Dominion Virginia residential customer; separate GS-5 class effective 2027. Not an observed bill or all-state tariff.
5. Proposed NextEra–Dominion Virginia benefits package: 600 company-announced new jobs and a proposed Richmond co-headquarters tower, with 400 supplier jobs described as expected. SCC PUR-2026-00112 was still under review on 2026-10-05. The announcement does not establish a move out of NextEra's Juno Beach headquarters, merger approval, or delivered jobs.
6. The Geneva, Dupont Circle, Washington, DC office conversion: DMPED groundbreaking on 2026-01-22; 532 planned homes, 60 planned permanently affordable. No homes represented as complete.
7. California Proposition 40 proposal: eligible for the 2026-11-03 ballot on June 17 and reported qualified June 25; official sources describe a one-time tax up to 5% on initiative-defined covered assets over $1 billion and specified exclusions. It is not enacted law and does not measure a billionaire count or migration.

### Pairing, coverage and health scope

Themes now link these records to migration-routes, housing-costs, data-center-boom, energy-tradeoffs, jobs-lifestyle, corporate-moves and taxes-money. California–Texas grew from 15 to 16 verified stories; California–Florida grew from 2 to 3; New York–Florida stayed at 6. New geography includes OR Portland / MO Kansas City, Boone County IN, Pike County OH, Dominion service territory, Juno Beach FL, Richmond VA, Dupont Circle DC and the Geneva site. Original places stay in each record. The 70 Atlas actions use existing metric IDs and show parent-state mapping where applicable; the DC→NYC comparison is kept as a collection prompt without an unsuitable state-level action.

Read-only review of the compact medical-data inventory confirmed its HIV age/universe, cancer type and estimator vintages, suppression, and infant-mortality definitions. No new health story was added because this batch produced no media evidence that matched those exact boundaries. Keep HIV/cancer/infant-mortality rates descriptive and population-level; suppression/missing values are not zero, and a regional rate is not an individual diagnosis or risk prediction. Existing four medical stories were not changed.

No new candidates were promoted and no new rejection was required. Previously recorded unresolved candidate leads and the existing rejected “12,000 millionaires left New York last year” claim remain separate. The PEP/media publication-date limitation is stored as null in the verified story plus a queue follow-up, not guessed.

### Feed monitoring

Ran the documented bounded collector at session start, python3 stories/sources/collect_sources.py --limit 8 --budget-seconds 240. Run 20261005T102425880989Z selected no due sources and made no requests. A second status check, 20261005T103933470397Z, did the same. Both no-due receipts retain 88 cumulative URL leads, zero new matches and no failures; neither is represented as a content refresh. The preceding due fetch at 20261005T093103095104Z supplied 70 metadata leads and 7 topic matches. Census yielded HTTP 200 but the parser error “no usable title/link records in feed”; it was not retried. Receipts and hashes are in stories/sources/snapshots/. No article bodies were saved.

### Final library rebuild

Ran python3 stories/build_library.py after appending this batch. It reports 73 verified, 11 candidate, 1 rejected, 139 unique source URLs, 70 comparison actions, and no invalid records. 38 of 50 states have verified stories; DC is separate and now has 1. California has 24, Texas 22, Florida 23 and New York 10. Baseline facts remain excluded (baseline_cards_not_counted: 115); production admission remains false. Updated stories/README.md, stories/sources/README.md, and stories/research-queue.csv. Next source due-check is October 6; project implementation, the October 19 Texas TCEQ follow-up, medical estimator/suppression research, and the post-election Prop 40 status remain queued.
