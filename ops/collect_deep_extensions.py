#!/usr/bin/env python3
"""Queue two explicit native-table alternatives after the primary ACS run finishes.

The unchanged production contract remains authoritative. These are separate research
variants, with numerical equivalence checked on common county/tract geographies.
"""
from __future__ import annotations
import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'full'))
sys.path.insert(0, str(ROOT / 'ops'))
import collect_deep as deep
from start_deep_collection import alive, retryable

PRIMARY = ROOT / 'full/runtime/deep-20260928'
GEO = {'nation', 'state', 'county', 'place', 'tract', 'block_group'}
METRICS = [
    {'catalog_field_id': '02.08', 'table': 'B17021', 'metric': 'poverty_population',
     'universe': 'Population for whom poverty status is determined',
     'numerator': 'B17021_002', 'denominator': 'B17021_001',
     'legacy_table': 'B17001', 'legacy_numerator': 'B17001_002', 'legacy_denominator': 'B17001_001',
     'variables': ['B17021_001', 'B17021_002'],
     'identity': 'Native number of people below poverty threshold; share requires numerator / denominator and ACS MOE propagation.'},
    {'catalog_field_id': '01.05', 'table': 'B05012', 'metric': 'foreign_born_population',
     'universe': 'Total population in the United States',
     'numerator': 'B05012_003', 'denominator': 'B05012_001',
     'legacy_table': 'B05002', 'legacy_numerator': 'B05002_013', 'legacy_denominator': 'B05002_001',
     'variables': ['B05012_001', 'B05012_002', 'B05012_003'],
     'identity': 'Native foreign-born count and total population; does not reproduce the full birthplace/citizenship breakdown in B05002.'},
]


def jobs():
    return [{'id': 'acs-summary-' + item['table'], 'provider': 'acs-summary', 'table': item['table'],
             'url': deep.SF_BASE + f"acsdt5y2024-{item['table'].lower()}.dat",
             'variables': item['variables'], 'release': '2024-acs-acs5',
             'native_geographies_only': True, 'metric_identity': item,
             'extension_script_sha256': deep.digest(Path(__file__))} for item in METRICS]


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def compare(primary, out):
    checks = []
    for item in METRICS:
        original = primary / 'data' / ('acs-summary-' + item['legacy_table'] + '.csv.gz')
        candidate = out / 'data' / ('acs-summary-' + item['table'] + '.csv.gz')
        mapping = {item['legacy_numerator']: item['numerator'], item['legacy_denominator']: item['denominator']}
        original_values = {}
        columns = ['estimate', 'moe', 'estimate_status', 'moe_status', 'estimate_code', 'moe_code']
        with gzip.open(original, 'rt') as f:
            for row in csv.DictReader(f):
                if row['geo_type'] in {'county', 'tract'} and row['variable'] in mapping:
                    key = row['geo_type'], row['geo_id'], mapping[row['variable']]
                    original_values[key] = tuple(row[column] for column in columns)
        matches, mismatches, unmatched, examples = 0, 0, 0, []
        with gzip.open(candidate, 'rt') as f:
            for row in csv.DictReader(f):
                if row['geo_type'] not in {'county', 'tract'} or row['variable'] not in mapping.values():
                    continue
                key = row['geo_type'], row['geo_id'], row['variable']
                if key not in original_values:
                    unmatched += 1
                elif tuple(row[column] for column in columns) == original_values[key]:
                    matches += 1
                else:
                    mismatches += 1
                    if len(examples) < 10:
                        examples.append({'key': key, 'legacy': original_values[key], 'candidate': [row[c] for c in columns]})
        checks.append({'catalog_field_id': item['catalog_field_id'], 'candidate_table': item['table'],
                       'legacy_table': item['legacy_table'], 'matching_common_county_tract_pairs': matches,
                       'mismatching_common_county_tract_pairs': mismatches, 'candidate_pairs_without_legacy_match': unmatched,
                       'mismatch_examples': examples, 'production_admitted': False})
    deep.save(out / 'metric-equivalence.json', checks)
    return checks


