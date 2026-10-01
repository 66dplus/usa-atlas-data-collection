-- Read-only storage inventory for the existing v1 schema. No extensions needed.
-- psql -X -w -qAt --dbname usa_atlas --set ON_ERROR_STOP=1 -f database/audit_storage.sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '2s';
SELECT EXISTS (
  SELECT 1 FROM pg_class WHERE oid=to_regclass('usa_atlas.observation') AND relkind='v'
) AS compact_storage
\gset
WITH relations AS (
  SELECT c.oid, c.relname, c.reltuples::bigint AS planner_estimated_rows,
    pg_relation_size(c.oid) AS heap_main_bytes,
    pg_table_size(c.oid) AS table_including_toast_bytes,
    pg_indexes_size(c.oid) AS indexes_bytes,
    pg_total_relation_size(c.oid) AS total_bytes,
    s.n_live_tup AS estimated_live_rows, s.n_dead_tup AS estimated_dead_rows,
    s.last_analyze, s.last_autoanalyze, s.last_vacuum, s.last_autovacuum
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
  WHERE n.nspname='usa_atlas' AND c.relkind IN ('r','m')
), indexes AS (
  SELECT s.relname AS table_name,s.indexrelname AS index_name,
    pg_relation_size(s.indexrelid) AS bytes,s.idx_scan,s.idx_tup_read,s.idx_tup_fetch,
    i.indisprimary,i.indisunique,pg_get_indexdef(s.indexrelid) AS definition
  FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid=s.indexrelid
  WHERE s.schemaname='usa_atlas'
), sample AS MATERIALIZED (
\if :compact_storage
  SELECT o.geo_id,o.geo_type,o.period,o.field_id,o.catalog_field_id,o.value,o.unit,
    o.source,o.source_release,r.source_url,m.methodology_note,o.retrieved_at,o.ingest_id
  FROM usa_atlas.observation_data o TABLESAMPLE SYSTEM (1) REPEATABLE (20260928)
  JOIN usa_atlas.source_resource r USING(resource_id)
  JOIN usa_atlas.methodology m USING(methodology_id)
\else
  SELECT * FROM usa_atlas.observation TABLESAMPLE SYSTEM (1) REPEATABLE (20260928)
\endif
  LIMIT 100000
), column_sample AS (
  SELECT v.column_name,count(*) AS sampled_rows,
    sum(octet_length(v.value)) AS utf8_value_bytes,
    count(DISTINCT v.value) AS distinct_values_within_sample
  FROM sample s CROSS JOIN LATERAL (VALUES
    ('geo_id',s.geo_id),('geo_type',s.geo_type),('period',s.period),
    ('field_id',s.field_id),('catalog_field_id',s.catalog_field_id),
    ('unit',s.unit),('source',s.source),('source_release',s.source_release),
    ('source_url',s.source_url),('methodology_note',s.methodology_note),
    ('retrieved_at',s.retrieved_at::text),('ingest_id',s.ingest_id::text)
  ) v(column_name,value) GROUP BY v.column_name
)
SELECT json_build_object(
  'status','measured_read_only',
  'database',current_database(),
  'measured_at',clock_timestamp(),
  'server_version',current_setting('server_version'),
  'transaction_read_only',current_setting('transaction_read_only'),
  'database_bytes',pg_database_size(current_database()),
  'database_stats_reset',(SELECT stats_reset FROM pg_stat_database WHERE datname=current_database()),
  'atlas_relation_total_bytes',(SELECT coalesce(sum(total_bytes),0) FROM relations),
  'relations',(SELECT coalesce(json_agg(r ORDER BY total_bytes DESC),'[]'::json) FROM relations r),
  'indexes',(SELECT coalesce(json_agg(i ORDER BY bytes DESC),'[]'::json) FROM indexes i),
  'sample_design','SYSTEM 1 percent, seed 20260928, cap 100000; not an exact count or savings estimate',
  'sample_rows',(SELECT count(*) FROM sample),
  'sample_mean_record_bytes',(SELECT avg(pg_column_size(s)) FROM sample s),
  'column_sample',(SELECT coalesce(json_agg(c ORDER BY utf8_value_bytes DESC),'[]'::json) FROM column_sample c),
  'sample_by_source',(SELECT coalesce(json_agg(g ORDER BY source),'[]'::json)
    FROM (SELECT source,count(*) AS sampled_rows,avg(pg_column_size(s)) AS mean_record_bytes
      FROM sample s GROUP BY source) g),
  'ingests',(SELECT coalesce(json_agg(g ORDER BY source,status),'[]'::json)
    FROM (SELECT source,status,count(*) AS runs,sum(row_count) AS declared_rows,
      min(started_at) AS first_start,max(completed_at) AS last_completion
      FROM usa_atlas.ingest_run GROUP BY source,status) g)
);
ROLLBACK;
