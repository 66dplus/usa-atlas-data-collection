INSERT INTO usa_atlas.catalog_field
    (catalog_field_id, catalog_label, planned_state, rate_limit_profile,
     source_release, contract, contract_sha256)
VALUES
('01.01','Fixture: median household income','run_now','census_acs','2024-acs-acs5',
 '{"unit":"USD"}'::jsonb,repeat('b',64));
INSERT INTO usa_atlas.ingest_run
    (ingest_id, source, artifact_path, artifact_sha256, contract_sha256,
     row_count, started_at, completed_at, status, error_code)
VALUES
('00000000-0000-4000-8000-000000000001','census_acs','fixture.jsonl',repeat('a',64),repeat('b',64),2,'2026-01-01T00:00:00Z','2026-01-02T00:00:00Z','pass',NULL),
('00000000-0000-4000-8000-000000000002','census_acs','unadmitted.jsonl',repeat('c',64),repeat('d',64),1,'2026-01-03T00:00:00Z',NULL,'loading',NULL);
INSERT INTO usa_atlas.observation
    (geo_id, geo_type, period, field_id, catalog_field_id, value, unit,
     source, source_release, source_url, methodology_note, retrieved_at, ingest_id)
VALUES
('06','state','2024','01.01','01.01',0,'USD','census_acs','2024-acs-acs5','https://example.test/source','Fixture zero is a real value.','2026-01-02T00:00:00Z','00000000-0000-4000-8000-000000000001'),
('06037','county','2024','01.01','01.01',100,'USD','census_acs','2024-acs-acs5','https://example.test/source','Fixture county observation.','2026-01-02T00:00:00Z','00000000-0000-4000-8000-000000000001'),
('06001','county','2024','01.01','01.01',50,'USD','census_acs','unadmitted-release','https://example.test/source','Must be filtered.','2026-01-04T00:00:00Z','00000000-0000-4000-8000-000000000002');
