# Reader v2 consumer protocol draft

Status: candidate / nonreleased. Version 2.0.0 is an additive draft for parent review; it has no release tag.

## Read boundary

The standard release contract identity is `format=usa_atlas_reader_contract`, `contract_id=usa_atlas.application_reader`, `version=2.0.0`. It preserves the standard gate `usa_atlas.ingest_run.status = 'pass'` and adds mandatory v2 filter `usa_atlas.reader_batch.candidate_status = 'admitted'`. Production readers apply both filters to every v2 observation, contest, candidate, party result, availability row, and boundary. Candidate `local_review` access is a separate loopback-only preview mode. The database role has `SELECT` access only.

Version-specific source metadata lives in `usa_atlas.reader_v2_catalog_field`, keyed by `(catalog_field_id, source_release)`. Readers resolve v2 dataset/source contracts through that relation; released v1 `catalog_field` metadata is insert-only and never overwritten. V2 uses explicit period selectors. AIAN broad share extends field `01.04`; FBI 2025 annual estimates use fields `04.01`–`04.07`; elections use `12.01` President, `12.02` Senate, and `12.03` House. IDs `11.01`–`11.03` remain assigned to cancer/HIV/child deaths.

## Scalar observations and periods

Use the complete period identity. `monthly` requires `period_month` 1–12. `annual` has a null month. `multi_year` records retain inclusive start and end years, which is how the 2020–2024 ACS five-year estimate is represented; selectors and cache keys must bind both endpoints. Source period codes remain provenance. BLS `M13` maps to `period_kind = 'annual'`, `period_year = 2025`, and `period_month = NULL`; it is never a calendar month.

```sql
SELECT geo_id,geo_type,value,unit,quality_status,source_release,source_url,
       methodology_note,source_period_code
FROM usa_atlas.reader_observation o
JOIN usa_atlas.ingest_run i USING (ingest_id)
WHERE o.field_id = :field_id
  AND o.period_kind = :period_kind
  AND o.period_year = :period_year
  AND o.period_month IS NOT DISTINCT FROM :period_month
  AND o.period_start_year = :period_start_year
  AND o.period_end_year = :period_end_year
  AND o.source_release = :source_release
  AND i.status = 'pass'
  AND EXISTS (SELECT 1 FROM usa_atlas.reader_batch rb WHERE rb.ingest_id=o.ingest_id AND rb.candidate_status='admitted');
```

The selector and cache key include both inclusive window endpoints for every period: field, kind, label year, month (nullable), start year, end year, source release, and geography. For a multi-year window, bind both endpoints; period_year alone does not identify a window. A no-row result is not a zero. A returned `quality_status` of `missing`, `suppressed`, `invalid`, or `nonmapping_geography` is not a usable map value. A real numeric zero is `observed` with `value = 0`. BLS LAUS uses catalog field `03.06`, dataset `unemployment`, field `03.06:unemployment_rate`, source release `laus-nsa-2025`, and catalog contract `sourceCode=bls_laus` plus `seasonalAdjustment=NSA`. Its source-version field remains `laus-nsa-2025-v2`. The prepared 2025 input contains state and county series only; it does not synthesize a national rate. It preserves all four source components: `03` unemployment rate, `04` unemployed, `05` employed, and `06` labor force. M10 source gaps and Kalawao series-not-returned remain explicit `missing` rows.

## FBI annual 2025

The 2025 FBI SRS annual values use dataset `fbi_crime_rate`, catalog/field pairs `04.01:derived` through `04.07:derived`, annual period 2025, null month, and unit `per 100,000`. Rates divide the official offense count by the population on the same FBI row. Field `04.07` uses `rape_revised`. Native US, all 50 states, and DC are represented. The raw OOXML workbook hash, prepared CSV hash, source URL, and retrieval timestamp are bound by the source inventory. Preserve Florida/North Dakota limited-data markers and the DC special-agency caveat. Do not sum monthly values or use ACS denominators.

## AIAN broad share

The candidate metric on existing field `01.04` is B02010_001E divided by B01003_001E from the same 2024 ACS 5-year product and exact geography, multiplied by 100. Keep the source estimate and MOE fields intact. Do not claim a derived share MOE from the numerator MOE alone. The selected definition includes AIAN alone or in combination and people of all Hispanic origins; race options can overlap, so shares are not expected to sum to 100%. A source county absent from the Census 2017 map stays nonmapping. Do not move its value to a nearby or predecessor geography.

## Election contests and selected-party shares

`contest_id` isolates office, election year, geography, stage, special/runoff flags, source release, and result mode. Preserve candidate-level rows, source candidatevotes/totalvotes text, original and normalized party, row source version, write-in/fusion flags, and all mode rows. `source_mode_raw` and contest `source_mode_values` retain the publisher cell verbatim (including blank). `reported_total_votes` is stored once per contest; a candidate row's repeated source `totalvotes` is provenance, never an addend.

For the map, select only `result_mode = 'TOTAL'`. Do not combine it with `EARLY VOTING`, `ABSENTEE`, `ELECTION DAY`, or any other subtotal. Aggregate candidatevotes by normalized party only when `party_aggregation_status = 'validated'`; ambiguous or repeated candidate cases are quarantined with null shares; a fusion flag alone is not a quarantine when source candidate-party rows remain unambiguous. The denominator is the contest's reported totalvotes (all votes), not only the two leading parties. Candidate share is not turnout or a share of residents. Canonical `stage='general'` has a separate `source_stage_values` array preserving raw source labels such as `GEN` and `GENERAL`; election candidates retain full source rows including original stage and party strings. A blank source mode is stored as `UNSPECIFIED` and quarantined with `source_mode_unspecified`; the source field remains blank and the numeric source-value validity is unchanged. The 2024 President coverage manifest separates 2,778 explicit-TOTAL county geographies, 367 blank-only counties, and 9 vote-center-only counties; blank-mode publisher semantics remain unverified, so these rows do not produce a party result or zero. `source_row_count` records the number of source rows in the exact-hash prepared file assigned to a contest. A validated contest must have a complete pinned file partition; truncation or unknown completeness is quarantined. Known source aggregate classes such as undervotes remain preserved source rows and are not added to candidate party totals.

