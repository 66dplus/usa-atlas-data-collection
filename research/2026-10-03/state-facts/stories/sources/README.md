# Story source monitoring

The working registry contains **24 sources**, including 16 RSS candidates and 8 official/data/publisher search references. The start-of-session documented bounded invocation at 2026-10-05 10:24 UTC selected no sources because none were due; it made no requests and retained 88 cumulative URL leads. A second status check at 10:39 UTC also selected no sources, made no requests and recorded no new leads, matches, failures or blocks. The latest due-source fetch remains 2026-10-05 09:31 UTC: 7 of 8 selected sources supplied usable metadata, Census returned HTTP 200 but the parser found no usable title/link records, and the run recorded 70 new URL leads and 7 topic matches (88 cumulative). See the two no-due manifests and the 09:31 manifest for receipts. Feed leads are discovery pointers only, not verified stories or numeric observations.

At the 2026-10-05 09:31 UTC documented refresh (`python3 stories/sources/collect_sources.py --limit 8 --budget-seconds 240`), 7 of 8 selected feeds returned usable metadata. BLS, NPR Business, The Texas Tribune, CalMatters, NPR Technology, The Colorado Sun, and THE CITY supplied 70 unique URL leads and 7 topic matches; cumulative leads are 88. Census returned HTTP 200, then parser error `no usable title/link records in feed`; this was not retried. Per-feed response bytes, headers, hashes, counts, exact error and artifact hashes are in `snapshots/20261005T093103095104Z/manifest.json` and `receipts.json`. The feeds provide metadata only and no article bodies were archived.

The THE CITY feed yielded two New York housing leads dated October 1: a federal rent-voucher story and a Mamdani administration affordable-housing districts story. Their lead URLs use `thecityreporter.nyc`, while the registry publisher is THE CITY and the observed RSS channel title is “The City Reporter”; canonical URL and publisher identity need resolution. One direct access attempt for each corresponding article path on `thecity.nyc` returned “not accessible via this tool.” Both remain unverified leads in `../batch-20261005/candidate-leads.json`; no mirror or alternate article copy was used. A separate San Francisco Chronicle report says 180 Chevron employees were expected to relocate from San Ramon to Houston by September 1, but the date has passed and no original EDD notice or completion evidence has been retrieved. That lead is held for follow-up rather than counted as a verified move.

Working feeds: BLS latest numbers, NPR Business and Technology, The Texas Tribune, CalMatters, The Colorado Sun and THE CITY feed. The latter supplies channel title “The City Reporter” and links to thecityreporter.nyc; confirm the publisher on each opened article page. Texas Tribune feed links are redirects; their final publisher URLs remain unresolved until research opens them. Geographic publisher hints are separate from article geography.

