#!/usr/bin/env python3
"""Inspect Atlas workers; --apply enables bounded recovery of owned workers.

Set enabled=false globally or on a job in scraper-watchdog.json before maintenance.
--check alone is read-only. --status prints the last persisted watchdog report.
Completed jobs are never restarted. Database maintenance is always read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'ops/scraper-watchdog.json'
RUNTIME = ROOT / 'full/runtime/watchdog'
TRANSIENT = ('network_', 'http_408', 'http_429', 'http_500', 'http_502',
             'http_503', 'http_504', 'TimeoutError', 'ConnectionResetError',
             'RemoteDisconnected', 'IncompleteRead', 'ConnectionAbortedError')


def now():
    return datetime.now(timezone.utc).isoformat()


def epoch(value):
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0.0


def path(value):
    return (ROOT / value).resolve()


def read(file):
    try:
        value = json.loads(file.read_text())
        if not isinstance(value, dict):
            raise ValueError('object_required')
        return value
    except FileNotFoundError:
        return {}


def save(file, value):
    temporary = file.with_suffix(file.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(file)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def process(pid, script, required=()):
    """Identify a live process by command arguments and kernel start ticks."""
    if not isinstance(pid, int) or pid < 1:
        return None
    try:
        folder = Path('/proc') / str(pid)
        argv = folder.joinpath('cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
        fields = folder.joinpath('stat').read_text().rsplit(')', 1)[1].split()
        cwd = folder.joinpath('cwd').resolve()
        script_matches = any((cwd / token).resolve() == path(script)
                             for token in argv[1:3] if token.endswith('.py'))
        if fields[0] == 'Z' or not script_matches or any(token not in argv for token in required):
            return None
        return {'pid': pid, 'process_start_ticks': int(fields[19]), 'boot_id': boot_id()}
    except (OSError, ValueError, IndexError, UnicodeError):
        return None


def matching_processes(job):
    result = []
    for folder in Path('/proc').iterdir():
        if not folder.name.isdecimal():
            continue
        for spec in job['processes']:
            identity = process(int(folder.name), spec['script'], spec.get('required', []))
            if identity:
                result.append(identity)
                break
    return result


def held(file):
    """Inspect the collector's existing flock without creating or removing it."""
    try:
        with file.open('r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    return False


def bindings_ok(job):
    pins = job.get('code_sha256', {})
    if not pins:
        return False
    for filename, expected in pins.items():
        if not isinstance(expected, str) or len(expected) != 64:
            return False
        try:
            actual = hashlib.sha256(path(filename).read_bytes()).hexdigest()
        except OSError:
            return False
        if actual != expected:
            return False
    return True


def service_info(name):
    result = subprocess.run(['systemctl', 'show', name, '--property=LoadState,ActiveState,SubState,MainPID,Result,NRestarts,FragmentPath,DropInPaths,ExecStart,UnitFileState,NextElapseUSecRealtime,NextElapseUSecMonotonic,LastTriggerUSec'],
                            text=True, capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise RuntimeError('systemctl_show_failed')
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def observe_progress(previous, signature, source_time, clock):
    if previous.get('progress_signature') == signature:
        changed = previous.get('progress_changed_epoch', clock)
    else:
        # On first adoption use the actual checkpoint time, not an artificial
        # fresh heartbeat. Later changes prove new work since our last sample.
        changed = clock if previous else (source_time or clock)
    return {'progress_signature': signature, 'progress_changed_epoch': changed,
            'progress_age_seconds': max(0, round(clock - changed))}


def artifacts_ok(manifest, folder, public=False):
    """Cheap existence/size checks; this is not full checksum revalidation."""
    for record in manifest.get('jobs', {}).values():
        if record.get('status') not in ('complete', 'source_tables_collected'):
            continue
        for key in ('raw', 'table' if public else 'normalized'):
            item = record.get(key, {})
            file = (folder / item.get('path', '')).resolve()
            if not file.is_relative_to(folder.resolve()) or not file.is_file():
                return False
            if not isinstance(item.get('bytes'), int) or file.stat().st_size != item['bytes']:
                return False
    return True


def completed(job, manifest):
    expected = job['expected_jobs']
    final = 'complete_source_tables' if job['kind'] == 'public' else 'complete'
    item_final = 'source_tables_collected' if job['kind'] == 'public' else 'complete'
    records = manifest.get('jobs', {})
    return (manifest.get('status') == final and len(records) == expected
            and all(record.get('status') == item_final for record in records.values()))


def batch(job, previous, clock):
    manifest_path = path(job['manifest'])
    manifest = read(manifest_path)
    supervisor = read(path(job['supervisor'])) if job.get('supervisor') else {}
    report = {'completed_jobs': sum(r.get('status') in ('complete', 'source_tables_collected') for r in manifest.get('jobs', {}).values()),
              'planned_jobs': job['expected_jobs'], 'automatic_recovery': True}
    if not manifest:
        return {**report, 'state': 'needs_attention', 'reason': 'manifest_missing_no_automatic_first_launch'}
    if not artifacts_ok(manifest, manifest_path.parent, job['kind'] == 'public'):
        return {**report, 'state': 'needs_attention', 'reason': 'completed_artifact_missing_or_size_changed'}
    if completed(job, manifest):
        return {**report, 'state': 'complete', 'reason': 'all_planned_jobs_complete'}
    if manifest.get('status') in ('complete', 'complete_source_tables'):
        return {**report, 'state': 'needs_attention', 'reason': 'completed_manifest_count_mismatch'}
    if not bindings_ok(job):
        return {**report, 'state': 'needs_attention', 'reason': 'code_binding_changed'}
    failures = [r for r in manifest.get('jobs', {}).values() if r.get('status') == 'blocked_or_failed']
    for failure in failures:
        transient = (failure.get('reason', '').startswith(TRANSIENT)
                     or failure.get('http_status') in (408, 429, 500, 502, 503, 504)
                     or failure.get('error_class') in ('TimeoutError', 'ConnectionResetError', 'RemoteDisconnected', 'IncompleteRead', 'ConnectionAbortedError'))
        if not transient:
            return {**report, 'state': 'needs_attention', 'reason': 'nontransient_or_unclassified_source_failure'}
    if supervisor.get('status', '').startswith(('failed_code', 'failed_collector', 'blocked_')):
        return {**report, 'state': 'needs_attention', 'reason': 'supervisor_binding_or_dependency_failure'}
    if supervisor.get('status') == 'failed' and not supervisor.get('reason', '').startswith(TRANSIENT):
        return {**report, 'state': 'needs_attention', 'reason': 'unclassified_supervisor_failure'}
    processes = matching_processes(job)
    report['processes'] = processes
    signature_parts = [manifest.get('status'), manifest.get('active_job'), report['completed_jobs'],
                       [(name, row.get('status'), row.get('completed_at')) for name, row in manifest.get('jobs', {}).items()]]
    partials = []
    for folder in (manifest_path.parent / 'raw', manifest_path.parent / 'data', manifest_path.parent / 'tables'):
        if folder.exists():
            partials.extend((p.name, p.stat().st_size) for p in folder.glob('*.part') if p.is_file())
    signature_parts.append(partials)
    signature = hashlib.sha256(json.dumps(signature_parts, sort_keys=True).encode()).hexdigest()
    report.update(observe_progress(previous, signature, epoch(manifest.get('updated_at')), clock))
    if processes:
        if report['progress_age_seconds'] > job['stale_seconds']:
            return {**report, 'state': 'needs_attention', 'reason': 'live_worker_without_semantic_progress_no_automatic_kill'}
        return {**report, 'state': 'retrying' if supervisor.get('status') == 'retry_wait' else 'healthy', 'reason': 'owned_worker_running'}
    if any(held(path(lock)) for lock in job.get('locks', [])):
        return {**report, 'state': 'needs_attention', 'reason': 'worker_lock_held_by_unidentified_process'}
    return {**report, 'state': 'retrying', 'reason': 'unfinished_worker_stopped', 'requested_action': 'start'}


def local(job, previous, clock):
    unit = service_info(job['service'])
    report = {'service': job['service'], 'unit_state': unit.get('ActiveState'),
              'automatic_recovery': True, 'systemd_restarts': int(unit.get('NRestarts') or 0)}
    state = read(path(job['manifest']))
    errors = [key for key, record in state.get('collections', {}).items() if record.get('status') == 'needs_review']
    report['collections_needing_review'] = errors
    if unit.get('LoadState') != 'loaded' or unit.get('FragmentPath') != job['unit_file'] or unit.get('DropInPaths'):
        return {**report, 'state': 'needs_attention', 'reason': 'service_definition_unrecognized'}
    if not bindings_ok(job):
        return {**report, 'state': 'needs_attention', 'reason': 'code_or_unit_binding_changed'}
    if unit.get('Result') == 'start-limit-hit':
        return {**report, 'state': 'needs_attention', 'reason': 'systemd_start_limit_hit_manual_review_required'}
    pid = int(unit.get('MainPID') or 0)
    identity = process(pid, job['processes'][0]['script'], ['daemon'])
    report['process'] = identity
    if unit.get('ActiveState') in ('activating', 'deactivating', 'reloading'):
        return {**report, 'state': 'retrying', 'reason': 'systemd_transition_in_progress'}
    if unit.get('ActiveState') not in ('active',):
        if matching_processes(job) or any(held(path(lock)) for lock in job.get('locks', [])):
            return {**report, 'state': 'needs_attention', 'reason': 'detached_worker_or_unidentified_lock'}
        return {**report, 'state': 'retrying', 'reason': 'daemon_stopped', 'requested_action': 'start'}
    if not identity:
        return {**report, 'state': 'needs_attention', 'reason': 'main_pid_identity_mismatch'}
    heartbeat = read(path(job['heartbeat']))
    if any(str(heartbeat.get(key)) != str(identity[key]) for key in ('pid', 'boot_id', 'process_start_ticks')):
        return {**report, 'state': 'needs_attention', 'reason': 'heartbeat_process_identity_mismatch'}
    phase = heartbeat.get('phase')
    heartbeat_age = clock - epoch(heartbeat.get('updated_at'))
    progress_age = clock - epoch(heartbeat.get('progress_at'))
    report.update(phase=phase, heartbeat_age_seconds=max(0, round(heartbeat_age)),
                  progress_age_seconds=max(0, round(progress_age)), next_cycle_at=heartbeat.get('next_cycle_at'))
    if phase == 'cycle_error' or heartbeat.get('last_cycle_outcome') == 'error':
        return {**report, 'state': 'needs_attention', 'reason': 'cycle_error_requires_review'}
    if heartbeat_age > job['stale_seconds']:
        return {**report, 'state': 'retrying', 'reason': 'daemon_heartbeat_stale', 'requested_action': 'restart', 'expected_identity': identity}
    if phase == 'sleeping':
        next_cycle = epoch(heartbeat.get('next_cycle_at'))
        if not next_cycle or next_cycle > clock + job['interval_seconds'] + job['idle_grace_seconds']:
            return {**report, 'state': 'needs_attention', 'reason': 'invalid_next_cycle_deadline'}
        if clock > next_cycle + job['idle_grace_seconds']:
            return {**report, 'state': 'retrying', 'reason': 'next_cycle_deadline_missed', 'requested_action': 'restart', 'expected_identity': identity}
        return {**report, 'state': 'needs_attention' if errors else 'idle', 'reason': 'collection_content_needs_review' if errors else 'waiting_for_scheduled_cycle'}
    if progress_age > job['stale_seconds']:
        return {**report, 'state': 'retrying', 'reason': 'daemon_semantic_progress_stale', 'requested_action': 'restart', 'expected_identity': identity}
    return {**report, 'state': 'needs_attention' if errors else 'healthy', 'reason': 'collection_content_needs_review' if errors else 'cycle_has_progress'}


def database(job, previous, clock):
    state = read(path(job['manifest']))
    result = read(path(job['result']))
    phase = state.get('phase')
    report = {'automatic_recovery': False, 'phase': phase, 'updated_at': state.get('updated_at')}
    if phase == 'complete' or result.get('status') == 'complete':
        return {**report, 'state': 'complete', 'reason': 'database_maintenance_complete'}
    if not state:
        return {**report, 'state': 'idle', 'reason': 'database_maintenance_not_started'}
    if phase == 'failed':
        return {**report, 'state': 'needs_attention', 'reason': 'database_maintenance_failed_read_only_monitor'}
    identity = process(state.get('pid'), job['processes'][0]['script'])
    age = clock - epoch(state.get('updated_at'))
    report.update(process=identity, checkpoint_age_seconds=max(0, round(age)))
    if not identity or age > job['stale_seconds']:
        return {**report, 'state': 'needs_attention', 'reason': 'database_checkpoint_stale_or_process_stopped_read_only_monitor'}
    return {**report, 'state': 'healthy', 'reason': 'database_maintenance_running_no_automatic_actions'}


def scheduled(job, previous, clock):
    """Observe timer-owned jobs without duplicating systemd's recovery policy."""
    service = service_info(job['service'])
    timer = service_info(job['timer'])
    report = {'service': job['service'], 'timer': job['timer'],
              'automatic_recovery': 'bounded_by_systemd', 'unit_state': service.get('ActiveState'),
              'timer_state': timer.get('ActiveState'), 'next_scheduled_at': timer.get('NextElapseUSecRealtime'),
              'next_scheduled_monotonic': timer.get('NextElapseUSecMonotonic'),
              'systemd_restarts': int(service.get('NRestarts') or 0)}
    for info, filename in ((service, job['unit_file']), (timer, job['timer_file'])):
        if info.get('LoadState') != 'loaded' or info.get('FragmentPath') != filename or info.get('DropInPaths'):
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_unit_definition_unrecognized'}
    if not bindings_ok(job):
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_code_or_unit_binding_changed'}
    if timer.get('ActiveState') != 'active' or timer.get('UnitFileState') not in ('enabled', 'enabled-runtime'):
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_timer_not_enabled_and_active'}
    if service.get('Result') == 'start-limit-hit':
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_systemd_start_limit_hit'}
    manifest = read(path(job['manifest']))
    report.update(last_cycle_status=manifest.get('status'),
                  last_cycle_finished_at=manifest.get('finished_at') or manifest.get('completed_at'))
    pid = int(service.get('MainPID') or 0)
    if service.get('ActiveState') in ('active', 'activating', 'deactivating'):
        identity = process(pid, job['processes'][0]['script'])
        report['process'] = identity
        if not identity:
            # ExecCondition, termination, and RestartSec are bounded by the
            # service's own deadlines; none warrants an independent restart.
            return {**report, 'state': 'retrying', 'reason': 'scheduled_service_transition'}
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        age = max(0, uptime - identity['process_start_ticks'] / os.sysconf('SC_CLK_TCK'))
        report['run_age_seconds'] = round(age)
        if age > job['run_deadline_seconds']:
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_worker_exceeded_deadline_systemd_owns_stop'}
        return {**report, 'state': 'healthy', 'reason': 'scheduled_worker_running_with_bounded_deadline'}
    if service.get('ActiveState') == 'failed':
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_service_failed'}
    if not manifest:
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_first_cycle_missing'}
    if manifest.get('status') not in job['success_statuses']:
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_cycle_failed_or_incomplete'}
    if job.get('record_count_field'):
        report['source_records'] = manifest.get(job['record_count_field'])
    if job.get('artifact_list_field'):
        folder = path(job['manifest']).parent
        artifacts = manifest.get(job['artifact_list_field'], [])
        if not artifacts:
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_artifact_manifest_missing'}
        for item in artifacts:
            artifact = (folder / item.get('path', '')).resolve()
            if not artifact.is_relative_to(folder) or not artifact.is_file() or artifact.stat().st_size != item.get('bytes'):
                return {**report, 'state': 'needs_attention', 'reason': 'scheduled_artifact_missing_or_size_changed'}
    summary = {}
    if job.get('summary_pointer'):
        relative = manifest.get(job['summary_pointer'])
        if not relative:
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_summary_pointer_missing'}
        folder = path(job['manifest']).parent
        summary_file = (folder / relative).resolve()
        if not summary_file.is_relative_to(folder):
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_summary_path_invalid'}
        summary = read(summary_file)
    elif job.get('summary_file'):
        summary = read(path(job['summary_file']))
    if job.get('expected_jobs'):
        jobs = summary.get('jobs', {})
        report['completed_jobs'] = sum(row.get('status') == 'complete' for row in jobs.values())
        report['planned_jobs'] = job['expected_jobs']
        if summary.get('status') != 'complete' or report['completed_jobs'] != job['expected_jobs'] or len(jobs) != job['expected_jobs']:
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_dataset_summary_incomplete'}
    if job.get('expected_jurisdictions'):
        report.update(jurisdictions_planned=summary.get('jurisdictions_planned'),
                      query_results=summary.get('query_results'),
                      actual_server_catalog_query_pages=summary.get('actual_server_catalog_query_pages'),
                      candidate_occurrences=summary.get('candidate_occurrences'),
                      source_errors=summary.get('errors_requiring_attention', {}))
        if summary.get('jurisdictions_planned') != job['expected_jurisdictions'] or summary.get('stage') != 'complete_bounded_metadata_discovery':
            return {**report, 'state': 'needs_attention', 'reason': 'scheduled_nationwide_summary_incomplete'}
        # Failed HTTP attempts can precede a successful fallback adapter; keep
        # them visible, but alert on unresolved work rather than recovered tries.
        if any(value for key, value in report['source_errors'].items() if key != 'http_error_attempts'):
            return {**report, 'state': 'needs_attention', 'reason': 'completed_discovery_has_source_errors_review_required'}
    finished = epoch(report['last_cycle_finished_at'])
    report['completed_cycle_age_seconds'] = max(0, round(clock - finished))
    if not finished or clock - finished > job['freshness_seconds']:
        return {**report, 'state': 'needs_attention', 'reason': 'scheduled_completed_cycle_overdue'}
    return {**report, 'state': 'idle', 'reason': 'scheduled_cycle_complete_waiting_for_timer'}


def action(job, report, attempts, clock):
    """Recheck ownership immediately before mutating an explicitly owned worker."""
    if not bindings_ok(job):
        raise RuntimeError('binding_changed_before_action')
    if job['kind'] == 'local':
        info = service_info(job['service'])
        if info.get('FragmentPath') != job['unit_file'] or info.get('DropInPaths'):
            raise RuntimeError('service_changed_before_action')
        if report['requested_action'] == 'restart':
            current = process(int(info.get('MainPID') or 0), job['processes'][0]['script'], ['daemon'])
            if current != report.get('expected_identity'):
                raise RuntimeError('pid_changed_before_action')
        elif info.get('ActiveState') not in ('inactive', 'failed'):
            raise RuntimeError('service_state_changed_before_action')
        # No reset-failed: preserve systemd's separate start rate limit.
        result = subprocess.run(['systemctl', '--no-block', report['requested_action'], job['service']],
                                capture_output=True, timeout=15, check=False)
        if result.returncode:
            raise RuntimeError('systemctl_recovery_request_failed')
        return {'operation': report['requested_action'], 'service': job['service'], 'requested_at': now()}
    if matching_processes(job) or any(held(path(lock)) for lock in job.get('locks', [])):
        raise RuntimeError('worker_appeared_before_action')
    # The recovery receives its own systemd cgroup: a detached Popen would still
    # be killed when this oneshot service exits. The collector also takes its
    # existing flock itself, closing the final launch race safely.
    command = [part.replace('{root}', str(ROOT)) for part in job['restart_command']]
    log = RUNTIME / (job['id'] + '.recovery.log')
    unit = 'usa-atlas-watchdog-recovery-' + job['id']
    result = subprocess.run(['systemd-run', '--unit=' + unit, '--collect',
                             '--property=WorkingDirectory=' + str(ROOT), '--property=Restart=no',
                             '--property=StandardOutput=append:' + str(log),
                             '--property=StandardError=append:' + str(log), '--', *command],
                            capture_output=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError('systemd_recovery_unit_start_failed')
    return {'operation': 'start', 'service': unit + '.service', 'requested_at': now()}


def check(config, prior, apply):
    clock = time.time()
    free = shutil.disk_usage(ROOT).free
    report = {'checked_at': now(), 'apply': apply, 'enabled': config.get('enabled', False),
              'disk_free_bytes': free, 'disk_floor_bytes': config['disk_floor_bytes'],
              'jobs': {}, 'maintenance_switch': 'Set enabled=false in ops/scraper-watchdog.json before stopping workers.',
              'artifact_checks': 'Existence and byte sizes only; source collectors validate checksums on resume.'}
    records = prior.get('jobs', {})
    for job in config['jobs']:
        previous = records.get(job['id'], {})
        attempts = [stamp for stamp in previous.get('recovery_attempts', []) if clock - stamp < config['retry_window_seconds']]
        try:
            if not config.get('enabled') or not job.get('enabled', False):
                current = {'state': 'idle', 'reason': 'monitoring_disabled_for_maintenance'}
            else:
                current = {'local': local, 'batch': batch, 'public': batch, 'database': database,
                           'scheduled': scheduled}[job['kind']](job, previous, clock)
            current['recovery_attempts'] = attempts
            requested = current.get('requested_action')
            if requested:
                if free < config['disk_floor_bytes']:
                    current.update(state='needs_attention', reason='disk_headroom_below_recovery_floor')
                elif len(attempts) >= config['max_recovery_attempts']:
                    current.update(state='needs_attention', reason='recovery_budget_exhausted')
                elif attempts and clock < attempts[-1] + min(config['max_backoff_seconds'], config['initial_backoff_seconds'] * 2 ** (len(attempts) - 1)):
                    current.update(state='retrying', reason='recovery_backoff')
                elif apply:
                    # Persist an attempt before launching, surviving watchdog
                    # interruption and preventing duplicate uncounted retries.
                    attempts.append(clock)
                    report['jobs'][job['id']] = current
                    interim = {**prior, **report, 'jobs': {**records, **report['jobs']}}
                    save(RUNTIME / 'state.json', interim)
                    current['last_action'] = action(job, current, attempts, clock)
                else:
                    current['dry_run_action'] = requested
            report['jobs'][job['id']] = current
        except Exception as exc:
            # Never echo external response text, command output or credentials.
            report['jobs'][job['id']] = {'state': 'needs_attention', 'reason': 'watchdog_inspection_or_recovery_error',
                                        'error_class': type(exc).__name__, 'recovery_attempts': attempts}
    attention = [key for key, value in report['jobs'].items() if value['state'] == 'needs_attention']
    report['needs_attention'] = attention
    recovering = any(item['state'] == 'retrying' for item in report['jobs'].values())
    report['overall_state'] = ('needs_attention' if attention or free < config['disk_floor_bytes']
                               else 'retrying' if recovering else 'healthy')
    return report


def journal(report, prior):
    file = RUNTIME / 'events.jsonl'
    if file.exists() and file.stat().st_size > 2 * 1024 ** 2:
        file.replace(RUNTIME / 'events.previous.jsonl')
    events = []
    for key, current in report['jobs'].items():
        old = prior.get('jobs', {}).get(key, {})
        if (current.get('state'), current.get('reason')) != (old.get('state'), old.get('reason')) or current.get('last_action'):
            events.append({'at': report['checked_at'], 'job': key, 'state': current['state'],
                           'reason': current.get('reason'), 'action': current.get('last_action')})
    if events:
        with file.open('a') as stream:
            for event in events:
                stream.write(json.dumps(event, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--status', action='store_true')
    mode.add_argument('--preflight', metavar='JOB', help='Read-only systemd ExecCondition: pins, maintenance switch and disk headroom.')
    parser.add_argument('--apply', action='store_true', help='Persist health and enable reviewed recovery actions.')
    parser.add_argument('--config', type=Path, default=CONFIG)
    args = parser.parse_args()
    if args.preflight:
        config = read(args.config.resolve())
        job = next((item for item in config.get('jobs', []) if item['id'] == args.preflight), None)
        allowed = bool(config.get('enabled') and job and job.get('enabled')
                       and job.get('kind') == 'scheduled' and bindings_ok(job)
                       and shutil.disk_usage(ROOT).free >= config['disk_floor_bytes'])
        print(json.dumps({'job': args.preflight, 'preflight': 'allowed' if allowed else 'blocked',
                          'checks': 'enabled, reviewed code/unit hashes, disk headroom'}))
        return 0 if allowed else 1
    if args.status:
        print(json.dumps(read(RUNTIME / 'state.json'), indent=2))
        return 0
    lock = None
    if args.apply:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        lock = (RUNTIME / 'watchdog.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'state': 'idle', 'reason': 'another_watchdog_check_is_running'}))
            return 0
    prior = read(RUNTIME / 'state.json')
    config = read(args.config.resolve())
    if config.get('version') != 1 or not config.get('jobs'):
        raise SystemExit('Invalid watchdog config; no actions taken.')
    report = check(config, prior, args.apply)
    if args.apply:
        save(RUNTIME / 'state.json', report)
        journal(report, prior)
    print(json.dumps(report, indent=2))
    # Health failures are in the durable report/journal; timer must continue
    # checking without systemd treating a monitored-worker alert as own failure.
    return 0


if __name__ == '__main__':
    sys.exit(main())
