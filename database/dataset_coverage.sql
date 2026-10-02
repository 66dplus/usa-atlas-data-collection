-- Read-only inventory of the latest accepted snapshot of every pipeline dataset.
-- Observation level counts are accepted snapshot rows, not unique geographies.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '2s';
WITH current_batches AS (
  SELECT b.* FROM usa_atlas_pipeline.snapshot_batch b
  JOIN usa_atlas_pipeline.dataset d ON d.dataset_key=b.dataset_key
    AND d.latest_snapshot_id=b.snapshot_id
  WHERE b.status='pass'
), totals AS (
  SELECT dataset_key, count(*) AS batch_count,
         sum(numeric_rows) AS numeric_rows,
         sum(quality_rows) AS quality_rows,
         sum(record_rows) AS record_rows
  FROM current_batches GROUP BY dataset_key
), levels AS (
  SELECT b.dataset_key,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:block_group') AS block_group_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:tract') AS tract_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:county') AS county_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:state') AS state_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:nation') AS nation_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:place') AS place_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:zip') AS zip_rows,
         sum(v.value::bigint) FILTER (WHERE v.key='observations:monitor') AS monitor_rows
  FROM current_batches b
  CROSS JOIN LATERAL jsonb_each_text(coalesce(b.manifest #> '{scope,row_counts}', '{}'::jsonb)) v
  GROUP BY b.dataset_key
)
SELECT d.dataset_key,d.kind,d.source,d.source_release,d.latest_snapshot_at,
       d.completed_at,t.batch_count,t.numeric_rows,t.quality_rows,t.record_rows,
       coalesce(l.block_group_rows,0) AS block_group_rows,
       coalesce(l.tract_rows,0) AS tract_rows,
       coalesce(l.county_rows,0) AS county_rows,
       coalesce(l.state_rows,0) AS state_rows,
       coalesce(l.nation_rows,0) AS nation_rows,
       coalesce(l.place_rows,0) AS place_rows,
       coalesce(l.zip_rows,0) AS zip_rows,
       coalesce(l.monitor_rows,0) AS monitor_rows,
       d.scope->>'coverage' AS source_coverage_note
FROM usa_atlas_pipeline.dataset d
LEFT JOIN totals t USING (dataset_key)
LEFT JOIN levels l USING (dataset_key)
ORDER BY d.dataset_key;
ROLLBACK;
