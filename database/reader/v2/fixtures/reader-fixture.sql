INSERT INTO usa_atlas.reader_v2_catalog_field
    (catalog_field_id,source_release,dataset_id,catalog_label,source_code,contract_version,contract,contract_sha256,candidate_status)
VALUES
('03.06','bls-2025-fixture','unemployment','Fixture: unemployment','bls_laus','2.0.0','{"periodKinds":["monthly","annual"],"unit":"percent"}'::jsonb,repeat('b',64),'local_review'),
('01.04','2024-acs-acs5','aian_broad_share','AIAN broad share extension','acs_acs5','2.0.0','{"numerator":"B02010_001E","denominator":"B01003_001E"}'::jsonb,repeat('c',64),'local_review'),
('12.01','medsl-fixture-v1','president_election','President election results','medsl','2.0.0','{"office":"president"}'::jsonb,repeat('d',64),'local_review'),
('12.02','medsl-fixture-v1','senate_election','Senate election results','medsl','2.0.0','{"office":"senate"}'::jsonb,repeat('e',64),'local_review'),
('12.03','medsl-fixture-v1','house_election','House election results','medsl','2.0.0','{"office":"house"}'::jsonb,repeat('f',64),'local_review'),
('12.03','unadmitted-fixture','house_election','House election results','medsl','2.0.0','{"office":"house"}'::jsonb,repeat('0',64),'local_review');

INSERT INTO usa_atlas.ingest_run
    (ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,completed_at,status,error_code)
VALUES
('00000000-0000-4000-8000-000000000101','fixture','reader-v2-fixture.sql',repeat('a',64),repeat('b',64),8,
 '2026-10-26T00:00:00Z','2026-10-26T00:01:00Z','pass',NULL),
('00000000-0000-4000-8000-000000000102','fixture','unadmitted-v2-fixture.sql',repeat('e',64),repeat('f',64),1,
 '2026-10-26T00:02:00Z',NULL,'loading',NULL);

-- One annual M13 record and two monthly records. M13 is source provenance only;
-- it is never encoded as a month number.
INSERT INTO usa_atlas.reader_observation
    (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,
     period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,
     value,unit,quality_status,source_value_status,geography_mapping_status,source,
     source_release,source_url,source_sha256,methodology_note,candidate_status,retrieved_at,ingest_id)
VALUES
('unemp-ca-annual-2025','unemployment','03.06:unemployment_rate','03.06','06','state','06',
 'annual',2025,NULL,2025,2025,'M13',4.7,'percent','observed','observed','mapped',
 'BLS LAUS','bls-2025-fixture','https://example.test/bls',repeat('1',64),
 'Synthetic fixture annual average; source code M13 retained as provenance.','local_review','2026-10-26T00:00:00Z',
 '00000000-0000-4000-8000-000000000101'),
('unemp-ca-month-2025-01','unemployment','03.06:unemployment_rate','03.06','06','state','06',
 'monthly',2025,1,2025,2025,'M01',4.5,'percent','observed','observed','mapped',
 'BLS LAUS','bls-2025-fixture','https://example.test/bls',repeat('1',64),
 'Synthetic fixture January observation.','local_review','2026-10-26T00:00:00Z','00000000-0000-4000-8000-000000000101'),
('unemp-ca-month-2025-02','unemployment','03.06:unemployment_rate','03.06','06','state','06',
 'monthly',2025,2,2025,2025,'M02',0,'percent','observed','observed','mapped',
 'BLS LAUS','bls-2025-fixture','https://example.test/bls',repeat('1',64),
 'Synthetic fixture zero is a real observed value.','local_review','2026-10-26T00:00:00Z','00000000-0000-4000-8000-000000000101'),
('aian-ca-county','aian_broad_share','01.04:aian_share','01.04','06001','county','06',
 'multi_year',2024,NULL,2020,2024,NULL,3.25,'percent','observed','observed','mapped',
 'U.S. Census Bureau ACS','2024-acs-acs5','https://api.census.gov/data/2024/acs/acs5',repeat('2',64),
 'Synthetic fixture ratio from B02010_001E / B01003_001E; no derived MOE.','local_review','2026-10-26T00:00:00Z',
 '00000000-0000-4000-8000-000000000101');

INSERT INTO usa_atlas.reader_observation
    (observation_id,dataset_id,field_id,catalog_field_id,geo_id,geo_type,state_fips,
     period_kind,period_year,period_month,period_start_year,period_end_year,source_period_code,
     value,unit,quality_status,source_value_status,geography_mapping_status,raw_estimate,
     raw_estimate_moe,raw_denominator,raw_denominator_moe,denominator_value,source,
     source_release,source_url,source_sha256,methodology_note,candidate_status,retrieved_at,ingest_id)
VALUES
('aian-suppressed-fixture','aian_broad_share','01.04:aian_share','01.04','06003','county','06',
 'multi_year',2024,NULL,2020,2024,NULL,NULL,'percent','suppressed','suppressed','mapped',
 '-999999999','-999999999','100','-555555555',100,'U.S. Census Bureau ACS','2024-acs-acs5',
 'https://api.census.gov/data/2024/acs/acs5',repeat('2',64),'Synthetic suppression-state fixture.','local_review',
 '2026-10-26T00:00:00Z','00000000-0000-4000-8000-000000000101'),
