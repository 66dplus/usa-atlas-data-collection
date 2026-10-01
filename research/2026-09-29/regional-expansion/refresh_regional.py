#!/usr/bin/env python3
"""One UTC-date snapshot per day; resume within a date, refresh on the next date."""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def save(value):
    tmp = HERE / 'latest.json.tmp'
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(HERE / 'latest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default=datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    args = parser.parse_args()
    stamp = datetime.strptime(args.date, '%Y-%m-%d').strftime('%Y-%m-%d')
    (HERE / 'runtime').mkdir(exist_ok=True)
    with (HERE / 'runtime/refresh.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = HERE / 'runs' / stamp
        (out / 'runtime').mkdir(parents=True, exist_ok=True)
        command = [sys.executable, '-u', str(HERE / 'collect_regional.py'), '--out', str(out)]
        status = {'pid': os.getpid(), 'date': stamp, 'status': 'running',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'summary': str((out / 'collection-summary.json').relative_to(HERE)),
            'log': str((out / 'runtime/collector.log').relative_to(HERE)),
            'collector_sha256': hashlib.sha256((HERE / 'collect_regional.py').read_bytes()).hexdigest(),
            'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        save(status)
        try:
            with (out / 'runtime/collector.log').open('a') as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=1500)
            code = completed.returncode
            summary = json.loads((out / 'collection-summary.json').read_text())
            if code == 0 and (summary.get('status') != 'complete' or len(summary.get('jobs', {})) != 3):
                code = 2
            status.update(status='complete' if code == 0 else 'failed', exit_code=code,
                          job_statuses={k: v.get('status') for k, v in summary.get('jobs', {}).items()})
        except Exception as error:
            code = 2
            status.update(status='failed', exit_code=code, error=type(error).__name__ + ':' + str(error))
        status['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(status)
        print(json.dumps(status, indent=2))
        return code


if __name__ == '__main__':
    raise SystemExit(main())
