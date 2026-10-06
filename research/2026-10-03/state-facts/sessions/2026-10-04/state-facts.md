# USA Atlas state-facts research — 2026-10-04

## Work completed

The separate sourced-stories library was rebuilt and remains research-only (`production_admitted: false`). The day's batch now holds 11 verified stories, one candidate and one rejected claim. Ten verified stories were already in the batch before this continuation; this session added the New York City housing-policy story and updated source checks, comparison actions and several evidence records. The 115 baseline cards remain outside these totals.

Key verified records reviewed or revised:

- **California–Texas and New York–Florida migration:** 2024 ACS State-to-State Migration Table 1 values are people age 1+ with each direction and 90% MOE preserved. CA→TX 77,161 (±9,059), TX→CA 45,447 (±6,640), derived difference 31,714; NY→FL 50,661 (±6,714), FL→NY 28,080 (±4,963), difference 22,581. Difference MOEs were not calculated. Census, USAFacts and Texas Tribune evidence remain attached. The AP report on Texas as the leading source for residents of nine states was added to the existing route story. Population Atlas links are explicitly contextual, not migration measures or explanations of moves.
- **New York taxable-income and address-change records:** NY DTF reports 99,404 tax returns with taxable income of at least $1 million for TY2024, while its 2024 high-AGI out-of-state address-change count is 1,679 returns. These are different series and not people or net worth. The “12,000 millionaires left New York last year” claim remains rejected. The Forbes trillionaire headline remains an unverified estimate lead; no official registration category or verified status is claimed.
- **Housing/insurance:** KQED and California DOI support the CA FAIR Plan 29.1% average dwelling-fire rate increase effective October 15, 2026; Citizens Florida's homeowners multiperil average decrease is 8.8% effective July 1, 2026. They are different programs and not comparable family bills. Citizens official county report supports 143,621 PR-M policies across Miami-Dade (71,112), Broward (44,267), Palm Beach (26,228) and Monroe (2,014) at December 31, 2025; Miami-Dade is a county, not Miami city.
- **New York City housing policy:** Accessible coverage from amNewYork and QNS and the NYC Mayor's Office release identify the 12 designated community districts and the January 1, 2027 start of the 90-day review process for eligible proposals. The city release reports 724 of 63,870 new affordable homes over the previous five years (1.1%); QNS reports 883 for that same citywide total. This discrepancy remains unresolved pending the original DCP district dataset. The five-year release period has no exact endpoints, and historical production is not attributed to the future process. The THE CITY article page was blocked by robots.txt; no alternate route was used.
- **Utah proposal:** KSL and East Idaho News were checked against the September 17 SITLA board record and transcript. The state-land deal presented 480 acres initially plus a conditional 160 acres after Utah National Guard relocation. Board authorization to finalize terms is not proof of an executed lease or operating facility; KSL's “more than 640 acres” shorthand is retained as media wording with the primary record's distinction. Federal BLM acreage/reactor/capacity claims remain a candidate, not a verified project.
- **Health stories:** HIV and cancer comparisons retain their original populations, geography and observation periods. Florida's all-population HIV diagnosis-rate series is not mixed with CDC AtlasPlus ages-13+ prevalence. NYC and San Francisco city diagnosis counts are not treated as infection dates or individual risk. CA–KY lung-cancer incidence is the ACS 2018–2022 state series, not the distinct NCI 2019–2023 series. The infant-mortality record was corrected to the final NCHS 2024 period-linked birth/infant-death report, Table 5 by state of residence: Mississippi 323 deaths / 33,473 live births / 9.65 per 1,000; New Hampshire 35 / 11,770 / 2.97. These are descriptive population rates, not an individual diagnosis or prediction.

## Coverage and collections

The rebuild reports **62 verified, 11 candidate and 1 rejected**; 58 verified stories have a media source; 112 source URLs, 56 comparison actions, 14 collections (all with at least one verified story), and 33 states with verified stories. DC is tracked separately and currently has none. States still without a verified story: CT, DE, KS, MD, ME, MI, MN, MO, MT, NE, OH, OR, RI, SD, VT, WV and WY.

Priority collections after rebuild: California–Texas 14 verified; New York–Florida 5; California–Florida 2; housing costs 10; insurance/climate 2; health/local records 4; data-center boom 12. These overlap and are not unique-story totals. County policy counts are kept separate from county migration, and the NYC story does not manufacture a community-district Atlas metric.

## Source-monitoring receipt

- The bounded collector run at `stories/sources/snapshots/20261004T102055387420Z/manifest.json` completed with no feeds selected because none were due; it made no requests. It records 80 cumulative leads.
- The preceding due-source run at `stories/sources/snapshots/20261004T093048306624Z/manifest.json` selected 8 sources: 7 yielded records, 70 unique leads and 7 topic matches (80 cumulative). Census returned HTTP 200 but the parser reported exactly `no usable title/link records in feed`. No aggressive retry was made. Feed and artifact hashes are retained in the manifests.
- Relevant topic leads included a proposed Utah nuclear-powered data center and New York housing coverage. The THE CITY feed was available but the direct article page was blocked by robots.txt. Headlines without specific state geography were not promoted.

## Remaining work

1. Open the original NYC DCP AHFT district dataset, establish its unit definition and exact five-year endpoints, and resolve the city's 724 vs QNS's 883 before using a district production comparison beyond this caveat.
2. Continue CA–TX and NY–FL work with IRS and county/city tables as different populations; preserve reverse flows and suppression. Continue county-to-Miami-Dade research without confusing Miami city, county and metro.
3. Find a net-worth-based millionaire residence series and date/definition; do not infer millionaire status from AGI or individual tax returns.
4. Track the Utah executed state lease and any later permits; locate an original BLM docket for federal-land claims. Keep announced capacity/jobs separate from permitted, built and operating facts.
5. Add distinct stories for under-covered states and subjects, especially local migration, housing/taxes/insurance, corporate headquarters/jobs and operational data centers. Follow the live coverage table; 17 states and DC currently have no verified stories.
6. Continue HIV, cancer-by-type and infant-mortality work only with exact population, period, estimator and suppression/reliability rules from read-only medical evidence and current primary sources.
7. Refresh due feeds with the documented bounded collector; distinguish no-feed-due runs from a completed source refresh and retain access failures.

## Files updated in this session

- `stories/batch-20261004/stories.json`
- `stories/migration/stories.json`
- `stories/research-queue.csv`
- `stories/sources/README.md`
- `stories/README.md`
- Consolidated `stories/library.json`, `stories/library.csv`, `stories/BROWSE.md`, `stories/collections.json`, `stories/comparison-actions.json`, `stories/story-source-register.json` and `stories/coverage.json` rebuilt by `stories/build_library.py`.

Build result: 62 verified, 11 candidate, 1 rejected; 56 comparison actions; 112 source URLs; no invalid records. No tests were run.
