#!/usr/bin/env python3
"""Bounded, read-only production evidence for the frozen collected35 runtime.

This writes a local JSON report only. No SQL writes, source admissions, UI edits,
or generic-record scans are performed. Geography presence probes do not claim
complete tract/block-group coverage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def audit(runtime: Path):
    paths = [runtime / item for item in (
        'scripts/atlas_data.py', 'ux/indicator-visibility.js', 'ux/catalog.json',
        'ux/catalog-v2.json', 'ux/acs-series.json')]
    bindings = [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in paths]
    enabled = re.findall(r"'([0-9]{2}\.[0-9]{2})': true", paths[1].read_text())
    if len(enabled) != 35 or len(set(enabled)) != 35:
        raise ValueError('Expected the frozen collected35 runtime')
    sql = ["BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;",
           "SET LOCAL statement_timeout='15s';", "SET LOCAL lock_timeout='2s';",
           "SET LOCAL idle_in_transaction_session_timeout='30s';", "SET LOCAL jit=off;",
           "SELECT json_build_object('snapshot_at',clock_timestamp(),'transaction_read_only',current_setting('transaction_read_only'));" ]
    defaults = {'03.06': '03.06:unemployment_rate', '08.05': '08.05:sector_ALL'}
    for catalog in enabled:
        default = defaults.get(catalog, catalog)
        selection_geo = 'county' if catalog in ('07.01', '09.04') else 'state'
        query = f"""
WITH choices AS (
  SELECT DISTINCT o.field_id FROM usa_atlas.observation_data o
  JOIN usa_atlas.ingest_run i USING(ingest_id)
  WHERE catalog_field_id={quote(catalog)} AND geo_type={quote(selection_geo)} AND i.status='pass'
), selected AS (
  SELECT field_id FROM choices ORDER BY
    CASE WHEN field_id={quote(default)} THEN 0
         WHEN field_id ~ '^[0-9]{{2}}\\.[0-9]{{2}}:B[0-9]{{5}}_[0-9]{{3}}E$' THEN 1
         ELSE 2 END, field_id LIMIT 1
), chosen AS (
  SELECT o.period,o.source_release,o.source FROM usa_atlas.observation_data o
  WHERE catalog_field_id={quote(catalog)} AND geo_type={quote(selection_geo)}
  AND field_id=(SELECT field_id FROM selected)
  AND EXISTS (SELECT 1 FROM usa_atlas.ingest_run i WHERE i.ingest_id=o.ingest_id AND i.status='pass')
  ORDER BY period DESC,source_release DESC LIMIT 1
), counts AS (
  SELECT o.geo_type,o.unit,o.source,count(*) rows,count(DISTINCT geo_id) geographies
  FROM usa_atlas.observation_data o
  WHERE catalog_field_id={quote(catalog)} AND geo_type IN ('nation','state','county')
  AND field_id=(SELECT field_id FROM selected) AND period=(SELECT period FROM chosen)
  AND source_release=(SELECT source_release FROM chosen) AND source=(SELECT source FROM chosen)
  AND EXISTS (SELECT 1 FROM usa_atlas.ingest_run i WHERE i.ingest_id=o.ingest_id AND i.status='pass')
  GROUP BY 1,2,3
), presence AS (
  SELECT g.geo_type,
    CASE WHEN probe.matched THEN true WHEN probe.scanned < 1000 THEN false ELSE null END present,
    probe.scanned sampled_parent_range_rows,1000 sample_limit
  FROM (VALUES ('nation'),('state'),('county'),('place'),('tract'),('block_group'),('zip'),('metro')) g(geo_type)
  CROSS JOIN LATERAL (
    WITH sample AS MATERIALIZED (
      SELECT field_id,period,source_release,source,ingest_id
      FROM usa_atlas.observation_data o
      WHERE catalog_field_id={quote(catalog)} AND o.geo_type=g.geo_type
      ORDER BY o.geo_id,o.period DESC LIMIT 1000
    ) SELECT count(*) scanned,coalesce(bool_or(
      s.field_id=(SELECT field_id FROM selected) AND s.period=(SELECT period FROM chosen)
      AND s.source_release=(SELECT source_release FROM chosen) AND s.source=(SELECT source FROM chosen)
      AND i.status='pass'),false) matched FROM sample s JOIN usa_atlas.ingest_run i USING(ingest_id)
  ) probe
), examples AS (
 SELECT o.* FROM usa_atlas.observation o
 WHERE catalog_field_id={quote(catalog)}
 AND field_id=(SELECT field_id FROM selected) AND period=(SELECT period FROM chosen)
 AND source_release=(SELECT source_release FROM chosen) AND source=(SELECT source FROM chosen)
 AND EXISTS (SELECT 1 FROM usa_atlas.ingest_run i WHERE i.ingest_id=o.ingest_id AND i.status='pass')
 AND (geo_type='nation' OR (geo_type='state' AND geo_id IN ('41','OR','41000','US','00000'))
      OR (geo_type='county' AND geo_id='41051'))
 ORDER BY geo_type,geo_id LIMIT 6
)
SELECT json_build_object('catalog_field_id',{quote(catalog)},
 'selected_field_id',(SELECT field_id FROM selected),'snapshot',(SELECT row_to_json(chosen) FROM chosen),
 'level_counts',coalesce((SELECT json_agg(counts) FROM counts),'[]'::json),
 'level_presence',(SELECT json_agg(presence) FROM presence),
 'examples',coalesce((SELECT json_agg(examples) FROM examples),'[]'::json));
