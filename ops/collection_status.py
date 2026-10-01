#!/usr/bin/env python3
"""Read local collection and database maintenance checkpoints; no database writes."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEEP = ROOT / 'full/runtime/deep-20260928'
LOCAL = ROOT / 'research/2026-09-28/local-portals/runtime'
MAINTENANCE = Path('/srv/usa-atlas/maintenance/20260928-compact')


def read(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        return {'read_error': type(exc).__name__}


def alive(pid):
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main():
    state = {'observed_at': datetime.now(timezone.utc).isoformat()}
    for provider in ['acs-summary', 'cdc-places']:
        supervisor = read(DEEP / f'supervisor-{provider}.json')
        run = read(DEEP / f'run-{provider}.json')
        state[provider] = {
            'status': supervisor.get('status', 'not_started'),
            'pid': supervisor.get('pid'), 'process_alive': alive(supervisor.get('pid')),
            'completed_jobs': run.get('completed_jobs'), 'planned_jobs': run.get('planned_jobs'),
            'active_job': run.get('active_job'), 'updated_at': supervisor.get('updated_at'),
        }
    extensions = read(DEEP / 'extensions/supervisor.json')
    state['acs-extensions'] = {**extensions, 'process_alive': alive(extensions.get('pid'))}
    public = read(ROOT / 'full/runtime/public-20260928/manifest.json')
    state['public-source-tables'] = {
        'status': public.get('status', 'not_started'),
        'jobs': {k: {'status': v.get('status'), 'rows': v.get('table', {}).get('table_rows_including_preserved_headers_when_nested')}
                 for k, v in public.get('jobs', {}).items()},
        'production_admission': False,
    }
    local = read(LOCAL / 'state.json')
    state['local-portals'] = {
        'pid': local.get('pid'), 'process_alive': alive(local.get('pid')),
        'cycle_completed_at': local.get('cycle_completed_at'),
        'collections': local.get('collections', {}),
        'discovery_query_count': len(local.get('discovery', {})),
        'heartbeat': read(LOCAL / 'heartbeat.json'),
    }
    regional_root = ROOT / 'research/2026-09-29/regional-expansion'
    regional = read(regional_root / 'latest.json')
    relative_summary = regional.get('summary', '')
    regional_summary_path = (regional_root / relative_summary).resolve()
    regional_summary = (read(regional_summary_path)
                        if relative_summary and regional_summary_path.is_relative_to(regional_root) else {})
    regional_jobs = regional_summary.get('jobs', {})
    state['regional-refresh'] = {
        'status': regional.get('status', 'not_started'),
        'snapshot_date': regional.get('date'), 'finished_at': regional.get('finished_at'),
        'jobs': {key: {'status': row.get('status'), 'rows': row.get('rows')}
                 for key, row in regional_jobs.items()},
        'production_admission': False,
    }
    pwc = read(ROOT / 'research/2026-09-29/data-center-expansion/latest.json')
    state['pwc-data-center-buildings'] = {
        key: pwc.get(key) for key in ['status', 'completed_at', 'actual_building_records',
                                     'status_counts', 'native_geography', 'production_admission']}
    nationwide_root = ROOT / 'research/2026-09-29/nationwide-portals'
    nationwide = read(nationwide_root / 'discovery-latest.json')
    schedule = read(nationwide_root / 'runtime/schedule-state.json')
    state['nationwide-discovery'] = {
        **{key: nationwide.get(key) for key in ['stage', 'completed_at', 'jurisdictions_planned',
           'actual_server_catalog_query_pages', 'catalog_listing_filter_jobs', 'candidate_occurrences',
           'errors_requiring_attention']},
        'schedule_status': schedule.get('status'), 'next_query': schedule.get('next_query'),
        'scope': 'Catalog metadata candidates; not collected observation datasets.',
    }
    original_completed = [r for r in local.get('collections', {}).values()
                          if r.get('status') == 'source_collected']
    new_completed = [r for r in regional_jobs.values() if r.get('status') == 'complete']
    pwc_complete = pwc.get('status') == 'collected_verified_source_snapshot'
    state['regional-dataset-totals'] = {
        'completed_datasets': len(original_completed) + len(new_completed) + int(pwc_complete),
        'source_rows': sum(r.get('rows', 0) for r in original_completed + new_completed)
                       + (pwc.get('actual_building_records', 0) if pwc_complete else 0),
        'scope': 'Mixed source units, including aggregates and buildings; not production observations.',
        'production_admission': False,
    }
    db = read(MAINTENANCE / 'progress.json')
    state['database-compaction'] = {
        **db, 'process_alive': alive(db.get('pid')),
        'result': read(MAINTENANCE / 'result.json'),
    }
    backup = MAINTENANCE / 'usa-atlas-before-compact.dump'
    if backup.exists():
        state['database-compaction']['backup_bytes_so_far'] = backup.stat().st_size
        state['database-compaction']['backup_verified'] = bool(read(MAINTENANCE / 'backup.json').get('sha256'))
    coverage = read(ROOT / 'research/2026-09-29/production-coverage.json')
    if coverage.get('status') == 'complete':
        groups = coverage.get('coverage', [])
        fields = {row['catalog_field_id'] for row in groups}
        excluded_food = {'08.01', '08.02', '08.03', '08.06', '09.01', '09.02', '09.03'}
        state['production-coverage-snapshot'] = {
            'snapshot_at': coverage.get('snapshot_at'),
            'observation_rows': coverage.get('observation_rows'),
            'populated_catalog_fields': len(fields),
            'catalog_fields_total': len(fields) + len(coverage.get('catalog_fields_without_rows', [])),
            'populated_non_food_fields': len(fields - excluded_food),
            'block_group_rows': sum(row['observation_rows'] for row in groups if row['geo_type'] == 'block_group'),
            'stored_geo_types': sorted({row['geo_type'] for row in groups}),
            'scope': 'Saved production inventory at snapshot_at, not a fresh database query; later admissions require a new inventory.',
        }
    watchdog = read(ROOT / 'full/runtime/watchdog/state.json')
    try:
        watchdog_age = (datetime.now(timezone.utc) - datetime.fromisoformat(watchdog['checked_at'])).total_seconds()
    except (KeyError, ValueError, TypeError):
        watchdog_age = None
    state['watchdog'] = {
        'checked_at': watchdog.get('checked_at'),
        'snapshot_age_seconds': round(watchdog_age) if watchdog_age is not None else None,
        'snapshot_stale': watchdog_age is None or watchdog_age > 300,
        'overall_state': watchdog.get('overall_state', 'not_started'),
        'needs_attention': watchdog.get('needs_attention', []),
        'jobs': {key: {'state': item.get('state'), 'reason': item.get('reason')}
                 for key, item in watchdog.get('jobs', {}).items()},
    }
    state['note'] = 'Checkpoint status is not production admission. PID liveness alone does not prove progress; inspect timestamps and logs.'
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
