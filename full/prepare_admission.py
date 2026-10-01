#!/usr/bin/env python3
"""Prepare bounded, immutable ACS/CDC admission bundles; never connect to a DB."""
from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / 'full'
DEFAULT_RUNTIME = FULL / 'runtime/deep-20260928'
CONTRACT = FULL / 'field-contract.json'
VERSION = 'national_deep_v1'
OUTPUT_LIMIT = 250000
FOOD = {'08.01', '08.02', '08.03', '08.06', '09.01', '09.02', '09.03'}
ACS_COLUMNS = ['geo_type', 'geo_id', 'variable', 'estimate', 'moe', 'estimate_status', 'moe_status',
               'estimate_code', 'moe_code', 'estimate_annotation', 'moe_annotation', 'annotation_status']
CDC_COLUMNS = ['geo_type', 'geo_id', 'catalog_field_id', 'variant', 'data_year', 'estimate',
               'ci_low', 'ci_high', 'estimate_status', 'ci_status', 'raw_ci']
WIRE = {'geo_id', 'geo_type', 'year', 'field_id', 'catalog_field_id', 'value', 'unit', 'source',
        'source_release', 'source_url', 'methodology_note', 'retrieved_at'}
QUALITY_WIRE = (WIRE - {'value'}) | {'quality_status', 'raw_value', 'annotation'}
GEO_LENGTH = {'nation': 2, 'state': 2, 'county': 5, 'place': 7, 'tract': 11, 'block_group': 12}
STATUS_MAP = {'missing': 'missing', 'not_collected': 'missing',
              'suppressed_insufficient_sample': 'suppressed', 'moe_insufficient_sample': 'suppressed',
              'not_applicable_or_unavailable': 'not_applicable', 'estimate_not_computable': 'invalid',
              'moe_controlled_estimate': 'sentinel', 'moe_open_ended_median': 'sentinel',
              'unknown_negative_sentinel': 'sentinel', 'unparsed_source_token': 'invalid'}
EXTENSIONS = {'B17021': ('02.08', ['B17021_001', 'B17021_002']),
              'B05012': ('01.05', ['B05012_001', 'B05012_002', 'B05012_003'])}


class Quarantine(ValueError):
    pass


HANDLED_ERRORS = (Quarantine, KeyError, ValueError, TypeError, AttributeError, StopIteration,
                  csv.Error, OSError, EOFError)


def failure(error):
    transient = isinstance(error, (OSError, EOFError))
    reason = str(error).split(':', 1)[0] if isinstance(error, Quarantine) else ''
    if not re.fullmatch(r'[a-z][a-z0-9_]*', reason):
        reason = 'artifact_io_error' if transient else 'invalid_source_or_request_shape'
    return {'status': 'transient_failure' if transient else 'quarantine', 'reason': reason,
            'error': type(error).__name__ + ':' + str(error),
            'retry_after_seconds': 300 if transient else 0}


def save_failure(out, result):
    """Called only while holding the batch lock; never replace a ready bundle."""
    path = out / 'prepare-result.json'
    if path.exists():
        try:
            previous = read(path)
        except HANDLED_ERRORS:
            return
        if not isinstance(previous, dict) or previous.get('status') == 'ready':
            return
    atomic(path, result)


def now():
    return datetime.now(timezone.utc).isoformat()


