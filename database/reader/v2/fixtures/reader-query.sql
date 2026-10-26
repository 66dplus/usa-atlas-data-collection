-- Observation selector. Bind the full period identity, including endpoints:
-- $1=field_id, $2=period_kind, $3=period_year, $4=period_month,
-- $5=period_start_year, $6=period_end_year, $7=source_release.
SELECT o.geo_id,o.geo_type,o.value,o.unit,o.quality_status,o.source_value_status,
       o.period_kind,o.period_year,o.period_month,o.period_start_year,o.period_end_year,
       o.source_period_code,o.raw_estimate,o.raw_estimate_moe,o.raw_denominator,
       o.raw_denominator_moe,o.denominator_value,o.source,o.source_release,o.source_url,
       o.methodology_note,o.retrieved_at
FROM usa_atlas.reader_observation AS o
JOIN usa_atlas.ingest_run AS i USING (ingest_id)
JOIN usa_atlas.reader_batch AS b USING (ingest_id)
WHERE o.field_id = $1
  AND o.period_kind = $2
  AND o.period_year = $3
  AND o.period_month IS NOT DISTINCT FROM $4
  AND o.period_start_year = $5
  AND o.period_end_year = $6
  AND o.source_release = $7
  AND i.status = 'pass'
  AND b.candidate_status = 'admitted'
ORDER BY o.geo_type,o.geo_id;

-- Election selector: $1=office,$2=year,$3=geography_type,$4=stage,
-- $5=is_special,$6=is_runoff,$7=geo_id,$8=boundary_vintage,
-- $9=congress_session,$10=selected normalized party,$11=source_release.
SELECT c.contest_id,c.field_id,c.dataset_id,c.geo_id,c.geography_type,
       c.boundary_vintage,c.congress_session,c.election_year,c.stage,c.is_special,
       c.is_runoff,c.reported_total_votes,c.quality_status,c.party_aggregation_status,
       CASE WHEN c.quality_status='observed' AND c.party_aggregation_status='validated'
            THEN coalesce(p.party_votes,0) ELSE NULL END AS party_votes,
       CASE WHEN c.quality_status='observed' AND c.party_aggregation_status='validated'
                  AND c.reported_total_votes > 0
            THEN coalesce(p.party_votes,0)::numeric / c.reported_total_votes
            ELSE NULL END AS selected_party_share_of_all_votes,
       c.source_release,c.source_url,c.source_sha256,c.source_status
FROM usa_atlas.election_contest c
JOIN usa_atlas.ingest_run i USING (ingest_id)
JOIN usa_atlas.reader_batch b USING (ingest_id)
LEFT JOIN usa_atlas.election_party_result p
  ON p.contest_id=c.contest_id AND p.party_normalized=$10
 AND p.candidate_status='admitted'
WHERE c.office=$1 AND c.election_year=$2 AND c.geography_type=$3
  AND c.stage=$4 AND c.is_special=$5 AND c.is_runoff=$6 AND c.geo_id=$7
  AND c.boundary_vintage IS NOT DISTINCT FROM $8
  AND c.congress_session IS NOT DISTINCT FROM $9
  AND c.result_mode='TOTAL' AND c.source_release=$11
  AND c.candidate_status='admitted'
  AND b.candidate_status='admitted' AND i.status='pass';

-- If no contest row exists, consult election_availability with the same full
-- identity. no_election and missing are represented as null values.
