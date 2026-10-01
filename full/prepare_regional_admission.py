#!/usr/bin/env python3
"""Prepare reviewed regional/public source records for the automatic DB loader.

Preserves source rows and suppression tokens. This adapter never converts a
building, tax bracket, search trend or permit into an unrelated catalog metric.
Only registered completed collectors are discovered; catalog search hits are
not executable collection or admission instructions.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()
VERSION = 'regional-source-records-v1'
LOCAL_IDS = ('ca-dwr-bg-income-2023', 'ca-dwr-bg-water-vulnerability-2024',
             'dc-mpd-crime-bg-2025', 'dc-mpd-crime-bg-2026',
             'loudoun-dc-building-records', 'ny-county-income-tax-1999-2014')
REGIONAL_IDS = ('tx-reservoir-current', 'co-well-permits-county-status',
                'wa-electric-vehicles-tract-type')
PUBLIC_IDS = ('susb-receipts-2022', 'susb-large-receipts-2022',
              'irs-state-agi-2023', 'irs-county-agi-2023', 'bea-metro-rpp',
              'epa-monitors-2025')
REFERENCE_IDS = ('irs-wealth-2019', 'lbnl-energy-2024',
                 'loudoun-datacenters-2026-03-01', 'ubs-national-wealth')
FLOOR = 12 * 1024**3


class PreparationError(ValueError):
    pass


class PreparationDeferred(PreparationError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe(path):
    path = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise PreparationError('path_outside_repository')
    return path


def relative(path):
    return str(safe(path).relative_to(ROOT))


def read(path):
    return json.loads(safe(path).read_text())


def timestamp(value):
    if not isinstance(value, str):
        raise PreparationError('missing_snapshot_timestamp')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        value += 'T00:00:00+00:00'
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise PreparationError('timestamp_without_timezone')
    return dt.astimezone(timezone.utc).isoformat()


def bound(path, expected=None):
    path = safe(path)
    actual = sha(path)
    if expected is not None and actual != expected:
        raise PreparationError('source_file_hash_mismatch:' + relative(path))
    return {'path': relative(path), 'sha256': actual}


def candidate(dataset_key, source, release, snapshot_at, manifest, payload, fmt,
              rows, inputs, metadata):
    if not isinstance(rows, int) or rows < 0:
        raise PreparationError('invalid_expected_source_rows')
    unique = {i['path']: i for i in [bound(manifest), *inputs]}
    result = {
        'dataset_id': dataset_key, 'dataset_key': dataset_key, 'kind': 'records',
        'source': source, 'source_release': str(release),
        'snapshot_at': timestamp(snapshot_at), 'source_manifest': bound(manifest),
        'payload_path': relative(payload), 'payload_format': fmt,
        'total_input_rows': rows, 'inputs': sorted(unique.values(), key=lambda i: i['path']),
        'metadata': metadata, 'adapter_version': VERSION,
        'adapter': {'path': relative(HERE), 'sha256': sha(HERE)},
    }
    result['source_manifest_path'] = result['source_manifest']['path']
    result['source_manifest_sha256'] = result['source_manifest']['sha256']
    result['source_artifacts'] = result['inputs']
    result['revision'] = digest({
        'dataset_key': dataset_key, 'source': source, 'release': str(release),
        'snapshot_at': result['snapshot_at'], 'format': fmt, 'rows': rows,
        'input_hashes': sorted(i['sha256'] for i in result['inputs']),
        'metadata': metadata, 'adapter_version': VERSION,
        'adapter_sha256': result['adapter']['sha256'],
    })
    return result


def local_candidate(key):
    base = ROOT / 'research/2026-09-28/local-portals'
    path = base / 'manifests' / (key + '.json')
    m = read(path)
    if m.get('status') != 'source_collected' or m.get('complete') is not True:
        raise PreparationError('source_not_complete')
    payload = safe(base / m['normalized_path'])
    receipt_path = safe(base / m['raw_requests_path'])
    inputs = [bound(payload, m['normalized_file_sha256']), bound(receipt_path)]
    for receipt in read(receipt_path):
        inputs.append(bound(base / receipt['raw_path'], receipt['file_sha256']))
    return candidate('local:' + key, 'local_portals', m.get('release', key),
                     m['retrieved_at'], path, payload, 'jsonl', m['rows'], inputs,
                     {k: m.get(k) for k in ('endpoint', 'geo_type', 'boundary_vintage',
                      'coverage', 'release', 'limitations', 'checks', 'review_status')})


def regional_candidate(key):
    base = ROOT / 'research/2026-09-29/regional-expansion'
    latest = read(base / 'latest.json')
    if latest.get('status') != 'complete':
        raise PreparationError('regional_cycle_not_complete')
    summary = safe(base / latest['summary'])
    run = summary.parent
    report = read(summary)
    job = report['jobs'][key]
    if job.get('status') != 'complete':
        raise PreparationError('regional_job_not_complete')
    path = safe(run / job['manifest'])
    m = read(path)
    if m.get('status') != 'complete':
        raise PreparationError('regional_manifest_not_complete')
    payload = safe(run / m['normalized']['path'])
    inputs = [bound(payload, m['normalized']['sha256'])]
    for request in m.get('requests', []):
        inputs.append(bound(run / request['path'], request['gzip_sha256']))
    return candidate('regional:' + key, 'regional_portals', key,
                     m['retrieved_at'], path, payload, 'jsonl', m['normalized']['rows'], inputs,
                     {k: m.get(k) for k in ('jurisdiction', 'owner', 'name', 'official_provenance',
                      'geo_type', 'boundary_vintage', 'limitations', 'checks', 'bindings')})


def public_candidate(key):
    base = ROOT / 'full/runtime/public-20260928'
    path = base / 'manifest.json'
    m = read(path)['jobs'][key]
    if m.get('status') != 'source_tables_collected':
        raise PreparationError('public_source_not_complete')
    table = m['table']
    payload = safe(base / table['path'])
    return candidate('public:' + key, 'public_bulk', m['period'], m['raw']['retrieved_at'],
                     path, payload, 'csv', table['table_rows_including_preserved_headers_when_nested'],
                     [bound(payload, table['sha256']), bound(base / m['raw']['path'], m['raw']['sha256'])],
                     {'source_url': m['url'], 'native_geography': m['geo'],
                      'representation': table['representation'],
                      'suppression_policy': table['suppression_policy'],
                      'metric_admission': False,
                      'meaning': 'Original source table cells; headers and missing/suppressed tokens preserved.'})


def pwc_candidate():
    base = ROOT / 'research/2026-09-29/data-center-expansion'
    latest = read(base / 'latest.json')
    if latest.get('status') != 'collected_verified_source_snapshot':
        raise PreparationError('pwc_not_complete')
    run = safe(base / latest['run'])
    path = run / 'manifest.json'
    m = read(path)
    inputs = [bound(base / a['path'], a['sha256']) for a in m['artifacts']]
    return candidate('local:pwc-data-center-buildings', 'pwc_planning', 'current_buildings',
                     m['completed_at'], path, run / 'buildings.normalized.json', 'json_array',
                     m['actual_building_records'], inputs,
                     {k: m.get(k) for k in ('source_url', 'source_publisher', 'publisher_evidence',
                      'declared_geographic_scope', 'native_geography', 'geometry_crs', 'unit',
                      'status_semantics', 'source_copyright', 'license_review', 'privacy_projection')})


def reference_candidate(key):
    base = ROOT / 'research/2026-09-28/new-topics'
    path = base / 'collection-manifest.json'
    m = read(path)
    artifacts = {a['path']: a for a in m['artifacts']}
    record = artifacts['normalized/' + key + '.csv']
    payload = safe(base / record['path'])
    # These explicitly identified research transcriptions are retained as source
    # references, never promoted to a canonical observation or original download.
    inputs = [bound(base / a['path'], a['sha256']) for a in m['artifacts']]
    return candidate('reference:' + key, 'research_references', key, m['retrieved_date'],
                     path, payload, 'csv', record['row_count'], inputs,
                     {'representation': 'research_extraction_or_transcription',
                      'original_provider_bytes_available': False, 'metric_admission': False,
                      'limitations': [m['note'], 'Research reference; original provider bytes were not downloaded.']})


def trends_candidate():
    base = ROOT / 'research/2026-09-29/demand-signals'
    m = read(base / 'latest.json')
    if m.get('status') != 'collected_public_trending_snapshot':
        raise PreparationError('trends_not_complete')
    run = safe(base / m['run'])
    path = run / 'manifest.json'
    manifest = read(path)
    return candidate('demand:google-trends-us-rss', 'google_trends_rss', 'trending_sample',
                     m['completed_at'], path, run / 'trends.normalized.json', 'json_array',
                     m['records'], [bound(run / a['path'], a['sha256']) for a in manifest['files']],
                     {k: m.get(k) for k in ('source_url', 'source_owner', 'source_geo', 'caveats',
                      'sample_complete_market_demand', 'monthly_keyword_volume_available', 'supplied_traffic_field')})


def discover():
    jobs = [(f'local:{k}', local_candidate, (k,)) for k in LOCAL_IDS]
    jobs += [(f'regional:{k}', regional_candidate, (k,)) for k in REGIONAL_IDS]
    jobs += [(f'public:{k}', public_candidate, (k,)) for k in PUBLIC_IDS]
    jobs += [(f'reference:{k}', reference_candidate, (k,)) for k in REFERENCE_IDS]
    jobs += [('local:pwc-data-center-buildings', pwc_candidate, ()),
             ('demand:google-trends-us-rss', trends_candidate, ())]
    candidates, blocked = [], []
    for key, fn, args in jobs:
        try:
            candidates.append(fn(*args))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            blocked.append({'dataset_id': key, 'reason': str(exc) if isinstance(exc, PreparationError)
                            else type(exc).__name__})
    return {'status': 'complete', 'candidates': candidates, 'blocked': blocked,
            'registered_datasets': len(jobs), 'unknown_catalog_candidates_admitted': False}


def open_text(path):
    return gzip.open(path, 'rt', encoding='utf-8-sig', newline='') if path.suffix == '.gz' \
        else path.open('r', encoding='utf-8-sig', newline='')


def rows(candidate):
    path = safe(candidate['payload_path'])
    fmt = candidate['payload_format']
    with open_text(path) as stream:
        if fmt == 'jsonl':
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        elif fmt == 'json_array':
            if path.stat().st_size > 32 * 1024**2:
                raise PreparationError('json_array_exceeds_memory_bound')
            data = json.load(stream)
            if isinstance(data, dict):
                data = data.get('records')
            if not isinstance(data, list):
                raise PreparationError('expected_record_array')
            yield from data
        elif fmt == 'csv':
            table = csv.reader(stream)
            header = next(table)
            for index, cells in enumerate(table, 1):
                if len(cells) != len(header):
                    raise PreparationError('ragged_source_csv')
                if 'cells_json' in header:
                    payload = dict(zip(header, cells))
                    payload['cells'] = json.loads(payload.pop('cells_json'))
                    yield payload
                else:
                    yield {'source_row': index, 'cells': cells}
        else:
            raise PreparationError('unsupported_payload_format')


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')
    os.chmod(temp, 0o600)
    temp.replace(path)


def prepare(candidate_path, out, max_rows, cursor_text):
    selected = read(candidate_path)
    # A caller cannot turn this adapter into an arbitrary file importer by
    # editing candidate JSON. Re-derive the registered, bound source candidate.
    current = {c['dataset_id']: c for c in discover()['candidates']}.get(selected.get('dataset_id'))
    if current is None or current != selected:
        raise PreparationError('candidate_superseded_or_unregistered')
    if not 1 <= max_rows <= 250000:
        raise PreparationError('max_rows_out_of_bounds')
    cursor = json.loads(cursor_text) if cursor_text else None
    if cursor is not None and (not isinstance(cursor, dict) or cursor.get('revision') != selected['revision']):
        raise PreparationError('cursor_binding_mismatch')
    start = cursor.get('next_row', 0) if cursor else 0
    total = selected['total_input_rows']
    if not isinstance(start, int) or not 0 <= start <= total:
        raise PreparationError('cursor_range_invalid')
    stop = min(total, start + max_rows)
    out = safe(out)
    out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out).free < FLOOR + 512 * 1024**2:
        raise PreparationDeferred('insufficient_preparation_disk_headroom')
    with (out / '.prepare.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        partition_id = digest({'snapshot_id': selected['revision'], 'start': start, 'stop': stop})
        temp = out / (partition_id + '.records.tmp')
        count = 0
        uncompressed = 0
        try:
            with temp.open('wb') as raw:
                with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as dest:
                    # Read through the full small source to verify declared counts
                    # even when a caller chooses a smaller first partition.
                    for index, payload in enumerate(rows(selected)):
                        count += 1
                        if not isinstance(payload, dict):
                            raise PreparationError('source_record_not_object')
                        if not start <= index < stop:
                            continue
                        line = (canonical({'record_key': str(index), 'kind': 'source_record', 'payload': payload}) + '\n').encode()
                        if len(line) > 1024**2:
                            raise PreparationError('source_record_too_large')
                        dest.write(line)
                        uncompressed += len(line)
                        if uncompressed > 512 * 1024**2:
                            raise PreparationError('batch_output_exceeds_byte_bound')
            if count != total:
                raise PreparationError('source_row_count_mismatch')
            for item in selected['inputs']:
                bound(item['path'], item['sha256'])
            payload_sha = sha(temp)
            batch_id = digest({'snapshot_id': selected['revision'], 'start': start, 'stop': stop,
                               'payload_sha256': payload_sha, 'rows': stop - start})
            target = out / (batch_id + '.records.jsonl.gz')
            manifest_path = out / 'admission-manifest.json'
            if manifest_path.exists() and read(manifest_path).get('batch_id') != batch_id:
                raise PreparationError('output_directory_contains_another_batch')
            os.chmod(temp, 0o600)
            temp.replace(target)
            scope = {'type': 'input_row_range', 'start_row': start, 'end_row_exclusive': stop,
                     'total_input_rows': total, 'source_manifest': selected['source_manifest'],
                     'representation': 'source_records_not_canonical_metrics', **selected['metadata']}
            if selected['payload_format'] == 'csv':
                with open_text(safe(selected['payload_path'])) as stream:
                    scope['table_columns'] = next(csv.reader(stream))
            def manifest_binding(item):
                return {**item, 'path': os.path.relpath(safe(item['path']), out)}
            manifest = {
                'format': 'usa_atlas_admission_v1', 'status': 'complete', 'batch_id': batch_id,
                'dataset_key': selected['dataset_key'], 'kind': 'records', 'source': selected['source'],
                'source_release': selected['source_release'], 'snapshot_id': selected['revision'],
                'snapshot_at': selected['snapshot_at'], 'adapter_version': VERSION,
                'adapter': manifest_binding(selected['adapter']), 'scope': scope, 'contract': None,
                'completeness': {'complete': True, 'basis': 'registered completed collector; bound inputs; all source rows parsed; source row count matched'},
                'inputs': [manifest_binding(item) for item in selected['inputs']], 'observations': None, 'quality': None,
                'records': {'path': target.name, 'sha256': payload_sha, 'rows': stop - start,
                            'bytes': target.stat().st_size, 'uncompressed_bytes': uncompressed},
            }
            atomic_json(manifest_path, manifest)
            result = {'status': 'ready', 'manifest': str(manifest_path), 'prepared_rows': stop - start,
                      'next_cursor': {'revision': selected['revision'], 'next_row': stop} if stop < total else None,
                      'complete': stop == total}
            atomic_json(out / 'prepare-result.json', result)
            return result
        finally:
            if temp.exists():
                temp.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('discover')
    plan.add_argument('--json', action='store_true')
    build = sub.add_parser('prepare')
    build.add_argument('--candidate', required=True, type=Path)
    build.add_argument('--out', required=True, type=Path)
    build.add_argument('--max-rows', type=int, default=250000)
    build.add_argument('--cursor', default='null')
    args = parser.parse_args()
    try:
        result = discover() if args.command == 'discover' else prepare(args.candidate, args.out, args.max_rows, args.cursor)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (PreparationError, OSError, ValueError, KeyError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, PreparationError) else type(exc).__name__
        transient = isinstance(exc, (PreparationDeferred, OSError))
        result = {'status': 'transient_failure' if transient else 'quarantine', 'reason': reason}
        if transient:
            result['retry_after_seconds'] = 900
        if args.command == 'prepare':
            try:
                output = safe(args.out)
                if output.is_dir():
                    atomic_json(output / 'prepare-result.json', result)
            except (OSError, PreparationError):
                pass
        print(json.dumps(result), flush=True)
        return 75 if transient else 65


if __name__ == '__main__':
    raise SystemExit(main())
