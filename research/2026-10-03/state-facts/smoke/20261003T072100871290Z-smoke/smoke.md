# State-facts source smoke — 2026-10-03

## Focused check

Checked the existing Maine seed `US-23-ACS2024-age` (Atlas field `01.02`, Age). A live search found and opened the U.S. Census Bureau's [2024 ACS 5-Year Detailed Table B01002, “Median Age by Sex”](https://data.census.gov/table/ACSDT5Y2024.B01002). The Census result identifies the table universe as the total population and the release as the 2024 ACS 5-year detailed tables. This matches the seed's 2020–2024 period and the field contract for `01.02`.

## Finding and access limit

The saved, hash-verified source evidence contains Maine's B01002_001 estimate of **44.8 years**, with a **90% margin of error of 0.1 years**. The source register identifies the official source file as the 2024 ACS 5-year B01002 data, last modified **2026-01-29**; the corresponding evidence row is in `acs-state-evidence.json`. This local evidence agrees with the existing fact record, but this smoke does **not** count the numeric cell as newly verified live.

The live Census table opened only as a JavaScript-required shell, so it did not expose Maine's state row. A direct state-filtered table URL and a small Census API URL were inaccessible in the browser tool. Opening the official bulk `.dat` source failed because its 26,666,521-byte response exceeded the browser fetch limit. The accessible Census table metadata therefore verifies title, vintage, and universe, while live access to the exact Maine value remains blocked by the browsing path.

No facts, source registers, README, or queue were changed in this smoke session.

## Next action

In the next full research session, retrieve only Maine's `B01002_001E` and `B01002_001M` from the official Census API or parse the already-receipted B01002 source file, then compare the result with the preserved receipt and evidence. Keep the seed's 2020–2024 period and total-population universe attached to any display copy.
