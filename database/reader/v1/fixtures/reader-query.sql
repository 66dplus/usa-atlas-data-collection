SELECT o.geo_id, o.geo_type, o.period, o.field_id, o.value, o.unit,
       o.source, o.source_release, o.source_url, o.methodology_note,
       o.retrieved_at, o.ingest_id
FROM usa_atlas.observation AS o
JOIN usa_atlas.ingest_run AS i USING (ingest_id)
WHERE o.catalog_field_id = '01.01'
  AND o.field_id = '01.01'
  AND o.geo_type IN ('state', 'county', 'nation')
  AND i.status = 'pass'
ORDER BY o.geo_type, o.geo_id;
