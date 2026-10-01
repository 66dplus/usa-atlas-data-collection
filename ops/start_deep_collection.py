#!/usr/bin/env python3
"""Detached, locked supervisors for Census/CDC deep collection on this server."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / 'full/collect_deep.py'
DEFAULT_OUT = ROOT / 'full/runtime/deep-20260928'
PROVIDERS = ('acs-summary', 'cdc-places')


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        stat = Path(f'/proc/{pid}/stat')
        return not stat.exists() or stat.read_text().split()[2] != 'Z'
    except (OSError, ValueError):
        return False


def locked(path):
    handle = path.open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError:
        handle.close()
        return None


def retryable(reason):
    return reason.startswith(('network_', 'http_408', 'http_429', 'http_500', 'http_502',
                              'http_503', 'http_504', 'TimeoutError', 'ConnectionResetError',
                              'RemoteDisconnected', 'IncompleteRead', 'ConnectionAbortedError'))


def worker(out, provider):
    lock = locked(out / (provider + '.lock'))
    if lock is None:
        print('Supervisor already running:', provider, flush=True)
        return 3
    status_path = out / ('supervisor-' + provider + '.json')
    launch = read(out / ('launch-' + provider + '.json'))
    expected_hash = launch.get('collector_sha256') or sha(COLLECTOR)
    command = [sys.executable, '-u', str(COLLECTOR), 'collect', '--out', str(out),
               '--provider', provider, '--max-jobs', '19' if provider == 'acs-summary' else '1',
               '--timeout', '90', '--max-payload-gib', '4', '--geographies',
               'nation,state,place,county,tract,block_group' if provider == 'acs-summary' else 'tract']
    status = {'pid': os.getpid(), 'provider': provider, 'started_at': now(), 'command': command,
              'collector_sha256': expected_hash, 'status': 'starting', 'attempt': 0}
    print(json.dumps(status), flush=True)
    write(status_path, status)
    for attempt in range(1, 25):
        if sha(COLLECTOR) != expected_hash:
            status.update(status='failed_code_changed', updated_at=now())
            write(status_path, status)
            return 4
        status.update(status='running', attempt=attempt, updated_at=now())
        child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL)
        status['collector_pid'] = child.pid
        write(status_path, status)
        while child.poll() is None:
            status['updated_at'] = now()
            write(status_path, status)
            time.sleep(5)
        state = read(out / ('run-' + provider + '.json'))
        status.update(last_exit_code=child.returncode, updated_at=now(),
                      completed_jobs=state.get('completed_jobs', 0), planned_jobs=state.get('planned_jobs'))
        if child.returncode == 0 and state.get('status') == 'complete':
            status.update(status='complete', completed_at=now())
            write(status_path, status)
            print(json.dumps(status), flush=True)
            return 0
        failures = [job for job in state.get('jobs', {}).values() if job.get('status') == 'blocked_or_failed']
        reason = failures[-1].get('reason', '') if failures else 'collector_failed_without_retryable_manifest'
        status['reason'] = reason
        if child.returncode != 2 or not retryable(reason) or attempt == 24:
            status.update(status='failed', updated_at=now())
            write(status_path, status)
            print(json.dumps(status), flush=True)
            return child.returncode or 2
        delay = min(600, 15 * 2 ** min(attempt - 1, 6))
        status.update(status='retry_wait', retry_delay_seconds=delay, updated_at=now())
        write(status_path, status)
        print(json.dumps(status), flush=True)
        for _ in range(delay // 5):
            time.sleep(5)
            status['updated_at'] = now()
            write(status_path, status)
    return 2


def start(out):
    out.mkdir(parents=True, exist_ok=True)
    (out / '.gitignore').write_text('*\n!.gitignore\n')
    launch_lock = locked(out / 'launch.lock')
    if launch_lock is None:
        raise SystemExit('Another launch is active')
    subprocess.run([sys.executable, str(COLLECTOR), 'plan', '--out', str(out)], cwd=ROOT, check=True)
    result = {}
    for provider in PROVIDERS:
        previous = read(out / ('launch-' + provider + '.json'))
        supervisor = read(out / ('supervisor-' + provider + '.json'))
        if alive(supervisor.get('pid')) or alive(previous.get('pid')):
            result[provider] = {'status': 'already_running', 'pid': supervisor.get('pid') or previous.get('pid')}
            continue
        if supervisor.get('status') == 'complete':
            result[provider] = {'status': 'already_complete'}
            continue
        log_path = out / (provider + '.log')
        command = [sys.executable, '-u', str(Path(__file__).resolve()), 'worker', '--out', str(out), '--provider', provider]
        with log_path.open('ab', buffering=0) as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        record = {'pid': process.pid, 'provider': provider, 'launched_at': now(),
                  'collector_sha256': sha(COLLECTOR), 'command': command, 'log': str(log_path)}
        write(out / ('launch-' + provider + '.json'), record)
        result[provider] = record
    return result


def status(out):
    result = {}
    for provider in PROVIDERS:
        supervisor = read(out / ('supervisor-' + provider + '.json'))
        state = read(out / ('run-' + provider + '.json'))
        completed = {name: {'geography_counts': job['normalized']['geography_counts'],
                             'normalized_bytes': job['normalized']['bytes'],
                             'raw_bytes': job['raw']['bytes']}
                     for name, job in state.get('jobs', {}).items() if job.get('status') == 'complete'}
        result[provider] = {'supervisor': supervisor, 'supervisor_alive': alive(supervisor.get('pid')),
                            'collector_alive': alive(supervisor.get('collector_pid')),
                            'status': state.get('status'), 'completed_jobs': state.get('completed_jobs', 0),
                            'planned_jobs': state.get('planned_jobs'), 'active_job': state.get('active_job'),
                            'completed': completed}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['start', 'status', 'worker'])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--provider', choices=PROVIDERS)
    args = parser.parse_args()
    if args.command == 'worker':
        if not args.provider:
            parser.error('--provider is required for worker')
        return worker(args.out.resolve(), args.provider)
    value = start(args.out.resolve()) if args.command == 'start' else status(args.out.resolve())
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
