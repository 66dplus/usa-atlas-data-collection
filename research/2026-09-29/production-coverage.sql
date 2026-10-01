-- Read-only inventory of the compact production table. Run only after cutover.
-- Stored geo_type/geo_id are reported verbatim, without asserting that regional
-- source codes are canonical Census geographies. Text periods sort lexically.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30min';
SET LOCAL lock_timeout='3s';
SET LOCAL max_parallel_workers_per_gather=0;
SET LOCAL work_mem='128MB';
SET LOCAL temp_file_limit='16GB';
WITH coverage AS MATERIALIZED (
  SELECT catalog_field_id,source,geo_type,
         count(*) AS observation_rows,
         count(DISTINCT geo_id) AS distinct_geo_ids,
         min(period) AS min_period,max(period) AS max_period
  FROM usa_atlas.observation_data
  GROUP BY catalog_field_id,source,geo_type
), detailed AS (
  SELECT c.catalog_field_id,f.catalog_label,c.source,c.geo_type,
         c.observation_rows,c.distinct_geo_ids,c.min_period,c.max_period
  FROM coverage c JOIN usa_atlas.catalog_field f USING(catalog_field_id)
), sources AS (
  SELECT source,sum(observation_rows)::bigint AS observation_rows,
         count(DISTINCT catalog_field_id) AS populated_catalog_fields,
         array_agg(DISTINCT geo_type ORDER BY geo_type) AS stored_geo_types
  FROM coverage GROUP BY source
)
SELECT json_build_object(
  'status','complete',
  'snapshot_at',transaction_timestamp(),
  'snapshot_id',pg_current_snapshot()::text,
  'database',current_database(),
  'relation','usa_atlas.observation_data',
  'schema_sha256',(SELECT schema_sha256 FROM usa_atlas.schema_metadata),
  'query_limits',json_build_object('statement_timeout','30min',
    'max_parallel_workers_per_gather',0,'work_mem','128MB','temp_file_limit','16GB'),
  'observation_rows',(SELECT sum(observation_rows)::bigint FROM coverage),
  'populated_catalog_fields',(SELECT count(DISTINCT catalog_field_id) FROM coverage),
  'coverage_groups',(SELECT count(*) FROM coverage),
  'coverage',(SELECT json_agg(d ORDER BY catalog_field_id,source,geo_type) FROM detailed d),
  'sources',(SELECT json_agg(s ORDER BY source) FROM sources s),
  'catalog_fields_without_rows',(SELECT coalesce(json_agg(z ORDER BY catalog_field_id),'[]'::json) FROM (
     SELECT f.catalog_field_id,f.catalog_label,f.planned_state
     FROM usa_atlas.catalog_field f
     WHERE NOT EXISTS(SELECT 1 FROM coverage c WHERE c.catalog_field_id=f.catalog_field_id)
  ) z),
  'notes',json_build_array(
    'Counts describe committed production observations in one consistent snapshot; downloaded files awaiting admission are excluded.',
    'Distinct geo_id is per catalog_field_id/source/geo_type group and must not be summed as a national unique-geography total.',
    'geo_type and geo_id reflect stored source codes; state-like regional codes have not been relabeled as Census states.',
    'min_period and max_period are lexical extrema of stored period text, reported separately by source and geography.',
    'Observation rows can include multiple field_id series and margins of error within one catalog field.'
  )
);
ROLLBACK;