National PEP values use the pinned Census PEP Vintage 2025 native single-age national file (`census-pep-national-single-age-v2025`, SHA-256 `6436d4f6972d415caf14cb20776807bc031fc9f1bfc9d6ff26055d592a2b0230`). The national total is checked against its unique `SEX=0`, `AGE=999` row for each year. National age 13+ and under-18 denominators are recomputed from that same official national single-age file and compared exactly with the prepared values. This provides the same-year native 2023 denominator for the national IRS per-resident value and cancer crude rate; neither is marked missing when the native denominator is verified. The national cancer numerator is 1,941,540. National HIV and under-18 death rates remain missing because the prepared numerator sources contain state rows only.

Election fields are `12.01` President, `12.02` Senate, and `12.03` House. President uses county geography, Senate state geography, and House congressional-district geography. For a 2024 House general contest, include the 2024 boundary vintage and 119th Congress session in the identity. At-large state districts use Census `CD119FP = '00'`; the nonvoting delegate identifier `98` is not an at-large district. Historical House records without matched year-appropriate boundaries retain their source district identifier with a null boundary vintage and must not join to 2024 district geometry.

```sql
-- Bind the complete contest identity and selected party. The v2 contract marks
-- party_aggregation_status=validated only for a complete, nonambiguous TOTAL set.
SELECT c.geo_id,c.geography_type,c.boundary_vintage,c.congress_session,
       c.election_year,c.stage,c.is_special,c.is_runoff,c.quality_status,
       c.reported_total_votes,c.party_aggregation_status,
       CASE WHEN c.quality_status='observed'
                  AND c.party_aggregation_status='validated'
                  AND c.reported_total_votes > 0
                  AND (SELECT count(*) FROM usa_atlas.election_candidate e
                       JOIN usa_atlas.ingest_run ei ON ei.ingest_id=e.ingest_id AND ei.status='pass'
                       JOIN usa_atlas.reader_batch eb ON eb.ingest_id=e.ingest_id AND eb.candidate_status='admitted'
                       WHERE e.contest_id=c.contest_id AND e.result_mode='TOTAL')=c.source_row_count
            THEN coalesce(p.party_votes,0) ELSE NULL END AS party_votes,
       CASE WHEN c.quality_status='observed'
                  AND c.party_aggregation_status='validated'
                  AND c.reported_total_votes > 0
                  AND (SELECT count(*) FROM usa_atlas.election_candidate e
                       JOIN usa_atlas.ingest_run ei ON ei.ingest_id=e.ingest_id AND ei.status='pass'
                       JOIN usa_atlas.reader_batch eb ON eb.ingest_id=e.ingest_id AND eb.candidate_status='admitted'
                       WHERE e.contest_id=c.contest_id AND e.result_mode='TOTAL')=c.source_row_count
            THEN coalesce(p.party_votes,0)::numeric / c.reported_total_votes
            ELSE NULL END AS selected_party_share_of_all_votes
FROM usa_atlas.election_contest c
JOIN usa_atlas.ingest_run ci ON ci.ingest_id=c.ingest_id AND ci.status='pass'
JOIN usa_atlas.reader_batch cb ON cb.ingest_id=c.ingest_id AND cb.candidate_status='admitted'
LEFT JOIN LATERAL (
  SELECT sum(e.candidate_votes) AS party_votes
  FROM usa_atlas.election_candidate e
  JOIN usa_atlas.ingest_run ei ON ei.ingest_id=e.ingest_id AND ei.status='pass'
  JOIN usa_atlas.reader_batch eb ON eb.ingest_id=e.ingest_id AND eb.candidate_status='admitted'
  WHERE e.contest_id=c.contest_id AND e.result_mode='TOTAL'
    AND e.candidate_kind='candidate' AND e.quality_status='observed'
    AND e.party_normalized=:party
) p ON true
WHERE c.office=:office AND c.election_year=:election_year
  AND c.geography_type=:geography_type AND c.geo_id=:geo_id
  AND c.stage=:stage AND c.is_special=:is_special AND c.is_runoff=:is_runoff
  AND c.boundary_vintage IS NOT DISTINCT FROM :boundary_vintage
  AND c.congress_session IS NOT DISTINCT FROM :congress_session
  AND c.result_mode='TOTAL' AND c.source_release=:source_release;
```

For a validated complete candidate set, absence of the selected party is observed zero votes and zero share. The producer writes an explicit party result for `DEMOCRAT` and `REPUBLICAN`, including zero rows, only after validating the complete pinned contest row set. A missing party result in another selector is not implicitly zero. This is distinguishable from a missing contest, a quarantined/incomplete candidate set, and a no-election row. For state/year combinations with no scheduled or special Senate race, return the explicit `election_availability.quality_status = 'no_election'` row. For a scheduled contest with no candidate observations, return `missing`. Neither state is a numeric zero. The consumer keeps the cycle explicit; v2 does not select the latest result silently.
