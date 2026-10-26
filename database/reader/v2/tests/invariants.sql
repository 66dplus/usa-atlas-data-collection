-- Run after schema.sql and fixtures/reader-fixture.sql in an owned disposable DB.
DO $$ BEGIN
  BEGIN
    INSERT INTO usa_atlas.reader_observation (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,district_code,boundary_vintage,congress_session,is_at_large,period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,source_release,source_url,source_sha256,methodology_note,retrieved_at,ingest_id) SELECT 'duplicate-annual',dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,district_code,boundary_vintage,congress_session,is_at_large,period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,source_release,source_url,source_sha256,methodology_note,retrieved_at,ingest_id FROM usa_atlas.reader_observation WHERE observation_id='unemp-ca-annual-2025';
    RAISE EXCEPTION 'duplicate annual grain unexpectedly accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  BEGIN
    INSERT INTO usa_atlas.election_contest SELECT
      'duplicate-senate',office,election_year,election_date,stage,is_special,is_runoff,geography_type,geo_id,state_fips,district_code,boundary_vintage,congress_session,result_mode,reported_total_votes,source_release,source_url,source_sha256,source_version,quality_status,geography_mapping_status,party_aggregation_status,quarantine_reasons,methodology_note,ingest_id
    FROM usa_atlas.election_contest WHERE contest_id='fixture-senate-2024-ks-no-election';
    RAISE EXCEPTION 'duplicate NULL-dimension contest unexpectedly accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  BEGIN
    INSERT INTO usa_atlas.reader_observation (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,period_kind,period_year,period_month,period_start_year,period_end_year,value,unit,quality_status,source_value_status,geography_mapping_status,source,source_release,source_url,source_sha256,methodology_note,retrieved_at,ingest_id)
    VALUES ('bad-m13-month','test','x','03.06','06','state','monthly',2025,13,2025,2025,1,'x','observed','observed','mapped','x','x','https://example.test',repeat('a',64),'x',now(),'00000000-0000-4000-8000-000000000101');
    RAISE EXCEPTION 'month 13 unexpectedly accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    INSERT INTO usa_atlas.election_contest (contest_id,office,election_year,stage,is_special,is_runoff,geography_type,geo_id,result_mode,source_release,source_url,source_sha256,source_version,quality_status,geography_mapping_status,party_aggregation_status,methodology_note,ingest_id)
    VALUES ('bad-house-state','house',2024,'general',false,false,'state','06','TOTAL','x','https://example.test',repeat('a',64),'x','observed','mapped','validated','x','00000000-0000-4000-8000-000000000101');
    RAISE EXCEPTION 'House/state mismatch unexpectedly accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    INSERT INTO usa_atlas.election_availability (office,election_year,geography_type,geo_id,stage,is_special,is_runoff,quality_status,source_release,reason,ingest_id)
    VALUES ('senate',2024,'state','20','general',false,false,'no_election','medsl-fixture-v1','bad value','00000000-0000-4000-8000-000000000101');
    RAISE EXCEPTION 'duplicate availability with NULL dimensions unexpectedly accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  IF (SELECT reported_total_votes FROM usa_atlas.election_contest WHERE contest_id='fixture-house-2024-ca-cd06-general') <> 100 THEN RAISE EXCEPTION 'contest totalvotes must be stored once, not summed across candidate rows'; END IF;
  IF (SELECT sum(candidate_votes) FROM usa_atlas.election_candidate WHERE contest_id='fixture-house-2024-ca-cd06-general' AND result_mode='TOTAL') <> 100 THEN RAISE EXCEPTION 'TOTAL mode candidatevotes mismatch'; END IF;
  IF (SELECT sum(candidate_votes) FROM usa_atlas.election_candidate WHERE contest_id='fixture-house-2024-ca-cd06-general') <> 150 THEN RAISE EXCEPTION 'fixture should demonstrate separate subtotal mode'; END IF;
  IF NOT EXISTS (SELECT 1 FROM usa_atlas.election_contest c WHERE c.contest_id='fixture-house-2024-ca-cd06-general' AND c.quality_status='observed' AND c.party_aggregation_status='validated' AND NOT EXISTS (SELECT 1 FROM usa_atlas.election_candidate e WHERE e.contest_id=c.contest_id AND e.party_normalized='GREEN' AND e.result_mode='TOTAL') AND coalesce((SELECT sum(e.candidate_votes) FROM usa_atlas.election_candidate e WHERE e.contest_id=c.contest_id AND e.party_normalized='GREEN' AND e.result_mode='TOTAL'),0)=0) THEN RAISE EXCEPTION 'validated absent party must be observed zero'; END IF;
  IF NOT EXISTS (SELECT 1 FROM usa_atlas.election_availability WHERE office='senate' AND geo_id='20' AND quality_status='no_election') THEN RAISE EXCEPTION 'no-election must remain explicit'; END IF;
  IF NOT EXISTS (SELECT 1 FROM usa_atlas.election_availability WHERE office='senate' AND geo_id='12' AND quality_status='missing') THEN RAISE EXCEPTION 'missing scheduled contest must remain distinct'; END IF;
  BEGIN
    INSERT INTO usa_atlas.reader_observation (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,period_kind,period_year,period_month,period_start_year,period_end_year,value,unit,quality_status,source_value_status,geography_mapping_status,source,source_release,source_url,source_sha256,methodology_note,retrieved_at,ingest_id)
    VALUES ('observed-null','test','x','03.06','06','state','annual',2025,NULL,2025,2025,NULL,'x','observed','observed','mapped','x','x','https://example.test',repeat('a',64),'x',now(),'00000000-0000-4000-8000-000000000101');
    RAISE EXCEPTION 'observed NULL value unexpectedly accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    UPDATE usa_atlas.reader_observation SET value=0 WHERE observation_id='unemp-ca-annual-2025';
    IF NOT EXISTS (SELECT 1 FROM usa_atlas.reader_observation WHERE observation_id='unemp-ca-annual-2025' AND period_month IS NULL AND source_period_code='M13') THEN RAISE EXCEPTION 'annual M13 was not retained as a NULL month'; END IF;
  END;
END $$;
