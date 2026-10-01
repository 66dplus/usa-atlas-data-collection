#!/usr/bin/env python3
"""Rotate current gap queries across 52 catalogs with durable locks and cadence.

Successful bounded metadata discovery advances the cursor even when particular
providers need review. A completed run does not admit observations to production.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
RUNTIME = BASE / 'runtime'
PRIORITIES = ['data center', 'electricity', 'water', 'overdose', 'crime']
CYCLE_SECONDS = 21600
QUERY_SECONDS = 86400
FAILURE_COOLDOWN_SECONDS = 900
MAX_SHORT_FAILURES = 3


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, obj):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj, indent=2) + '\n')
    temp.replace(path)


def terminate_child(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=15)
    return process.returncode


def fail(state, path, error, code=1):
    count = state.get('consecutive_failures', 0) + 1
    cooldown = FAILURE_COOLDOWN_SECONDS if count < MAX_SHORT_FAILURES else CYCLE_SECONDS
    state.update(status='failed', completed_at=now(), error=error, exit_code=code,
                 consecutive_failures=count, retry_not_before_epoch=time.time() + cooldown,
                 failed_retry_policy='First two failures:15m; third and later:6h; cursor does not advance.')
    write(path, state)
    print('Discovery failed:', error, flush=True)
    return code or 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry-last-batch', action='store_true',
                        help='Operator-requested repair of previous batch across all52; preserve cursor.')
    options = parser.parse_args()
    repair = options.retry_last_batch
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = (RUNTIME / 'schedule.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('A scheduled nationwide discovery is already running.', flush=True)
        return 75
    state_path = RUNTIME / 'schedule-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    epoch = time.time()
    previous_queries = state.get('cycle_queries')
    if repair and (not isinstance(previous_queries, list) or not 1 <= len(previous_queries) <= 5):
        print('Cannot repair: no previous bounded batch in schedule state.', flush=True)
        return 2
    saved_cursor, saved_next_query = state.get('cursor', 0), state.get('next_query')
    if state.get('status') == 'running':
        # Lock is available, so the previous wrapper ended without a checkpoint.
        # Its process group is controlled by the systemd service; the worker lock
        # additionally prevents a duplicate if a manually started child survived.
        return fail(state, state_path, 'Previous wrapper interrupted before completion; retry after explicit cooldown.', 75)
    if not repair and state.get('status') == 'failed' and epoch < state.get('retry_not_before_epoch', 0):
        print('Failed run is in retry cooldown; no successful completion claimed.', flush=True)
        return 75
    if not repair and epoch < state.get('last_success_epoch', 0) + CYCLE_SECONDS:
        print('Regular six-hour cycle not due.', flush=True)
        return 0

    # Refresh primary+collected-alternative geography evidence before choosing jobs.
    try:
        generated = subprocess.run([sys.executable, str(BASE / 'build_queue.py')], cwd=BASE, timeout=120)
        if generated.returncode:
            return fail(state, state_path, 'queue generation failed', generated.returncode)
        queue_body = (BASE / 'search-queue.json').read_bytes()
        queue = json.loads(queue_body)
        queries = PRIORITIES + sorted({j['query'] for j in queue['jobs']} - set(PRIORITIES))
    except Exception as exc:
        return fail(state, state_path, f'queue generation/read: {type(exc).__name__}: {exc}')

    cursor_name = state.get('next_query')
    cursor = queries.index(cursor_name) if cursor_name in queries else state.get('cursor', 0) % len(queries)
    history = state.get('query_last_success_epoch', {})
    chosen, indices = (list(previous_queries), []) if repair else ([], [])
    for step in ([] if repair else range(len(queries))):
        index = (cursor + step) % len(queries)
        term = queries[index]
        if epoch - history.get(term, 0) >= QUERY_SECONDS:
            chosen.append(term)
            indices.append(index)
        if len(chosen) == 5:
            break
    if not chosen:
        state.update(status='waiting_query_cadence', last_checked_at=now(),
                     next_query_due_epoch=min(history.get(q, 0) + QUERY_SECONDS for q in queries))
        write(state_path, state)
        print('All current query groups are within their 24-hour interval.', flush=True)
        return 0

    args = [sys.executable, '-u', str(BASE / 'discover.py'), '--workers', '4',
            '--max-requests', '600', '--timeout', '25', '--page-size', '10', '--max-pages', '1',
            '--queries', *chosen]
    started_epoch = time.time()
    state.update(status='running', started_at=now(), last_attempt_epoch=started_epoch,
                 command=args, cycle_queries=chosen, cursor=cursor,
                 execution_mode='operator_retry_last_batch' if repair else 'scheduled_rotation',
                 repair_preserved_cursor=saved_cursor if repair else None,
                 repair_preserved_next_query=saved_next_query if repair else None,
                 queue_sha256=hashlib.sha256(queue_body).hexdigest(),
                 queued_query_groups=queue['query_groups'], rotating_query_groups=len(queries),
                 bootstrap_extra_queries=sorted(set(PRIORITIES) - {j['query'] for j in queue['jobs']}),
                 runner_sha256=hashlib.sha256((BASE / 'discover.py').read_bytes()).hexdigest())
    write(state_path, state)
    process = None
    try:
        process = subprocess.Popen(args, cwd=BASE, start_new_session=True)
        state['worker_pid'] = process.pid
        write(state_path, state)
        code = process.wait(timeout=3600)
    except BaseException as exc:
        child_code = terminate_child(process) if process is not None else None
        return fail(state, state_path,
                    f'{type(exc).__name__}: {exc}; child terminated and reaped, exit={child_code}', 124)

    try:
        manifest = json.loads((BASE / 'discovery-latest.json').read_text())
        completed_epoch = dt.datetime.fromisoformat(manifest['completed_at']).timestamp()
        run_started_epoch = dt.datetime.fromisoformat(manifest['started_at']).timestamp()
        completed = (code == 0 and manifest.get('stage') == 'complete_bounded_metadata_discovery'
                     and manifest.get('jurisdictions_planned') == 52
                     and manifest.get('priority_queries') == chosen
                     and manifest.get('runner_sha256') == state['runner_sha256']
                     and completed_epoch >= run_started_epoch >= started_epoch)
    except Exception as exc:
        return fail(state, state_path, f'missing/invalid current completion manifest: {exc}', code or 1)
    if not completed:
        return fail(state, state_path, 'child/current manifest did not prove this exact batch completed', code or 1)

    success_epoch = time.time()
    for term in chosen:
        history[term] = success_epoch
    next_cursor = saved_cursor if repair else (indices[-1] + 1) % len(queries)
    next_query = saved_next_query if repair else queries[next_cursor]
    state.update(status='complete', exit_code=code, completed_at=now(),
        last_success_epoch=success_epoch, consecutive_failures=0, retry_not_before_epoch=None,
        query_last_success_epoch=history, cursor=next_cursor, next_query=next_query,
        last_run=manifest.get('run'), actual_server_query_pages=manifest.get('actual_server_catalog_query_pages'),
        candidate_occurrences=manifest.get('candidate_occurrences'),
        errors_requiring_attention=manifest.get('errors_requiring_attention'),
        pagination_policy='First bounded page per query each cycle; next_offset preserved in result metadata, not resumed yet.')
    state.pop('error', None)
    write(state_path, state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