def worker(primary, out, expected_collector_hash):
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / 'extensions.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 3
    status_path = out / 'supervisor.json'
    status = {'pid': os.getpid(), 'status': 'waiting_for_primary', 'started_at': deep.now(),
              'primary': str(primary), 'collector_sha256': expected_collector_hash,
              'extension_script_sha256': deep.digest(Path(__file__))}
    while True:
        status['updated_at'] = deep.now()
        deep.save(status_path, status)
        if deep.digest(ROOT / 'full/collect_deep.py') != expected_collector_hash:
            status.update(status='failed_collector_changed', updated_at=deep.now())
            deep.save(status_path, status)
            return 4
        state = read(primary / 'run-acs-summary.json')
        if state.get('status') == 'complete' and state.get('completed_jobs') == 19:
            break
        supervisor = read(primary / 'supervisor-acs-summary.json')
        if supervisor.get('status') == 'failed':
            status.update(status='blocked_primary_failed', reason=supervisor.get('reason'))
            deep.save(status_path, status)
            return 2
        time.sleep(10)
    # Plan is overridden only inside this independent worker process. Both script
    # hashes are recorded; no running collector file or production contract changes.
    deep.plan = jobs
    deep.save(out / 'extension-metrics.json', METRICS)
    deep.save(out / 'collection-plan.json', {'jobs': jobs(), 'production_admission': False})
    for attempt in range(1, 25):
        status.update(status='running', attempt=attempt, updated_at=deep.now())
        deep.save(status_path, status)
        result = deep.collect(out, 'acs-summary', 2, 90, GEO, 4 * 1024 ** 3)
        print(json.dumps(result), flush=True)
        if result.get('status') == 'complete':
            checks = compare(primary, out)
            status.update(status='complete', completed_at=deep.now(), metric_checks=checks)
            deep.save(status_path, status)
            return 0
        reason = result.get('reason', '')
        if not retryable(reason) or attempt == 24:
            status.update(status='failed', reason=reason, updated_at=deep.now())
            deep.save(status_path, status)
            return 2
        delay = min(600, 15 * 2 ** min(attempt - 1, 6))
        status.update(status='retry_wait', reason=reason, retry_delay_seconds=delay, updated_at=deep.now())
        deep.save(status_path, status)
        time.sleep(delay)
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['start', 'worker', 'status'])
    parser.add_argument('--primary', type=Path, default=PRIMARY)
    parser.add_argument('--out', type=Path, default=PRIMARY / 'extensions')
    parser.add_argument('--collector-sha256')
    args = parser.parse_args()
    primary, out = args.primary.resolve(), args.out.resolve()
    if args.command == 'status':
        status = read(out / 'supervisor.json')
        print(json.dumps({**status, 'alive': alive(status.get('pid')), 'run': read(out / 'run-acs-summary.json')}, indent=2))
        return 0
    if args.command == 'worker':
        if not args.collector_sha256:
            parser.error('--collector-sha256 required')
        return worker(primary, out, args.collector_sha256)
    out.mkdir(parents=True, exist_ok=True)
    previous = read(out / 'launch.json')
    if alive(previous.get('pid')):
        print(json.dumps({'status': 'already_running', **previous}, indent=2))
        return 0
    if read(out / 'supervisor.json').get('status') == 'complete':
        print(json.dumps({'status': 'already_complete'}))
        return 0
    command = [sys.executable, '-u', str(Path(__file__).resolve()), 'worker', '--primary', str(primary),
               '--out', str(out), '--collector-sha256', deep.digest(ROOT / 'full/collect_deep.py')]
    with (out / 'extensions.log').open('ab', buffering=0) as log:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    launch = {'pid': process.pid, 'command': command, 'started_at': deep.now()}
    deep.save(out / 'launch.json', launch)
    print(json.dumps(launch, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
