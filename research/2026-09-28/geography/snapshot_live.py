#!/usr/bin/env python3
"""Take a hash-verified report snapshot of the independent live collection."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_RUNTIME = ROOT / 'full/runtime/deep-20260928'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    fields = json.loads((ROOT / 'full/field-contract.json').read_text())
    baseline = json.loads((HERE / 'coverage-matrix.json').read_text())
    excluded = set(baseline['food_excluded'])
    runs, tables, files, counts = {}, {}, [], Counter()
    for provider in ['acs-summary', 'cdc-places']:
        path = runtime / ('run-' + provider + '.json')
        run = json.loads(path.read_text()) if path.exists() else {}
        runs[provider] = run
        for name, job in run.get('jobs', {}).items():
            if job.get('status') != 'complete':
                continue
            for kind in ['raw', 'normalized']:
                item = job[kind]
                if digest(runtime / item['path']) != item['sha256']:
                    raise ValueError('artifact_hash_mismatch:' + item['path'])
                files.append({'provider': provider, 'job': name, 'kind': kind, **item})
            counts.update(job['normalized']['rows_by_geography'])
            tables[name] = job
    extension_root = runtime / 'extensions'
    extension_path = extension_root / 'run-acs-summary.json'
    extension_run = json.loads(extension_path.read_text()) if extension_path.exists() else {}
    extension_metrics_path = extension_root / 'extension-metrics.json'
    extension_metrics = json.loads(extension_metrics_path.read_text()) if extension_metrics_path.exists() else []
    extension_counts, extension_tables = Counter(), {}
    for name, job in extension_run.get('jobs', {}).items():
        if job.get('status') != 'complete':
            continue
        for kind in ['raw', 'normalized']:
            item = job[kind]
            if digest(extension_root / item['path']) != item['sha256']:
                raise ValueError('extension_artifact_hash_mismatch:' + item['path'])
            files.append({'provider': 'acs-summary-extension', 'job': name, 'kind': kind,
                          **item, 'path': 'extensions/' + item['path']})
        extension_tables[name] = job
        extension_counts.update(job['normalized']['rows_by_geography'])
    output = []
    for field in fields:
        fid, provider = field['field_id'], field['rate_limit_profile']
        row = {'field_id': fid, 'label': field['catalog_label'], 'excluded_food': fid in excluded,
               'source_tables': [], 'completed_source_tables': [], 'coverage_by_table': {},
               'available_native_levels': [], 'status': 'not_part_of_this_acs_cdc_run'}
        if fid in excluded:
            row['status'] = 'excluded_food'
        elif provider == 'census_acs':
            required = sorted({'acs-summary-' + v.split('_')[0] for v in field['source_variables']})
            completed = [name for name in required if name in tables]
            row.update(source_tables=required, completed_source_tables=completed)
            row['coverage_by_table'] = {name: tables[name]['normalized']['geography_counts'] for name in completed}
            if completed:
                levels = set.intersection(*(set(row['coverage_by_table'][name]) for name in completed))
                row['available_native_levels'] = sorted(levels)
            row['status'] = 'all_required_source_tables_collected' if len(completed) == len(required) else 'partial_source_tables' if completed else 'pending'
            row['interpretation'] = 'Native estimates and MOEs; derived ratios/shares require the contract formula and uncertainty propagation before UI admission.'
            row['exact_geoid_intersection_between_tables_computed'] = False
        elif provider == 'cdc_places':
            name = 'cdc-places-2025-tract'
            row['source_tables'] = [name]
            row['status'] = 'collected_separate_crude_variant' if name in tables else 'pending'
            if name in tables:
                row.update(completed_source_tables=[name], coverage_by_table={name: tables[name]['normalized']['geography_counts']},
                           available_native_levels=['tract'], variant='crude_prevalence', data_year='2023', geography_vintage='2023')
        row['extension_variants'] = []
        for metric in extension_metrics:
            name = 'acs-summary-' + metric['table']
            if metric['catalog_field_id'] == fid and name in extension_tables:
                row['extension_variants'].append({**metric, 'status': 'collected_native_alternative',
                    'geography_counts': extension_tables[name]['normalized']['geography_counts'],
                    'available_native_levels': sorted(level for level, count in
                        extension_tables[name]['normalized']['geography_counts'].items() if count > 0),
                    'normalized_observations': sum(extension_tables[name]['normalized']['rows_by_geography'].values())})
        output.append(row)
    result = {'captured_at': datetime.now(timezone.utc).isoformat(), 'runtime': str(runtime.relative_to(ROOT)),
              'scope': 'Live network collection; separate from historical offline cache recovery.',
              'production_admitted': False, 'source_artifact_hashes_verified': True,
              'normalized_observations_by_geography': dict(counts), 'normalized_observations_total': sum(counts.values()),
              'extension_observations_by_geography': dict(extension_counts), 'extension_observations_total': sum(extension_counts.values()),
              'all_normalized_observations_total': sum(counts.values()) + sum(extension_counts.values()),
              'extension_state': {'status': extension_run.get('status'), 'completed_jobs': extension_run.get('completed_jobs', 0),
                                  'planned_jobs': extension_run.get('planned_jobs'), 'active_job': extension_run.get('active_job'),
                                  'bindings': extension_run.get('bindings')},
              'provider_states': {p: {'status': r.get('status'), 'completed_jobs': r.get('completed_jobs', 0),
                                     'planned_jobs': r.get('planned_jobs'), 'active_job': r.get('active_job'),
                                     'bindings': r.get('bindings')} for p, r in runs.items()},
              'files': files, 'fields': output}
    (HERE / 'live-coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    columns = ['field_id', 'label', 'excluded_food', 'status', 'source_tables', 'completed_source_tables', 'available_native_levels', 'extension_variants']
    with (HERE / 'live-coverage.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in output:
            csv_row = {key: row[key] for key in columns}
            for key, value in csv_row.items():
                if isinstance(value, list):
                    csv_row[key] = (json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                                    if key == 'extension_variants' else '|'.join(value))
            writer.writerow(csv_row)
    print(json.dumps({'providers': result['provider_states'], 'normalized_observations_total': sum(counts.values()),
                      'extension_observations_total': sum(extension_counts.values()),
                      'all_normalized_observations_total': result['all_normalized_observations_total'],
                      'field_status_counts': dict(Counter(row['status'] for row in output))}, indent=2))


if __name__ == '__main__':
    main()
