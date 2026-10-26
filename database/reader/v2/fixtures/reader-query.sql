-- Period selector example: $1=field_id, $2=period_kind, $3=period_year,
-- $4=period_month (NULL for annual/multi-year), $5=source_release.
SELECT o.geo_id,o.geo_type,o.value,o.unit,o.quality_status,o.source_value_status,
       o.period_kind,o.period_year,o.period_month,o.period_start_year,o.period_end_year,
       o.source_period_code,o.raw_estimate,o.raw_estimate_moe,o.raw_denominator,
       o.raw_denominator_moe,o.denominator_value,o.source,o.source_release,o.source_url,
       o.methodology_note,o.retrieved_at
FROM usa_atlas.reader_observation AS o
JOIN usa_atlas.ingest_run AS i USING (ingest_id)
WHERE o.field_id = $1
  AND o.period_kind = $2
  AND o.period_year = $3
  AND o.period_month IS NOT DISTINCT FROM $4
  AND o.source_release = $5
  AND i.status = 'pass'
ORDER BY o.geo_type,o.geo_id;

-- Election selector example: $1=office, $2=year, $3=geography_type,
-- $4=stage, $5=is_special, $6=is_runoff, $7=geo_id, $8=boundary_vintage,
-- $9=congress_session, $10=selected normalized party, $11=source_release.
WITH selected_contest AS (
    SELECT c.*
    FROM usa_atlas.election_contest AS c
    JOIN usa_atlas.ingest_run AS i USING (ingest_id)
    WHERE c.office = $1
      AND c.election_year = $2
      AND c.geography_type = $3
      AND c.stage = $4
      AND c.is_special = $5
      AND c.is_runoff = $6
      AND c.geo_id = $7
      AND c.boundary_vintage IS NOT DISTINCT FROM $8
      AND c.congress_session IS NOT DISTINCT FROM $9
      AND c.result_mode = 'TOTAL'
      AND c.source_release = $11
      AND i.status = 'pass'
), selected_party_votes AS (
    SELECT e.contest_id,coalesce(sum(e.candidate_votes),0) AS party_votes
    FROM usa_atlas.election_candidate AS e
    JOIN selected_contest AS c USING (contest_id)
    JOIN usa_atlas.ingest_run AS i USING (ingest_id)
    WHERE e.result_mode = 'TOTAL'
      AND e.candidate_kind = 'candidate'
      AND e.quality_status = 'observed'
      AND e.party_normalized = $10
      AND c.party_aggregation_status = 'validated'
      AND i.status = 'pass'
    GROUP BY e.contest_id
)
SELECT c.geo_id,c.geography_type,c.boundary_vintage,c.congress_session,
       c.election_year,c.stage,c.is_special,c.is_runoff,c.reported_total_votes,
       c.quality_status,c.party_aggregation_status,CASE WHEN c.quality_status = 'observed' AND c.party_aggregation_status = 'validated' THEN coalesce(p.party_votes,0) ELSE NULL END AS party_votes,
       CASE WHEN c.quality_status = 'observed'
                  AND c.party_aggregation_status = 'validated'
                  AND c.reported_total_votes > 0
            THEN coalesce(p.party_votes,0)::numeric / c.reported_total_votes
            ELSE NULL END AS selected_party_share_of_all_votes,
       c.source_release,c.source_url,c.methodology_note
FROM selected_contest AS c
LEFT JOIN selected_party_votes AS p USING (contest_id);