Census RSS returned HTTP 200 but yielded no usable title/link records. The collector records `parse_or_budget_error`; no feed-index lead is promoted. The recent exact error and response receipt remain in the run manifest. Census’s [RSS directory](https://www.census.gov/about/contact-us/feeds.html), [state flow tables](https://www.census.gov/data/tables/time-series/demo/geographic-mobility/state-to-state-migration.html) and [IRS migration tables](https://www.irs.gov/statistics/soi-tax-stats-migration-data) remain official verification/search references.

## Run as part of the existing research session

```bash
python3 research/2026-10-03/state-facts/stories/sources/collect_sources.py --limit 8 --budget-seconds 240
```

Only due feeds are selected, oldest checked first. Default limits: 8 sources, 80 items/feed, 2 MB/response, 15-second network timeout and a 240-second process alarm; hard argument ceilings are validated. A file lock prevents concurrent collections. Feeds are checked against the actual host’s robots.txt for `USA-Atlas-Source-Monitor/1.0`; Missing robots.txt (404), inaccessible robots.txt, disallowed paths and failed HTTP requests remain explicit. HTTP 401/403/429 defer the next automatic check 72 hours; there are no retries in a collection run. Selected successful sources refresh after 24 hours. `--source <id>` chooses specific entries; `--force` ignores due dates but never bypasses access restrictions.

`build_registry.py` records initial curation; do not rerun it over a populated registry because it resets monitoring state. Extend `registry.json` deliberately, retaining last_checked/status/evidence. Publisher/access notes record actual observed endpoints or cited pages, not a general grant to scrape. [Texas Tribune guidelines](https://www.texastribune.org/republishing-guidelines/) contain source-specific conditions and exclusions. [Guardian feed help](https://www.theguardian.com/help/feeds) describes personal/noncommercial use; Guardian is therefore reference/search only in this workstream. Forbes likewise has no collector configured, following the existing Atlas collection plan.

## Artifacts

- `registry.json`: publisher, homepage, feed/API URLs, source role, tags/geography, access method, robots/terms observations, last check, status and next refresh.
- `leads.json`: cumulative deduplicated URL/title/date metadata, source provenance, first/last seen and topic/geography lexical candidates; capped at 20,000 rows.
- `story-candidates.json`: currently matched library leads for human/LLM research.
- `query-templates.json`: 16 reusable media-search templates, including state-pair migration, wealth moves, company headquarters, taxes, housing, jobs and data centers. These are explicitly unexecuted search tasks, not scrape-ready sources.
- `snapshots/<run>/`: HTTP receipts with status, bytes, feed SHA256/headers; per-source outcomes; normalized metadata leads, candidates and manifest.
- `latest.json`: most recent run, which may be a focused error check; use `registry.json` and `handoff.json` for overall state.
- `handoff.json`: corrected counts and continuation instructions.

Full RSS payloads are never saved because some feeds embed complete copyrighted articles. No linked articles, images, audio or full descriptions are downloaded or archived. Robots/feed response hashes and sizes establish what was observed without preserving article bodies. The collector never uses credentials or installs a service.

## 2026-10-04 receipt and access notes

The run at 10:20 UTC was the bounded start-of-session check. `snapshots/20261004T102055387420Z/manifest.json` is the pre-session bounded run: status completed, no sources selected, no requests, 80 cumulative leads, 0 newly matched leads. The previous due-source receipt is `snapshots/20261004T093048306624Z/manifest.json`: 8 sources selected, 7 collected, 70 unique metadata leads, 7 topic matches and 80 cumulative leads. `census-news` returned HTTP 200 but failed parsing with the exact error `no usable title/link records in feed`; no aggressive retry was made. Publisher and response hashes remain in the manifest.

Topic-match review focused on concrete state/local candidates, including the Valar Utah proposal and New York affordable-housing coverage. The THE CITY feed returned metadata successfully, but its direct story page returned “Blocked by robots.txt” when opened. The direct THE CITY article remains an unresolved media lead. The related housing-policy story was independently reviewed through amNewYork, QNS and the NYC Mayor’s Office; no mirror or proxy was used for THE CITY. Other matched headlines without specific state geography were not promoted.

## Research handoff

1. Refresh due sources with the command above and retain failures.
2. Read candidates and choose a few links with concrete geography and an interesting comparison. Open the original publisher URL, record its date and exact claim, then follow its underlying official/company source.
3. Use the 16 templates to fill old/historical stories and missing states beyond today’s RSS window; substitute state/origin/destination/year. A small daily RSS window is not50-state coverage.
4. Build story records in the parent workstream with source URLs,observation period,media narrative,primary verification,origin/destination state codes and contextual Atlas indicator IDs. Templates suggest existing catalog IDs; confirm their definitions and numeric availability before linking.
5. Treat income-tax returns/AGI separately from net-worth millionaire counts,company headquarters separately from personal residence,planned data centers separately from operational facilities. Immigration is not auto-tagged as interstate migration; West Virginia no longer double-matches Virginia. Washington lexical matches remain candidates requiring DC-versus-state review.

Example leads include Colorado tax-ballot proposals,NYC housing policy,and a proposed nuclear-powered data-center project in Utah. They are pointers to investigate, not admitted facts. Proposed taxes are not current tax law; planned sites are not operational counts. Media narratives about why someone moved require direct evidence beyond a tax-rate difference.

Checks performed: real HTTP/RSS runs; URL tracking normalization; dedupe; malformed RSS rejection; RFC date parsing; migration/immigration distinction; geographic overlap handling; metadata-only output inspection; Python compilation. No tests or services were added outside this folder.


## 2026-10-05 no-due feed receipts

The documented bounded start-of-session invocation at 10:24 UTC was run with --limit 8 --budget-seconds 240. Run 20261005T102425880989Z completed with zero sources due, no HTTP requests, no failures, 88 cumulative metadata leads and zero new topic matches. A second status invocation at 10:39 UTC (20261005T103933470397Z) also had no sources due, made no requests and retained the same counts. Their manifests, three-byte empty candidate artifacts and SHA-256 receipts are in snapshots/20261005T102425880989Z/ and snapshots/20261005T103933470397Z/. These checks did not refresh article/feed content. The previous due fetch remains 20261005T093103095104Z; its Census parser error is recorded above and was not retried. No media articles were archived.
