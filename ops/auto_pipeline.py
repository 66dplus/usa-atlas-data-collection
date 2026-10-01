#!/usr/bin/env python3
"""Consume completed artifacts through reviewed adapters and idempotent DB admission.

--once is a read-only discovery/verification plan. --once --apply prepares and
admits bounded batches. Collectors keep their independent schedules. This runner
never interprets catalog candidates as datasets and never edits collector code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import sys
import time

import auto_pipeline_retention

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'ops/auto-pipeline.json'


class Deferred(Exception):
    pass


class ContentError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def read(file, default=None):
    try:
        return json.loads(file.read_text())
    except FileNotFoundError:
        return {} if default is None else default


def save(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temp = file.with_suffix(file.suffix + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    temp.replace(file)


def local_path(value, base=ROOT):
    result = (base / value).resolve()
    if not result.is_relative_to(ROOT):
        raise ContentError('path_outside_repository')
    return result


def digest(file, deadline=None):
    value = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 ** 2), b''):
            if deadline is not None and time.monotonic() >= deadline:
                raise Deferred('cycle_time_budget')
            value.update(chunk)
    return value.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_pins(pins):
    if not pins:
        raise ContentError('code_not_pinned_installation_required')
    for name, expected in pins.items():
        if not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected):
            raise ContentError('invalid_code_pin')
        file = local_path(name)
        if not file.is_file() or digest(file) != expected:
            raise ContentError('reviewed_code_binding_changed')


def stat_signature(file):
    stat = file.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def verified_file(item, cache, deadline):
    file = local_path(item['path'])
    expected = item.get('sha256', '')
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ContentError('source_sha256_missing')
    if not file.is_file():
        raise ContentError('source_artifact_missing')
    before = stat_signature(file)
    if item.get('bytes') is not None and before[2] != item['bytes']:
        raise ContentError('source_artifact_size_mismatch')
    key = str(file.relative_to(ROOT))
    previous = cache.get(key, {})
    if previous.get('stat') == before and previous.get('sha256') == expected:
        return
    actual = digest(file, deadline)
    if actual != expected or stat_signature(file) != before:
        raise ContentError('source_artifact_hash_mismatch_or_changed_during_read')
    cache[key] = {'stat': before, 'sha256': actual, 'verified_at': now()}


def verify_candidate(candidate, cache, deadline):
    if not isinstance(candidate.get('dataset_id'), str) or not candidate['dataset_id']:
        raise ContentError('candidate_dataset_id_missing')
    verified_file({'path': candidate['source_manifest_path'],
                   'sha256': candidate['source_manifest_sha256']}, cache, deadline)
    if not candidate.get('source_artifacts'):
        raise ContentError('candidate_source_artifacts_missing')
    for item in candidate['source_artifacts']:
        verified_file(item, cache, deadline)


def busy(file):
    """Probe a real OS flock. There are no lease expirations or forced unlocks."""
    try:
        handle = file.open('r')
    except FileNotFoundError:
        return False
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def maintenance_busy(config):
    return any(busy(Path(name) if Path(name).is_absolute() else ROOT / name)
               for name in config.get('maintenance_locks', []))


def headroom(config):
    if shutil.disk_usage(ROOT).free < config['disk_floor_bytes']:
        raise Deferred('disk_headroom_below_floor')


def terminate_owned(child):
    """Only the process group created by this runner; never scan or global pkill."""
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=20)


def run_child(command, log, timeout, heartbeat=None, capture=False):
    started = time.monotonic()
    target = subprocess.PIPE if capture else log.open('ab', buffering=0)
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                             stdout=target, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        if capture:
            output, _ = child.communicate(timeout=timeout)
            if len(output) > 8 * 1024 ** 2:
                raise ContentError('adapter_discovery_output_too_large')
            return child.returncode, output
        while child.poll() is None:
            if time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(command[0], timeout)
            if heartbeat:
                heartbeat(child.pid)
            time.sleep(2)
        return child.returncode, None
    except BaseException:
        terminate_owned(child)
        raise
    finally:
        if not capture:
            target.close()


def event(runtime, **data):
    file = runtime / 'events.jsonl'
    if file.exists() and file.stat().st_size > 4 * 1024 ** 2:
        file.replace(runtime / 'events.previous.jsonl')
    with file.open('a') as stream:
        stream.write(json.dumps({'at': now(), **data}, sort_keys=True) + '\n')


def reason_code(value, fallback):
    return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', value) else fallback


def defer_job(job, config, reason, requested_delay=0, maintenance=False):
    clock = time.time()
    history = [stamp for stamp in job.get('transient_failures', [])
               if clock - stamp < config['retry']['window_seconds']]
    if not maintenance:
        history.append(clock)
    delay = config['retry']['maintenance_seconds'] if maintenance else min(
        config['retry']['max_seconds'], config['retry']['base_seconds'] * 2 ** min(len(history) - 1, 12))
    delay = max(delay, requested_delay or 0)
    if len(history) >= config['retry']['max_attempts_per_window']:
        delay = max(delay, history[0] + config['retry']['window_seconds'] - clock)
    delay += random.SystemRandom().uniform(0, delay * config['retry']['jitter_fraction'])
    job.update(status='deferred_maintenance' if maintenance else 'retry_wait', reason=reason,
               next_attempt_epoch=clock + delay, transient_failures=history, updated_at=now())


def candidate_key(candidate, adapter):
    return fingerprint({'adapter': adapter['id'], 'code': adapter['code_sha256'],
                        'dataset_id': candidate['dataset_id'], 'revision': candidate.get('revision'),
                        'source_manifest_sha256': candidate['source_manifest_sha256'],
                        'artifacts': [(item['path'], item['sha256']) for item in candidate['source_artifacts']]})


def current_counts(state):
    jobs = [state['jobs'][key] for key in state.get('current_candidate_keys', []) if key in state['jobs']]
    states = ('pending', 'prepared', 'preparing', 'admitting', 'retry_wait', 'deferred_maintenance', 'quarantine', 'complete')
    state['current_candidate_counts'] = {status: sum(job['status'] == status for job in jobs) for status in states}
    state['remaining_candidates'] = len(jobs) - state['current_candidate_counts']['complete']


def discover(config, state, deadline, apply):
    candidates, errors = [], {}
    cache = state.setdefault('verified_sources', {})
    for adapter in config['adapters']:
        if not adapter.get('enabled') or not adapter.get('reviewed'):
            continue
        try:
            check_pins(adapter['code_sha256'])
            timeout = min(config['discovery_timeout_seconds'], max(1, deadline - time.monotonic()))
            code, output = run_child([sys.executable, str(local_path(adapter['script'])), 'discover', '--json'],
                                     None, timeout, capture=True)
            if code:
                raise ContentError('adapter_discovery_failed')
            packet = json.loads(output)
            if not isinstance(packet.get('candidates'), list):
                raise ContentError('adapter_discovery_protocol_invalid')
            for blocked in packet.get('blocked', []):
                name = str(blocked.get('dataset_id', 'unknown'))[:120]
                errors[adapter['id'] + ':' + name] = reason_code(blocked.get('reason'), 'registered_source_not_ready')
            for candidate in packet['candidates']:
                # An entry can only originate from a pinned, reviewed adapter.
                # No command or importer code is accepted from source metadata.
                try:
                    key = candidate_key(candidate, adapter)
                    verify_candidate(candidate, cache, deadline)
                    candidates.append((key, adapter, candidate))
                except Deferred:
                    raise
                except (KeyError, OSError, TypeError, ValueError, ContentError) as exc:
                    name = str(candidate.get('dataset_id', 'unknown'))[:120]
                    errors[adapter['id'] + ':' + name] = reason_code(str(exc), type(exc).__name__)
        except Deferred:
            errors['discovery'] = 'cycle_time_budget_during_source_verification'
            break
        except (OSError, ValueError, TypeError, ContentError, subprocess.TimeoutExpired) as exc:
            errors[adapter['id']] = reason_code(str(exc), type(exc).__name__)
    return candidates, errors


def prepare_and_admit(config, runtime, state, key, adapter, candidate, deadline, prepare_only=False):
    jobs = state['jobs']
    job = jobs[key]
    headroom(config)
    if not prepare_only and maintenance_busy(config):
        raise Deferred('database_maintenance_or_load_lock_held')
    check_pins(adapter['code_sha256'])
    if not prepare_only:
        check_pins(config['loader']['code_sha256'])
    verify_candidate(candidate, state['verified_sources'], deadline)
    cursor = job.get('cursor')
    batch_key = fingerprint({'candidate_key': key, 'cursor': cursor})
    folder = runtime / 'batches' / key / batch_key
    folder.mkdir(parents=True, exist_ok=True)
    candidate_file = folder / 'candidate.json'
    if candidate_file.exists() and read(candidate_file) != candidate:
        raise ContentError('immutable_candidate_record_changed')
    if not candidate_file.exists():
        save(candidate_file, candidate)
    result_file = folder / 'prepare-result.json'
    prepared = read(result_file)
    if prepared.get('status') == 'ready' and (folder / 'retention.json').exists():
        # After a checkpoint restore a deliberately purged batch can be rebuilt
        # from its verified source at the same deterministic paths. Preserve the
        # previous prepare metadata and the DB receipt for audit.
        backup = folder / 'prepare-result.before-rebuild.json'
        if not backup.exists():
            save(backup, prepared)
        result_file.unlink()
        prepared = {}

    def heartbeat(pid):
        state.update(updated_at=now(), active_dataset=job['dataset_id'], active_batch=batch_key,
                     child_pid=pid, child_stage=job['status'])
        current_counts(state)
        save(runtime / 'state.json', state)

    if prepared.get('status') != 'ready':
        job.update(status='preparing', updated_at=now(), current_batch=batch_key)
        save(runtime / 'state.json', state)
        command = [sys.executable, str(local_path(adapter['script'])), 'prepare', '--candidate', str(candidate_file),
                   '--out', str(folder), '--max-rows', str(config['max_input_rows_per_batch']),
                   '--cursor', json.dumps(cursor, separators=(',', ':'))]
        timeout = min(config['prepare_timeout_seconds'], max(1, deadline - time.monotonic()))
        code, _ = run_child(command, folder / 'prepare.log', timeout, heartbeat)
        prepared = read(result_file)
        if code == 75 or prepared.get('status') in ('transient_failure', 'deferred_maintenance'):
            defer_job(job, config, reason_code(prepared.get('reason'), 'adapter_transient_failure'),
                      prepared.get('retry_after_seconds', 0), prepared.get('status') == 'deferred_maintenance')
            return False
        if code or prepared.get('status') != 'ready':
            raise ContentError(reason_code(prepared.get('reason'), 'adapter_prepare_rejected'))
    if not isinstance(prepared.get('complete'), bool) or 'next_cursor' not in prepared:
        raise ContentError('prepare_result_cursor_contract_invalid')
    if not prepared['complete'] and prepared['next_cursor'] == cursor:
        raise ContentError('adapter_cursor_did_not_advance')
    manifest = local_path(prepared.get('manifest', 'admission-manifest.json'), folder)
    if not manifest.is_relative_to(folder) or not manifest.is_file():
        raise ContentError('prepared_manifest_missing_or_outside_batch')
    if prepared.get('manifest_sha256') and digest(manifest) != prepared['manifest_sha256']:
        raise ContentError('prepared_manifest_hash_changed')
    verify_candidate(candidate, state['verified_sources'], deadline)
    if prepare_only:
        job.update(status='prepared', prepared_manifest=str(manifest.relative_to(ROOT)),
                   prepared_manifest_sha256=digest(manifest), prepared_rows=prepared.get('prepared_rows'),
                   updated_at=now(), reason=None)
        return True
    headroom(config)
    if maintenance_busy(config):
        raise Deferred('database_maintenance_or_load_lock_held')
    if time.monotonic() >= deadline:
        raise Deferred('cycle_time_budget')
    check_pins(config['loader']['code_sha256'])
    job.update(status='admitting', updated_at=now(), current_batch=batch_key,
               prepared_manifest=str(manifest.relative_to(ROOT)), prepared_manifest_sha256=digest(manifest))
    save(runtime / 'state.json', state)
    ingest_result = folder / 'ingest-result.json'
    command = [sys.executable, str(local_path(config['loader']['script'])), '--manifest', str(manifest),
               '--apply', '--result', str(ingest_result)]
    timeout = min(config['ingest_timeout_seconds'], max(1, deadline - time.monotonic()))
    code, _ = run_child(command, folder / 'ingest.log', timeout, heartbeat)
    admitted = read(ingest_result)
    status = admitted.get('status')
    if code == 0 and status in ('pass', 'already_pass'):
        if admitted.get('manifest_sha256') != job['prepared_manifest_sha256']:
            raise ContentError('database_receipt_manifest_binding_mismatch')
        job.update(status='complete' if prepared['complete'] else 'pending', cursor=prepared['next_cursor'],
                   accepted_batches=job.get('accepted_batches', 0) + 1,
                   accepted_rows=job.get('accepted_rows', 0) + admitted.get('row_count', 0),
                   last_receipt=str(ingest_result.relative_to(ROOT)), last_ingest_id=admitted.get('ingest_id'),
                   last_batch_id=admitted.get('batch_id'), updated_at=now(), reason=None,
                   next_attempt_epoch=0, transient_failures=[])
        event(runtime, dataset_id=job['dataset_id'], candidate_key=key, batch_id=admitted.get('batch_id'),
              status=status, rows=admitted.get('row_count', 0), complete=prepared['complete'])
        return True
    if code == 75 or status in ('transient_failure', 'deferred_maintenance'):
        defer_job(job, config, reason_code(admitted.get('reason'), 'loader_transient_failure'),
                  admitted.get('retry_after_seconds', 0), status == 'deferred_maintenance')
        return False
    raise ContentError(reason_code(admitted.get('reason'), 'database_admission_rejected'))


def cycle(config, runtime, state, apply, prepare_only=False):
    deadline = time.monotonic() + config['max_runtime_seconds']
    for key in ('completed_at', 'current_candidate_counts', 'remaining_candidates', 'discovered_candidates',
                'discovery_errors', 'deferred_reason', 'reason', 'active_dataset', 'active_batch', 'child_pid', 'child_stage'):
        state.pop(key, None)
    state.update(format='usa_atlas_auto_pipeline_v1', status='running', pid=os.getpid(), started_at=now(),
                 updated_at=now(), disk_free_bytes=shutil.disk_usage(ROOT).free,
                 cycle_phase='discovering', current_candidate_keys=[], batches_attempted_this_cycle=0,
                 operator_note='Catalog candidates are never admitted without a registered reviewed adapter.')
    state.setdefault('jobs', {})
    if apply:
        save(runtime / 'state.json', state)
    if not config.get('enabled') and not prepare_only:
        state.update(status='disabled', completed_at=now())
        return state
    check_pins(config['orchestrator_code_sha256'])
    if not prepare_only:
        check_pins(config['loader']['code_sha256'])
    if apply and not prepare_only and maintenance_busy(config):
        state.update(status='deferred_maintenance', reason='database_maintenance_or_load_lock_held', completed_at=now())
        return state
    headroom(config)
    candidates, errors = discover(config, state, deadline, apply)
    state.update(discovery_errors=errors, discovered_candidates=len(candidates))
    if not apply:
        return {'status': 'read_only_plan', 'checked_at': now(), 'discovery_errors': errors,
                'candidates': [{'key': key, 'adapter': adapter['id'], 'dataset_id': candidate['dataset_id'],
                                'prior_status': state['jobs'].get(key, {}).get('status', 'new')}
                               for key, adapter, candidate in candidates],
                'database_writes': False}
    for key, adapter, candidate in candidates:
        state['jobs'].setdefault(key, {'dataset_id': candidate['dataset_id'], 'adapter_id': adapter['id'],
                                      'source_manifest_sha256': candidate['source_manifest_sha256'],
                                      'status': 'pending', 'cursor': None, 'created_at': now()})
        if state['jobs'][key]['status'] in ('preparing', 'admitting'):
            state['jobs'][key].update(status='pending', reason='resume_after_interrupted_runner')
    state.update(current_candidate_keys=[key for key, _, _ in candidates], cycle_phase='processing_batches')
    current_counts(state)
    save(runtime / 'state.json', state)
    count = 0
    stop = False
    # One batch per candidate per round prevents a large ACS table starving
    # small regional releases. Failed datasets do not block unrelated datasets.
    while not stop and time.monotonic() < deadline and count < config['max_batches_per_cycle']:
        advanced = False
        for key, adapter, candidate in candidates:
            job = state['jobs'][key]
            if job['status'] in ('complete', 'quarantine') or (prepare_only and job['status'] == 'prepared') or time.time() < job.get('next_attempt_epoch', 0):
                continue
            if time.monotonic() >= deadline or count >= config['max_batches_per_cycle']:
                stop = True
                break
            try:
                accepted = prepare_and_admit(config, runtime, state, key, adapter, candidate, deadline, prepare_only)
                count += 1
                advanced = advanced or accepted
            except Deferred as exc:
                defer_job(job, config, reason_code(str(exc), 'resource_deferred'), maintenance=True)
                state['deferred_reason'] = reason_code(str(exc), 'resource_deferred')
                stop = True
            except (subprocess.TimeoutExpired, ConnectionError, TimeoutError) as exc:
                defer_job(job, config, type(exc).__name__)
                count += 1
            except (ContentError, KeyError, TypeError, ValueError, OSError) as exc:
                job.update(status='quarantine', reason=reason_code(str(exc), type(exc).__name__), updated_at=now())
                event(runtime, dataset_id=job['dataset_id'], candidate_key=key, status='quarantine', reason=job['reason'])
                count += 1
            state['batches_attempted_this_cycle'] = count
            current_counts(state)
            save(runtime / 'state.json', state)
            if stop:
                break
        if not advanced:
            break
    current_jobs = [state['jobs'][key] for key, _, _ in candidates]
    counts = {status: sum(job['status'] == status for job in current_jobs)
              for status in ('pending', 'prepared', 'retry_wait', 'deferred_maintenance', 'quarantine', 'complete')}
    if not prepare_only:
        state['retention'] = auto_pipeline_retention.cleanup(config, runtime, state, {key for key, _, _ in candidates}, deadline)
    attention = bool(errors or counts['quarantine'] or state.get('retention', {}).get('errors'))
    remaining = len(current_jobs) - counts['complete']
    state.update(status='needs_attention' if attention else 'prepared' if prepare_only else 'partial' if remaining else 'complete' if current_jobs else 'idle',
                 completed_at=now(), updated_at=now(), batches_attempted_this_cycle=count,
                 cycle_phase='finished',
                 database_writes_requested=not prepare_only,
                 current_candidate_counts=counts, remaining_candidates=remaining,
                 accepted_rows_total=sum(job.get('accepted_rows', 0) for job in state['jobs'].values()),
                 disk_free_bytes=shutil.disk_usage(ROOT).free)
    for key in ('active_dataset', 'active_batch', 'child_pid', 'child_stage'):
        state.pop(key, None)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--status', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare one bounded batch per dataset in the workspace; never invoke the DB loader.')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    if args.apply and args.prepare_only:
        parser.error('--apply and --prepare-only are mutually exclusive')
    config = read(args.config)
    runtime = local_path(config.get('runtime', 'full/runtime/auto-pipeline'))
    if args.status:
        print(json.dumps(read(runtime / 'state.json', {'status': 'not_started'}), indent=2))
        return 0
    if config.get('version') != 1:
        raise SystemExit('Unsupported pipeline configuration; no action taken.')
    lock = None
    writes = args.apply or args.prepare_only
    if writes:
        def interrupted(signum, frame):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        runtime.mkdir(parents=True, exist_ok=True)
        lock = (runtime / 'pipeline.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status': 'already_running'}))
            return 0
    state = read(runtime / 'state.json')
    try:
        result = cycle(config, runtime, state, writes, args.prepare_only)
        code = 0
    except Deferred as exc:
        result = {**state, 'status': 'retry_wait', 'reason': reason_code(str(exc), 'resource_deferred'), 'completed_at': now()}
        code = 0
    except ContentError as exc:
        result = {**state, 'status': 'needs_attention', 'reason': reason_code(str(exc), 'configuration_or_artifact_rejected'), 'completed_at': now()}
        code = 0
    except Exception as exc:
        result = {**state, 'status': 'failed', 'reason': 'unexpected_pipeline_error', 'error_class': type(exc).__name__, 'completed_at': now()}
        code = 1
    if writes:
        save(runtime / 'state.json', result)
    summary = {key: value for key, value in result.items() if key not in ('jobs', 'verified_sources')}
    print(json.dumps(summary, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