('aian-nonmapping-fixture','aian_broad_share','01.04:aian_share','01.04','09110','county','09',
 'multi_year',2024,NULL,2020,2024,NULL,2.50,'percent','nonmapping_geography','observed',
 'nonmapping_geography','100','10','4000','-555555555',4000,'U.S. Census Bureau ACS','2024-acs-acs5',
 'https://api.census.gov/data/2024/acs/acs5',repeat('2',64),
 'Synthetic source value retained; no exact 2017 geometry join and no reallocation.','local_review',
 '2026-10-26T00:00:00Z','00000000-0000-4000-8000-000000000101');

INSERT INTO usa_atlas.election_contest
    (contest_id,dataset_id,field_id,catalog_field_id,office,election_year,election_date,stage,is_special,is_runoff,geography_type,geo_id,
     state_fips,district_code,boundary_vintage,congress_session,result_mode,reported_total_votes,
     source_release,source_url,source_sha256,source_version,quality_status,geography_mapping_status,
     party_aggregation_status,quarantine_reasons,methodology_note,source_status,production_eligible,candidate_status,ingest_id)
VALUES
('fixture-house-2024-ca-cd06-general','house_election','12.03','12.03','house',2024,'2024-11-05','general',false,false,
 'congressional_district','0606','06','06',2024,'119','TOTAL',100,
 'medsl-fixture-v1','https://example.test/medsl',repeat('3',64),'fixture-v1',
 'observed','mapped','validated',ARRAY[]::text[],
 'Synthetic fixture contest; source total is stored once at contest grain.',
 'fixture_public',false,'local_review',
 '00000000-0000-4000-8000-000000000101'),
('fixture-senate-2024-ks-no-election','senate_election','12.02','12.02','senate',2024,NULL,'general',false,false,
 'state','20','20',NULL,NULL,NULL,'TOTAL',NULL,
 'medsl-fixture-v1','https://example.test/medsl',repeat('3',64),'fixture-v1',
 'no_election','mapped','not_evaluated',ARRAY[]::text[],
 'Synthetic fixture: 2024 Senate schedule says no regular or special contest in this state.',
 'fixture_public',false,'local_review',
 '00000000-0000-4000-8000-000000000101'),
('fixture-house-2024-ca-unadmitted','house_election','12.03','12.03','house',2024,'2024-11-05','general',false,false,
 'congressional_district','0606','06','06',2024,'119','TOTAL',999,
 'unadmitted-fixture','https://example.test/medsl',repeat('4',64),'fixture-v1',
 'observed','mapped','validated',ARRAY[]::text[],
 'Synthetic unadmitted run must not be returned by consumer queries.',
 'fixture_public',false,'local_review',
 '00000000-0000-4000-8000-000000000102');

INSERT INTO usa_atlas.election_candidate
    (contest_id,source_row_id,candidate_id,candidate_label,candidate_kind,party_original,party_normalized,
     candidatevotes_raw,totalvotes_raw,candidate_votes,source_total_votes,result_mode,write_in,
     fusion_ticket,source_version,source_url,source_sha256,source_status,quality_status,candidate_status,ingest_id)
VALUES
('fixture-house-2024-ca-cd06-general','row-001','candidate-a','Candidate A','candidate','DEMOCRAT','DEMOCRAT',
 '60','100',60,100,'TOTAL',false,false,'fixture-v1','https://example.test/medsl',repeat('3',64),'fixture_public','observed','local_review','00000000-0000-4000-8000-000000000101'),
('fixture-house-2024-ca-cd06-general','row-002','candidate-b','Candidate B','candidate','REPUBLICAN','REPUBLICAN',
 '40','100',40,100,'TOTAL',false,false,'fixture-v1','https://example.test/medsl',repeat('3',64),'fixture_public','observed','local_review','00000000-0000-4000-8000-000000000101'),
-- Mode subtotals are preserved but the consumer query selects TOTAL only.
('fixture-house-2024-ca-cd06-general','row-003','candidate-a','Candidate A','candidate','DEMOCRAT','DEMOCRAT',
 '30','50',30,50,'ABSENTEE',false,false,'fixture-v1','https://example.test/medsl',repeat('3',64),'fixture_public','observed','local_review','00000000-0000-4000-8000-000000000101'),
('fixture-house-2024-ca-cd06-general','row-004','candidate-b','Candidate B','candidate','REPUBLICAN','REPUBLICAN',
 '20','50',20,50,'ABSENTEE',false,false,'fixture-v1','https://example.test/medsl',repeat('3',64),'fixture_public','observed','local_review','00000000-0000-4000-8000-000000000101');

INSERT INTO usa_atlas.election_availability
    (field_id,dataset_id,office,election_year,geography_type,geo_id,boundary_vintage,congress_session,stage,is_special,
     is_runoff,quality_status,source_release,reason,candidate_status,ingest_id)
VALUES
('12.02','senate_election','senate',2024,'state','20',NULL,NULL,'general',false,false,'no_election','medsl-fixture-v1',
 'No regular Class I election and no special contest in the 2024 source schedule.',
 'local_review',
 '00000000-0000-4000-8000-000000000101'),
('12.02','senate_election','senate',2024,'state','12',NULL,NULL,'general',false,false,'missing','medsl-fixture-v1',
 'Synthetic expected state contest with no candidate rows; preserve as missing, not zero.',
 'local_review',
 '00000000-0000-4000-8000-000000000101');
