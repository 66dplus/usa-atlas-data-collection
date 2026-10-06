# Additional CDC surveillance measures

Collected 2026-10-05 into a separate research bundle. This bundle does not change the core medical schema or combine counts and rates. Numeric observations are in `observations.csv` / `observations.json`; actual coverage and source limitations are in `coverage.json`; downloads and hashes are in `../http-receipts.jsonl` and `source-checks.json`.

## Sexually transmitted infections

CDC's official 2024 provisional download supplied nine national spreadsheets covering years 2015–2024. The collection retains 2024 as provisional, with the source cutoff of 2025-08-14. The archive and CDC landing page both returned HTTP 200. The ZIP is 101,460 bytes with SHA-256 `b02c137cd63cd25a49a896a7cbf0fcf0ca614b58e4ec09b86969b3fc65f82439`.

The 534 numeric observations include reported case counts, published rates, and stage/sex strata for chlamydia, gonorrhea and syphilis. Additional measures include primary and secondary syphilis counts by sex and partner category; congenital syphilis counts by infant year of birth; and total and primary/secondary syphilis rates among women ages 15–44. Source labels, period basis, source workbook/member and cell references, numeric values, sex strata, and archive/member hashes remain on each record. These data are observed national reports, not prevalence estimates.

CDC says 2024 geographic data were withheld while NNDSS migrates to the One CDC Data Platform. Therefore these spreadsheets have U.S.-national geography only: District of Columbia included, U.S. territories excluded. National case counts include reports among non-U.S. residents. The ZIP does not publish exact denominator counts. General STI rates use the population denominator appropriate to the displayed sex group; the women's syphilis measure uses women ages 15–44. CDC specifies that the provisional congenital syphilis rate uses 2023 live births and other provisional case rates use 2024 population estimates. No state/county values are assigned from the national records.

The main CDC report treats total syphilis as all stages including congenital syphilis. Congenital syphilis counts in the workbook are by infant year of birth, distinct from surveillance report-year series. A published zero, if present, remains numeric; blank and nonnumeric source cells are not converted to zero. No cells were blank or suppressed in the collected workbooks.

## Tuberculosis

The current CDC `Reported Tuberculosis in the United States, 2024` reporting-area page contains annual 2023 and 2024 case counts, published incidence rates, and a July 1, 2024 population column. The page and 2024 technical notes returned HTTP 200; source HTML hashes and retrieval times are recorded in the receipts. There are 122 records per metric across two years: 61 rows per year including the U.S. national row, 52 U.S. reporting areas, and eight territories/freely associated states.

CDC's National Tuberculosis Surveillance System counts incident TB disease cases verified under the CSTE surveillance definition and countable for morbidity statistics; latent TB infection is excluded. Areas report cases through the standard Report of Verified Case of TB (RVCT) form. The revised form was first fully implemented across jurisdictions in 2023, and CDC cautions that minor data quality/completeness fluctuations may result. Counts are tabulated in the year a reporting area verified and included the case in its annual count. State tabulations follow reported residence. Published rates are annual crude cases per 100,000; they are not age adjusted.

The 2024 source population number is preserved as printed. The page's rates use official Census Bureau resident-population estimates. It does not print a 2023 population count for every reporting area, so the normalized 2023 denominator values stay null while the published 2023 rates remain as given. The U.S. aggregate excludes American Samoa, Federated States of Micronesia, Guam, Marshall Islands, Northern Mariana Islands, Puerto Rico, Palau, and U.S. Virgin Islands; those source rows are retained separately.

New York City is a separate CDC reporting area. The New York State row explicitly excludes New York City; it is identified as a distinct state reporting-area series with a boundary caveat. No FIPS is assigned to the New York City aggregate. The table has no county-specific routine TB incidence counts or rates. CDC's separate 2023–2024 recent-transmission county map covers a narrower genotyped-case-derived measure: 1,903 counties had no genotyped cases that could be evaluated. Its count categories and availability must not be treated as total county TB incidence or numeric zeros. County collection remains queued.

## Hepatitis: current availability check

CDC's current HepTracker landing page returned HTTP 200 and embeds a public Power BI viewer (`DVH_HepTracker_Final_Jan26`). CDC describes NNDSS data as reported confirmed cases for hepatitis A, hepatitis B (acute, chronic, perinatal), and hepatitis C (acute, chronic, perinatal); it states 2024 data are provisional, updated as of 2026-01-17, and expected to be finalized in fall 2026. The selected 2023 AtlasPlus state series for hepatitis A and acute B/C remain distinct from chronic infection prevalence, seroprevalence, and deaths.

No 2024 numeric hepatitis export or documented machine-readable endpoint was verified in this session. The public Power BI viewer is evidence that a dashboard exists, not proof that its data were downloaded. Continue by checking CDC's finalized release and documented download route, and preserve hepatitis B/C acute, chronic, and perinatal case definitions separately.

## Cancer source check (existing core records)

The live NCI State Cancer Profiles `output=1` all-sites incidence route returned HTTP 200 for state and county exports on 2026-10-05. Both headers show 2019–2023, all races, both sexes, all ages; they retain the average annual count and rate with 95% CIs. The state CSV is 8,306 bytes (SHA-256 `753bfc03e5df2f0436e8ec580519f25fbcd3bad61a876561390160f210eab716`); the county CSV is 331,475 bytes (SHA-256 `98abf0ad4b88da7af9636c59d92789736d6a1259969f82f323cfe019d6c80643`). These audit exports match the already-normalized 2019–2023 release and were not duplicated into the additional bundle.

Current NCI/CDC documentation was checked separately. State Cancer Profiles says incidence is provided by CDC NPCR and NCI SEER, population counts are Census-based as modified by NCI, and rates are calculated using SEER*Stat. CDC's current USCS denominator notes specify NCI-modified bridged-race denominators for incidence through 2023 and Census single-race estimates for cancer death rates in 2018–2024. Its current 2025-submission public-use documentation covers diagnosis years 2001–2023, identifies ICD-O-3 site/morphology fields, reports 100% coverage for 2003–2023, and applies suppression below 16 cases for the time period. The current release documentation is not used to relabel the separate State Cancer Profiles exports; annual versus pooled periods and source populations remain attached to the existing normalized rows.

## Reproduction

`python3 collect_additional_surveillance.py fetch` refreshes the five official landing/data/documentation pages using bounded 30-second requests and byte caps. `python3 collect_additional_surveillance.py normalize` verifies each downloaded file against its most recent successful HTTP 200 receipt and hash, parses the official STI spreadsheets and TB HTML table using Python's standard library, deduplicates by measure/period/geography/subgroup, and writes normalized files and source coverage. No automated tests were added or run.