def document_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def within_repo(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise Quarantine('path_outside_repository:' + str(path))
    return path


def artifact(path, expected_hash=None, expected_bytes=None):
    path = within_repo(path)
    actual = {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}
    if expected_hash is not None and actual['sha256'] != expected_hash:
        raise Quarantine('input_hash_mismatch:' + str(path))
    if expected_bytes is not None and actual['bytes'] != expected_bytes:
        raise Quarantine('input_size_mismatch:' + str(path))
    return actual


def check_inputs(items):
    for item in items:
        artifact(item['path'], item['sha256'], item.get('bytes'))


def candidate_for(manifest_path, job_id, extension=False):
    manifest_path = within_repo(manifest_path)
    run = read(manifest_path)
    if run.get('status') != 'complete' or run.get('completed_jobs') != run.get('planned_jobs'):
        raise Quarantine('collection_not_complete:' + str(manifest_path))
    job = run.get('jobs', {}).get(job_id)
    if not job or job.get('status') != 'complete':
        raise Quarantine('job_not_complete:' + job_id)
    contract_artifact = artifact(CONTRACT, run['bindings']['contract_sha256'])
    collector = artifact(FULL / 'collect_deep.py', run['bindings']['collector_sha256'])
    manifest_artifact = artifact(manifest_path)
    inputs = [manifest_artifact, contract_artifact, collector]
    for name in ['raw', 'normalized']:
        inputs.append(artifact(manifest_path.parent / job[name]['path'], job[name]['sha256'], job[name]['bytes']))
    is_acs = job_id.startswith('acs-summary-')
    if is_acs:
        table = job_id.removeprefix('acs-summary-')
        if not re.fullmatch(r'B\d{5}', table):
            raise Quarantine('unknown_acs_table')
        if job['release'] != '2024-acs-acs5' or job['data_period'] != '2020-2024':
            raise Quarantine('unsupported_acs_release')
        source = 'census_acs'
        metadata_root = manifest_path.parent.parent if extension else manifest_path.parent
        for name in ['variable-dictionary.json', 'table-universes-and-restrictions.json']:
            inputs.append(artifact(metadata_root / 'metadata' / name))
        if extension:
            if table not in EXTENSIONS:
                raise Quarantine('unknown_extension_table')
            inputs.append(artifact(manifest_path.parent / 'extension-metrics.json'))
            inputs.append(artifact(manifest_path.parent / 'metric-equivalence.json'))
            checks = read(manifest_path.parent / 'metric-equivalence.json')
            check = next((r for r in checks if r['candidate_table'] == table), None)
            if not check or check.get('mismatching_common_county_tract_pairs') != 0 or check.get('candidate_pairs_without_legacy_match') != 0:
                raise Quarantine('extension_equivalence_unconfirmed')
    else:
        if job_id != 'cdc-places-2025-tract' or job['release'] != 'PLACES-2025' or job['data_period'] != '2023':
            raise Quarantine('unsupported_cdc_job')
        source, table = 'cdc_places', 'PLACES-2025-tract-crude'
    dataset_id = f'{source}/{job["release"]}/{table}'
    candidate = {'dataset_id': dataset_id, 'source': source, 'source_release': job['release'],
        'source_manifest_path': str(manifest_path), 'source_manifest_sha256': manifest_artifact['sha256'],
        'source_artifacts': inputs, 'job_id': job_id, 'extension': extension,
        'snapshot_at': job['raw']['retrieved_at'], 'input_rows': sum(job['normalized']['rows_by_geography'].values()),
        'geography_vintage': job['geography_vintage'], 'data_period': job['data_period'],
        'native_geography_counts': job['normalized']['geography_counts'], 'adapter': VERSION}
    candidate['revision'] = document_hash(candidate)
    return candidate


def discover(runtime):
    candidates, blocked = [], []
    for relative, extension in [('run-acs-summary.json', False), ('run-cdc-places.json', False),
                                ('extensions/run-acs-summary.json', True)]:
        path = runtime / relative
        try:
            run = read(path)
            if not isinstance(run, dict) or not isinstance(run.get('jobs'), dict) or not run['jobs']:
                raise Quarantine('collection_manifest_jobs_invalid')
            job_ids = sorted(run['jobs'])
        except HANDLED_ERRORS as error:
            blocked.append({'dataset_id': relative, 'source_manifest_path': str(path), **failure(error)})
            continue
        for job_id in job_ids:
            try:
                candidates.append(candidate_for(path, job_id, extension))
            except HANDLED_ERRORS as error:
                blocked.append({'dataset_id': job_id, 'source_manifest_path': str(path), **failure(error)})
    return {'adapter': VERSION, 'candidates': candidates, 'blocked': blocked}


def mappings(candidate):
    contract = read(CONTRACT)
    parents, catalog = defaultdict(set), {r['field_id']: r for r in contract}
    if len(catalog) != 81:
        raise Quarantine('contract_catalog_count')
    if candidate['source'] == 'census_acs':
        table = candidate['job_id'].removeprefix('acs-summary-')
        if candidate['extension']:
            parent, bases = EXTENSIONS[table]
            for base in bases:
                for suffix in ['E', 'M']:
                    parents[base + suffix].add(parent)
        else:
            for row in contract:
                if row['field_id'] in FOOD or row['rate_limit_profile'] != 'census_acs':
                    continue
                for variable in row['source_variables']:
                    if not re.fullmatch(r'B\d{5}_\d{3}[EM]', variable):
                        raise Quarantine('nonconcrete_contract_variable')
                    if variable.startswith(table + '_'):
                        parents[variable].add(row['field_id'])
        if not parents:
            raise Quarantine('table_not_bound_to_catalog')
        for values in parents.values():
            for parent in values:
                if parent in FOOD or catalog[parent]['planned_state'] != 'run_now' or catalog[parent]['rate_limit_profile'] != 'census_acs':
                    raise Quarantine('nonrunnable_or_food_mapping')
    else:
        for parent in ['05.14', '05.15', '05.16']:
            if catalog[parent]['planned_state'] != 'run_now' or catalog[parent]['rate_limit_profile'] != 'cdc_places':
                raise Quarantine('cdc_contract_mismatch')
    return parents


def geography(row):
    kind, code = row['geo_type'], row['geo_id']
    if kind not in GEO_LENGTH or len(code) != GEO_LENGTH[kind]:
        raise Quarantine('geography_width')
    if (kind == 'nation' and code != 'US') or (kind != 'nation' and not code.isdigit()):
        raise Quarantine('geography_id')


def numeric(value):
    try:
        number = float(value)
    except (ValueError, TypeError) as error:
        raise Quarantine('invalid_observed_number') from error
    if not math.isfinite(number):
        raise Quarantine('nonfinite_observed_number')
    return number


def record(parent, field, row, candidate, job, note):
    if parent in FOOD:
        raise Quarantine('food_not_permitted')
    return {'geo_id': row['geo_id'], 'geo_type': row['geo_type'],
        'year': '2024' if candidate['source'] == 'census_acs' else row['data_year'],
        'field_id': parent + ':' + field, 'catalog_field_id': parent,
        'unit': 'source_defined' if candidate['source'] == 'census_acs' else '%',
        'source': candidate['source'], 'source_release': candidate['source_release'],
        'source_url': job['raw']['url'], 'methodology_note': note, 'retrieved_at': job['raw']['retrieved_at']}


def outputs(row, candidate, job, parents):
    geography(row)
    emitted = []
    if candidate['source'] == 'census_acs':
        base = row['variable']
        if not re.fullmatch(r'B\d{5}_\d{3}', base) or not base.startswith(candidate['job_id'].removeprefix('acs-summary-') + '_'):
            raise Quarantine('unexpected_source_variable')
        if row['annotation_status'] not in ['not_collected', 'source_columns']:
            raise Quarantine('annotation_status_unknown')
        for component, suffix in [('estimate', 'E'), ('moe', 'M')]:
            variable = base + suffix
            if variable not in parents:
                # Explicitly unrequested counterpart may occur in a paired file.
                if base + ('M' if suffix == 'E' else 'E') not in parents:
                    raise Quarantine('source_variable_unmapped')
                continue
            status, value, token = row[component + '_status'], row[component], row[component + '_code']
            for parent in sorted(parents[variable]):
                item = record(parent, variable, row, candidate, job,
                              f'ACS variable {variable}; native Summary File; annotation_status={row["annotation_status"]}')
                if status == 'observed':
                    if token:
                        raise Quarantine('observed_cell_with_sentinel')
                    number = numeric(value)
                    if number <= -100000000 or (suffix == 'M' and number < 0):
                        raise Quarantine('invalid_observed_acs_sentinel_or_moe')
                    item['value'] = number
                    emitted.append(('observations', item))
                else:
                    if value or status not in STATUS_MAP:
                        raise Quarantine('unsupported_acs_quality')
                    item.update(quality_status=STATUS_MAP[status], raw_value=token or None,
                        annotation=json.dumps({'source_status': status, 'source_annotation': row[component + '_annotation'] or None,
                            'annotation_status': row['annotation_status']}, sort_keys=True, separators=(',', ':')))
                    emitted.append(('quality', item))
    else:
        parent = row['catalog_field_id']
        if parent not in ['05.14', '05.15', '05.16'] or row['variant'] != 'crude_prevalence' or row['data_year'] != '2023' or row['geo_type'] != 'tract':
            raise Quarantine('cdc_variant_or_identity_mismatch')
        if row['ci_status'] == 'observed':
            low, high = numeric(row['ci_low']), numeric(row['ci_high'])
            if not (0 <= low <= high <= 100):
                raise Quarantine('cdc_interval_invalid')
            if row['estimate_status'] == 'observed' and not low <= numeric(row['estimate']) <= high:
                raise Quarantine('cdc_estimate_outside_interval')
        for component in ['estimate', 'ci_low', 'ci_high']:
            field = 'crude_prevalence' + ('' if component == 'estimate' else ':' + component)
            item = record(parent, field, row, candidate, job,
                'CDC PLACES crude prevalence; 95% confidence interval; observation year 2023; tract vintage 2023')
            status = row['estimate_status'] if component == 'estimate' else row['ci_status']
            if status == 'observed':
                value = numeric(row[component])
                if not 0 <= value <= 100:
                    raise Quarantine('cdc_percentage_out_of_range')
                item['value'] = value
                emitted.append(('observations', item))
            else:
                if row[component]:
                    raise Quarantine('cdc_unobserved_value_present')
                if component == 'estimate':
                    if status not in STATUS_MAP:
                        raise Quarantine('unknown_cdc_estimate_status')
                    quality = STATUS_MAP[status]
                else:
                    if status != 'missing_or_unparsed':
                        raise Quarantine('unknown_cdc_ci_status')
                    quality = 'invalid' if row['raw_ci'] else 'missing'
                item.update(quality_status=quality, raw_value=row['raw_ci'] or None if component != 'estimate' else None,
                    annotation=json.dumps({'source_status': status, 'component': component}, sort_keys=True, separators=(',', ':')))
                emitted.append(('quality', item))
    for kind, item in emitted:
        if set(item) != (WIRE if kind == 'observations' else QUALITY_WIRE):
            raise Quarantine('internal_wire_schema_mismatch')
    return emitted


class Stream:
    def __init__(self, path):
        self.path = path
        self.temporary = path.with_suffix(path.suffix + '.tmp')
        self.handle = self.temporary.open('wb')
        self.gzip = gzip.GzipFile(filename='', mode='wb', fileobj=self.handle, mtime=0, compresslevel=1)
        self.rows = 0
        self.uncompressed = 0

    def add(self, value):
        data = (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
        self.gzip.write(data)
        self.rows += 1
        self.uncompressed += len(data)

    def finish(self):
        self.gzip.close()
        self.handle.close()
        self.temporary.replace(self.path)
        return {'path': self.path.name, 'sha256': sha(self.path), 'rows': self.rows,
                'bytes': self.path.stat().st_size, 'uncompressed_bytes': self.uncompressed}

    def abort(self):
        self.gzip.close()
        self.handle.close()
        self.temporary.unlink(missing_ok=True)


def prepare(candidate, out, max_rows, cursor):
    if max_rows < 1 or max_rows > 1000000:
        raise Quarantine('max_rows_must_be_1_to_1000000')
    if cursor is not None and not isinstance(cursor, dict):
        raise Quarantine('cursor_must_be_object_or_null')
    fresh = candidate_for(candidate['source_manifest_path'], candidate['job_id'], candidate.get('extension', False))
    if fresh != candidate:
        raise Quarantine('candidate_no_longer_matches_source')
    adapter_hash = sha(Path(__file__))
    request_hash = document_hash({'candidate': candidate, 'cursor': cursor, 'max_input_rows': max_rows,
                                 'max_output_rows': OUTPUT_LIMIT, 'adapter_sha256': adapter_hash})
    existing = out / 'prepare-result.json'
    if existing.exists():
        result = read(existing)
        if result.get('request_sha256') != request_hash:
            raise Quarantine('batch_directory_bound_to_different_request')
        if result.get('status') == 'ready':
            manifest = read(out / result['manifest'])
            if sha(out / result['manifest']) != result['manifest_sha256']:
                raise Quarantine('prepared_manifest_hash_mismatch')
            check_inputs([{'path': str(out / manifest[k]['path']), **{n: manifest[k][n] for n in ['sha256', 'bytes']}} for k in ['observations', 'quality']])
            return result
    if shutil.disk_usage(out).free < 1024**3:
        raise OSError('insufficient_free_disk_for_bounded_preparation')
    source_manifest = read(candidate['source_manifest_path'])
    job = source_manifest['jobs'][candidate['job_id']]
    normalized = within_repo(Path(candidate['source_manifest_path']).parent / job['normalized']['path'])
    parents = mappings(candidate)
    start = (cursor or {}).get('input_row', 0)
    if isinstance(start, bool) or not isinstance(start, int) or start < 0 or start >= candidate['input_rows']:
        raise Quarantine('cursor_input_row_invalid')
    streams = {kind: Stream(out / (kind + '.jsonl.gz')) for kind in ['observations', 'quality']}
    counts, seen = Counter(), set()
    consumed, emitted = 0, 0
    last_offset, last_line_hash = None, None
    try:
        with gzip.open(normalized, 'rb') as handle:
            header_bytes = handle.readline()
            header = next(csv.reader([header_bytes.decode('utf-8')]))
            expected = ACS_COLUMNS if candidate['source'] == 'census_acs' else CDC_COLUMNS
            if header != expected or len(header) != len(set(header)):
                raise Quarantine('normalized_header_changed_or_duplicate')
            header_hash = hashlib.sha256(header_bytes).hexdigest()
            if cursor:
                if cursor.get('source_sha256') != job['normalized']['sha256'] or cursor.get('header_sha256') != header_hash:
                    raise Quarantine('cursor_source_binding_mismatch')
                if start:
                    handle.seek(cursor['previous_offset'])
                    anchor = handle.readline()
                    if hashlib.sha256(anchor).hexdigest() != cursor['previous_line_sha256'] or handle.tell() != cursor['uncompressed_offset']:
                        raise Quarantine('cursor_anchor_mismatch')
                elif cursor.get('uncompressed_offset', handle.tell()) != handle.tell():
                    raise Quarantine('cursor_zero_offset_invalid')
            while consumed < max_rows and start + consumed < candidate['input_rows']:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    raise Quarantine('normalized_file_truncated')
                values = next(csv.reader([line.decode('utf-8')]))
                if len(values) != len(header):
                    raise Quarantine('normalized_row_width')
                row = dict(zip(header, values))
                parts = outputs(row, candidate, job, parents)
                if emitted + len(parts) > OUTPUT_LIMIT:
                    handle.seek(offset)
                    break
                key = (row['geo_type'], row['geo_id'], row.get('variable', row.get('catalog_field_id')))
                if key in seen:
                    raise Quarantine('duplicate_native_row_within_chunk')
                seen.add(key)
                for kind, item in parts:
                    streams[kind].add(item)
                    counts[kind + ':' + item['geo_type']] += 1
                    if kind == 'quality':
                        counts['quality_status:' + item['quality_status']] += 1
                emitted += len(parts)
                consumed += 1
                last_offset, last_line_hash = offset, hashlib.sha256(line).hexdigest()
                if consumed % 10000 == 0:
                    atomic(out / 'progress.json', {'status': 'preparing', 'updated_at': now(), 'input_rows': consumed,
                        'input_row_start': start, 'output_rows': emitted, 'pid': os.getpid()})
                    if shutil.disk_usage(out).free < 1024**3:
                        raise OSError('disk_headroom_exhausted')
            end = start + consumed
            complete = end == candidate['input_rows']
            if complete and handle.read(1):
                raise Quarantine('normalized_more_rows_than_manifest')
            if not consumed:
                raise Quarantine('empty_chunk')
            next_cursor = None if complete else {'input_row': end, 'uncompressed_offset': handle.tell(),
                'previous_offset': last_offset, 'previous_line_sha256': last_line_hash,
                'source_sha256': job['normalized']['sha256'], 'header_sha256': header_hash}
        artifacts = {kind: writer.finish() for kind, writer in streams.items()}
    except BaseException:
        for writer in streams.values():
            writer.abort()
        raise
    # Re-read all source hashes after parsing; incomplete/changing inputs never publish a complete bundle.
    check_inputs(candidate['source_artifacts'])
    shutil.copyfile(CONTRACT, out / 'field-contract.json')
    contract_hash = sha(out / 'field-contract.json')
    expected_contract_hash = next(r['sha256'] for r in candidate['source_artifacts'] if Path(r['path']) == CONTRACT)
    if contract_hash != expected_contract_hash or sha(Path(__file__)) != adapter_hash:
        raise Quarantine('contract_or_adapter_changed_during_preparation')
    adapter_version = VERSION + ':' + adapter_hash
    snapshot_id = document_hash({'dataset_key': candidate['dataset_id'],
        'input_hashes': sorted(r['sha256'] for r in candidate['source_artifacts']),
        'adapter_version': adapter_version, 'contract_sha256': contract_hash})
    scope = {'type': 'input_row_range', 'start_row': start, 'end_row_exclusive': end,
             'total_input_rows': candidate['input_rows'], 'job_id': candidate['job_id'],
             'geography_vintage': candidate['geography_vintage'], 'data_period': candidate['data_period'],
             'native_geography_counts_for_complete_source': candidate['native_geography_counts'],
             'max_input_rows': max_rows, 'max_output_rows': OUTPUT_LIMIT,
             'dataset_complete_in_this_chunk': complete, 'row_counts': dict(counts),
             'annotation_policy': 'ACS annotations not_collected preserved; nonobserved cells in required quality sidecar',
             'no_derived_formulas': True, 'food_excluded': sorted(FOOD)}
    batch_id = document_hash({'snapshot_id': snapshot_id, 'start_row': start, 'end_row_exclusive': end,
                              'artifact_hashes': {k: v['sha256'] for k, v in artifacts.items()}})
    manifest = {'format': 'usa_atlas_admission_v1', 'status': 'complete', 'batch_id': batch_id,
        'snapshot_id': snapshot_id, 'dataset_key': candidate['dataset_id'], 'kind': 'observations',
        'source': candidate['source'], 'source_release': candidate['source_release'], 'snapshot_at': candidate['snapshot_at'],
        'adapter_version': adapter_version, 'adapter': {'path': os.path.relpath(Path(__file__).resolve(), out), 'sha256': adapter_hash},
        'scope': scope, 'completeness': {'complete': True, 'basis': 'Complete hash-verified source; exact bounded input-row interval; full dataset completion tracked separately.'},
        'contract': {'path': 'field-contract.json', 'sha256': contract_hash},
        'inputs': [{'path': os.path.relpath(r['path'], out), 'sha256': r['sha256'], 'bytes': r['bytes']} for r in candidate['source_artifacts']],
        **artifacts, 'records': None}
    atomic(out / 'admission-manifest.json', manifest)
    result = {'status': 'ready', 'manifest': 'admission-manifest.json',
        'manifest_sha256': sha(out / 'admission-manifest.json'), 'next_cursor': next_cursor,
        'complete': complete, 'prepared_rows': emitted, 'prepared_input_rows': consumed,
        'observation_rows': artifacts['observations']['rows'], 'quality_rows': artifacts['quality']['rows'],
        'request_sha256': request_hash, 'batch_id': batch_id, 'snapshot_id': snapshot_id}
    atomic(out / 'prepare-result.json', result)
    atomic(out / 'progress.json', {'status': 'ready', 'updated_at': now(), 'input_rows': consumed, 'output_rows': emitted})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('discover')
    scan.add_argument('--json', action='store_true')
    scan.add_argument('--runtime', type=Path, default=DEFAULT_RUNTIME)
    run = commands.add_parser('prepare')
    run.add_argument('--candidate', type=Path, required=True)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--max-rows', type=int, default=100000)
    run.add_argument('--cursor', default='null')
    args = parser.parse_args()
    try:
        if args.command == 'discover':
            result = discover(within_repo(args.runtime))
        else:
            args.out = within_repo(args.out)
            args.out.mkdir(parents=True, exist_ok=True)
            with (args.out / '.prepare.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    result = prepare(read(args.candidate), args.out, args.max_rows, json.loads(args.cursor))
                except HANDLED_ERRORS as error:
                    try:
                        save_failure(args.out, failure(error))
                    except OSError:
                        # The original failure remains available on stdout/stderr
                        # even when disk/permissions prevent a durable receipt.
                        pass
                    raise
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HANDLED_ERRORS as error:
        result = failure(error)
        encoded = json.dumps(result, ensure_ascii=False)
        print(encoded)
        print(encoded, file=sys.stderr)
        return 75 if result['status'] == 'transient_failure' else 65


if __name__ == '__main__':
    raise SystemExit(main())