"""
        # Independent CTE outputs avoid a poor nested-loop plan when several
        # scalar aggregates reference chosen at once. Stay in the same snapshot.
        prefix = query[:query.index("SELECT json_build_object('catalog_field_id'")]
        sql.append(prefix + f"SELECT json_build_object('catalog_field_id',{quote(catalog)},'selected_field_id',(SELECT field_id FROM selected),'snapshot',(SELECT row_to_json(chosen) FROM chosen));")
        for part in ('counts', 'presence', 'examples'):
            sql.append(prefix + f"SELECT coalesce(json_agg(t),'[]'::json)::jsonb FROM {part} t;")
    sql.append("""
SELECT coalesce(json_agg(t),'[]'::json)::jsonb FROM (
 SELECT o.* FROM usa_atlas.observation o JOIN usa_atlas.ingest_run i USING(ingest_id)
 WHERE catalog_field_id='03.06' AND geo_type='state' AND period='2024-M12'
 AND source_release='BLS-LAUS-2024' AND field_id IN ('03.06:unemployment','03.06:labor_force','03.06:unemployment_rate')
 AND i.status='pass' ORDER BY field_id,geo_id LIMIT 157
) t;
SELECT coalesce(json_agg(t),'[]'::json)::jsonb FROM (
 SELECT o.* FROM usa_atlas.observation o JOIN usa_atlas.ingest_run i USING(ingest_id)
 WHERE catalog_field_id='07.01' AND geo_type='county' AND geo_id >= '41000' AND geo_id < '42000'
 AND field_id='07.01:A00100:county_sum_agi_stubs_1_8' AND period='2023'
 AND source_release='IRS-SOI-COUNTY-2023' AND i.status='pass' ORDER BY geo_id LIMIT 37
) t;
ROLLBACK;
""")
    command = ['docker', 'exec', '-i', '-u', 'postgres', '-e', 'PGAPPNAME=usa_atlas_map_audit',
               'usa-atlas-postgres', 'sh', '-c',
               'exec psql -X -w -qAt --username "$POSTGRES_USER" --dbname usa_atlas --set ON_ERROR_STOP=1']
    result = subprocess.run(command, input='\n'.join(sql), text=True, capture_output=True, timeout=180)
    if result.returncode:
        completed = len(result.stdout.splitlines()) - 1
        raise RuntimeError(f'Read-only production audit failed after {completed} field results: ' + result.stderr[-1200:])
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != len(enabled) * 4 + 3:
        raise RuntimeError('Unexpected audit result count')
    fields = []
    for index in range(len(enabled)):
        start = 1 + index * 4
        fields.append({**rows[start], 'level_counts': rows[start+1],
                       'level_presence': rows[start+2], 'examples': rows[start+3]})
    return {'format': 'usa_atlas_map_data_audit_v1', 'captured_at': datetime.now(timezone.utc).isoformat(),
            'connection': {'container': 'usa-atlas-postgres', 'database': 'usa_atlas', 'read_only': True,
                           'isolation': 'repeatable read', 'statement_timeout_seconds': 15,
                           'lock_timeout_seconds': 2},
            'runtime_bindings': bindings, 'snapshot': rows[0], 'selected_series': fields,
            'unemployment_supporting_observations': rows[-2], 'oregon_agi_counties': rows[-1],
            'count_scope': 'Exact nation/state/county counts for selected period and release. Other levels probe at most 1,000 indexed rows: true confirms presence; false confirms empty/unmatched complete range; null means the bounded probe cannot determine presence.',
            'selection_note': 'Frozen runtime default selector, discovered in state ranges (county ranges for native county-only AGI and fitness). Snapshot is lexical latest in that native selection level, then nation/state/county counts are bound to it. This is not a release selection recommendation or proof that another geography has no newer release.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    packet = audit(args.runtime.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(packet, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': 'complete', 'fields': len(packet['selected_series']), 'report': str(args.out)}))


if __name__ == '__main__':
    main()
