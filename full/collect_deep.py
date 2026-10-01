#!/usr/bin/env python3
"""Independent research collector: verified legacy ACS recovery and native deep data.

Does not write the production manifest, contract, raw cache or database. Python stdlib.
Raw Census sentinels and absent E/M counterparts survive as explicit quality states.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import http.client
import io
import json
import math
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = ROOT / 'research/2026-09-28/geography'
CONTRACT = HERE / 'field-contract.json'
SF_BASE = 'https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/'
FOOD = {'08.01', '08.02', '08.03', '08.06', '09.01', '09.02', '09.03'}
GEO_LENGTH = {'nation': 2, 'state': 2, 'county': 5, 'place': 7, 'tract': 11, 'block_group': 12}
SUMMARY_LEVEL = {'040': 'state', '050': 'county', '140': 'tract', '150': 'block_group', '160': 'place'}
SPECIAL = {
    '-666666666': 'estimate_not_computable',
    '-999999999': 'suppressed_insufficient_sample',
    '-888888888': 'not_applicable_or_unavailable',
    '-222222222': 'moe_insufficient_sample',
    '-333333333': 'moe_open_ended_median',
    '-555555555': 'moe_controlled_estimate',
    '-': 'estimate_not_computable', 'N': 'suppressed_insufficient_sample',
    '(X)': 'not_applicable_or_unavailable', '**': 'moe_insufficient_sample',
    '***': 'moe_open_ended_median', '*****': 'moe_controlled_estimate',
}
OBS_HEADER = ['geo_type', 'geo_id', 'variable', 'estimate', 'moe',
              'estimate_status', 'moe_status', 'estimate_code', 'moe_code',
              'estimate_annotation', 'moe_annotation', 'annotation_status']


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(canonical(value))
    temp.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def artifact(path: Path, out: Path) -> dict:
    return {'path': str(path.relative_to(out)), 'sha256': digest(path), 'bytes': path.stat().st_size}


@contextmanager
def csv_writer(path: Path, header, compresslevel=9):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    try:
        with temp.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=compresslevel) as gz:
            with io.TextIOWrapper(gz, encoding='utf-8', newline='') as text:
                writer = csv.writer(text, lineterminator='\n')
                writer.writerow(header)
                yield writer
        temp.replace(path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def cell(raw, present=True):
    if not present:
        return '', 'not_collected', ''
    if raw is None or str(raw).strip() in {'', 'null'}:
        return '', 'missing', ''
    text = str(raw).strip()
    if text in SPECIAL:
        return '', SPECIAL[text], text
    try:
        number = float(text)
        if not math.isfinite(number):
            raise ValueError('nonfinite')
        if number <= -100000000:
            return '', 'unknown_negative_sentinel', text
        return text, 'observed', ''
    except ValueError:
        return '', 'unparsed_source_token', text


def observation(geo_type, geo_id, base, values):
    e, m = base + 'E', base + 'M'
    ev, es, ec = cell(values.get(e), e in values)
    mv, ms, mc = cell(values.get(m), m in values)
    annotations = 'source_columns' if e + 'A' in values or m + 'A' in values else 'not_collected'
    return [geo_type, geo_id, base, ev, mv, es, ms, ec, mc,
            values.get(e + 'A') or '', values.get(m + 'A') or '', annotations]


def geo_id(values, geo_type):
    parts = {'state': ['state'], 'county': ['state', 'county'],
             'place': ['state', 'place'], 'tract': ['state', 'county', 'tract'],
             'block_group': ['state', 'county', 'tract', 'block group']}[geo_type]
    result = ''.join(values[x] for x in parts)
    if not re.fullmatch(r'\d{' + str(GEO_LENGTH[geo_type]) + '}', result):
        raise ValueError('invalid_geoid')
    return result


def variables_by_table():
    result = defaultdict(set)
    for field in json.loads(CONTRACT.read_text()):
        if field['rate_limit_profile'] == 'census_acs' and field['field_id'] not in FOOD:
            for variable in field['source_variables']:
                if not re.fullmatch(r'B\d+_\d{3}[EM]', variable):
                    raise ValueError('contract_requires_concrete_acs_variables')
                result[variable.split('_')[0]].add(variable[:-1])
    return {table: sorted(bases) for table, bases in sorted(result.items())}


def recover(out: Path):
    legacy = json.loads((HERE / 'state/run-manifest.json').read_text())
    bindings = {key: legacy[key] for key in
                ['plan_sha256', 'contract_sha256', 'config_sha256', 'collector_sha256']}
    for filename, key in [('field-contract.json', 'contract_sha256'),
                          ('adapter-config.json', 'config_sha256'), ('collect.py', 'collector_sha256')]:
        if digest(HERE / filename) != bindings[key]:
            raise ValueError('legacy_code_or_contract_binding_mismatch')
    files = sorted((HERE / 'raw/full/census_acs').glob('*.json.gz'))
    verified, groups = [], defaultdict(list)
    for path in files:
        h = digest(path)
        if path.with_name(path.name + '.sha256').read_text().strip() != h:
            raise ValueError('legacy_payload_hash_mismatch')
        binding = json.loads(path.with_name(path.name + '.binding.json').read_text())
        if binding.get('payload_sha256') != h or any(binding.get(k) != v for k, v in bindings.items()):
            raise ValueError('legacy_payload_binding_mismatch')
        verified.append({'path': str(path.relative_to(ROOT)), 'sha256': h, 'bytes': path.stat().st_size})
        match = re.fullmatch(r'2024-(state|county|place|tract)-(\w+)-pack-\d+\.json.gz', path.name)
        if match:
            groups[match.group(1), match.group(2)].append(path)
    counters, quality, geographic_counts, states = Counter(), Counter(), Counter(), defaultdict(set)
    by_geo_variables = defaultdict(set)
    output = out / 'data/recovered-acs-2024.csv.gz'
    names = out / 'data/recovered-geographies-2024.csv.gz'
    with csv_writer(output, OBS_HEADER) as writer, csv_writer(names, ['geo_type', 'geo_id', 'parent_geo_id', 'name']) as geow:
        for (geotype, state), paths in sorted(groups.items()):
            merged = {}
            for path in paths:
                with gzip.open(path, 'rt', encoding='utf-8') as f:
                    table = json.load(f)
                header = table[0]
                if len(set(header)) != len(header):
                    raise ValueError('duplicate_input_columns')
                job_seen = set()
                for values in table[1:]:
                    if len(values) != len(header):
                        raise ValueError('invalid_census_row_width')
                    record = dict(zip(header, values))
                    gid = geo_id(record, geotype)
                    if gid in job_seen:
                        raise ValueError('duplicate_geography_in_job')
                    job_seen.add(gid)
                    combined = merged.setdefault(gid, {})
                    for key, value in record.items():
                        if key in combined and combined[key] != value:
                            raise ValueError('conflicting_census_cache_values')
                        combined[key] = value
            for gid, values in sorted(merged.items()):
                parent = gid[:11] if geotype == 'block_group' else gid[:5] if geotype == 'tract' else gid[:2] if geotype != 'state' else ''
                geow.writerow([geotype, gid, parent, values['NAME']])
                geographic_counts[geotype] += 1
                states[geotype].add(gid[:2])
                bases = sorted({v[:-1] for v in values if re.fullmatch(r'B\d+_\d{3}[EM]', v)})
                for base in bases:
                    row = observation(geotype, gid, base, values)
                    writer.writerow(row)
                    counters[geotype] += 1
                    quality['estimate:' + row[5]] += 1
                    quality['moe:' + row[6]] += 1
                    by_geo_variables[geotype].update(v for v in [base + 'E', base + 'M'] if v in values)
    result = {
        'status': 'partial_recovered_verified_cache', 'source_release': '2024-acs-acs5',
        'output_schema_version': 'deep-research-1', 'recovery_collector_sha256': digest(Path(__file__)),
        'data_period': '2020-2024', 'geography_vintage': '2024 ACS publication geography',
        'geometry_downloaded': False, 'not_admitted_to_production': True,
        'recovered_at': now(), 'source_retrieved_at': legacy['sources']['census_acs'].get('normalization_retrieved_at'),
        'retrieval_timestamp_note': 'Legacy run timestamp; individual HTTP retrieval timestamps are unavailable.',
        'legacy_bindings': bindings, 'verified_inputs': verified,
        'metadata_payload_count': len(files) - sum(map(len, groups.values())),
        'data_payload_count': sum(map(len, groups.values())),
        'geography_counts': dict(geographic_counts), 'observation_pairs_by_geography': dict(counters),
        'observation_pairs_total': sum(counters.values()), 'quality_counts': dict(quality),
        'states_by_geography': {k: sorted(v) for k, v in states.items()},
        'observed_variables_by_geography': {k: sorted(v) for k, v in by_geo_variables.items()},
        'artifacts': [artifact(output, out), artifact(names, out)],
        'limitations': ['Incomplete source and catalog fields; pairs with missing M remain explicit.',
                       'No block groups recovered.', 'EA/MA columns absent from legacy cache; annotations not collected.',
                       'B01001 total must not silently replace the contracted B01003 population series.'],
    }
    save(out / 'cache-recovery-manifest.json', result)
    return {k: result[k] for k in ['status', 'data_payload_count', 'geography_counts', 'observation_pairs_total', 'quality_counts']}


def plan():
    result = []
    tables = variables_by_table()
    for table in sorted(tables, key=lambda name: (name != 'B01003', len(tables[name]), name)):
        variables = tables[table]
        result.append({'id': 'acs-summary-' + table, 'provider': 'acs-summary', 'table': table,
                       'url': SF_BASE + f'acsdt5y2024-{table.lower()}.dat',
                       'variables': variables, 'release': '2024-acs-acs5',
                       'native_geographies_only': True})
    columns = ['stateabbr', 'countyfips', 'tractfips']
    for measure in ['obesity', 'diabetes', 'lpa']:
        columns += [measure + '_crudeprev', measure + '_crude95ci']
    query = urllib.parse.urlencode({'$select': ','.join(columns), '$limit': 100000, '$order': 'tractfips'})
    result.append({'id': 'cdc-places-2025-tract', 'provider': 'cdc-places',
                   'url': 'https://data.cdc.gov/resource/yjkw-uj5s.csv?' + query,
                   'release': 'PLACES-2025', 'data_year': '2023', 'geography_vintage': '2023',
                   'variant': 'crude_prevalence', 'row_limit': 100000, 'expected_native_rows': 83522,
                   'warning': 'Tract crude prevalence is a separate variant from existing county age-adjusted prevalence.'})
    return result


def download(job, out, timeout, max_bytes, progress=None, min_free_bytes=2 * 1024 ** 3):
    path = out / 'raw' / (job['id'] + '.gz')
    meta_path = path.with_name(path.name + '.json')
    binding = hashlib.sha256(canonical(job)).hexdigest()
    if path.exists():
        if not meta_path.exists():
            raise ValueError('raw_metadata_missing')
        meta = json.loads(meta_path.read_text())
        if meta['job_sha256'] != binding or meta['sha256'] != digest(path):
            raise ValueError('raw_binding_or_hash_mismatch')
        return path, meta
    if shutil.disk_usage(out).free < min_free_bytes:
        raise ValueError('insufficient_disk_headroom')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.part')
    upstream = hashlib.sha256()
    total = 0
    request = urllib.request.Request(job['url'], headers={'User-Agent': 'USA-Atlas-deep-research/1.0'})
    provider_metadata = places_metadata(timeout) if job['provider'] == 'cdc-places' else None
    last_report = 0.0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temp.open('wb') as raw:
            if response.status != 200:
                raise ValueError('unexpected_partial_or_non200_payload')
            length = response.headers.get('Content-Length')
            if length and int(length) > max_bytes:
                raise ValueError('response_exceeds_byte_limit')
            content_type = response.headers.get('Content-Type', '')
            if 'html' in content_type:
                raise ValueError('unexpected_html_response')
            etag = response.headers.get('ETag')
            modified = response.headers.get('Last-Modified')
            with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=1) as gz:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes or shutil.disk_usage(out).free < min_free_bytes:
                        raise ValueError('download_limit_reached')
                    upstream.update(chunk)
                    gz.write(chunk)
                    if progress and time.monotonic() - last_report > 10:
                        progress({'stage': 'downloading', 'upstream_bytes_received': total,
                                  'upstream_content_length': int(length) if length else None})
                        last_report = time.monotonic()
            if length and total != int(length):
                raise ValueError('incomplete_http_response')
        if provider_metadata is not None and places_metadata(timeout) != provider_metadata:
            raise ValueError('places_release_changed_during_download')
        temp.replace(path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    meta = {**artifact(path, out), 'job_sha256': binding, 'url': job['url'],
            'upstream_sha256': upstream.hexdigest(), 'upstream_bytes': total,
            'retrieved_at': now(), 'etag': etag, 'last_modified': modified}
    if provider_metadata is not None:
        meta['provider_metadata'] = provider_metadata
    save(meta_path, meta)
    return path, meta


def places_metadata(timeout):
    url = 'https://data.cdc.gov/api/views/yjkw-uj5s.json'
    request = urllib.request.Request(url, headers={'User-Agent': 'USA-Atlas-deep-research/1.0'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read(4 * 1024 ** 2))
    if '2025' not in value.get('name', '') or 'Census Tract' not in value.get('name', ''):
        raise ValueError('places_release_is_not_pinned_2025_tract')
    revision = value.get('rowsUpdatedAt')
    if revision is None:
        raise ValueError('places_revision_missing')
    return {'id': value['id'], 'name': value['name'], 'rowsUpdatedAt': revision,
            'metadata_url': url}


def summary_rows(path, variables, geographies):
    with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter='|')
        if not reader.fieldnames or 'GEO_ID' not in reader.fieldnames:
            raise ValueError('invalid_summary_header')
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('duplicate_summary_header')
        remap = {}
        for key in reader.fieldnames:
            match = re.fullmatch(r'(B\d+)_([EM])(\d{3})', key)
            if match:
                remap[key] = match.group(1) + '_' + match.group(3) + match.group(2)
        expected = {base + suffix for base in variables for suffix in 'EM'}
        if not expected <= set(remap.values()):
            raise ValueError('contract_variables_missing_from_summary_header')
        previous = set()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('invalid_summary_row_width')
            gid = row['GEO_ID']
            if gid == '0100000US':
                geotype, gid = 'nation', 'US'
            else:
                match = re.fullmatch(r'(040|050|140|150|160)0000US(\d+)', gid)
                if not match:
                    continue
                geotype, gid = SUMMARY_LEVEL[match.group(1)], match.group(2)
            if geotype not in geographies:
                continue
            if len(gid) != GEO_LENGTH[geotype] or (geotype, gid) in previous:
                raise ValueError('invalid_or_duplicate_summary_geography')
            previous.add((geotype, gid))
            values = {remap[k]: v for k, v in row.items() if k in remap}
            for base in variables:
                yield observation(geotype, gid, base, values)


def normalize_job(job, raw, out, geographies, progress=None):
    path = out / 'data' / (job['id'] + '.csv.gz')
    counts, quality, geography_counts = Counter(), Counter(), Counter()
    last_geo, total, last_report = None, 0, time.monotonic()
    if job['provider'] == 'acs-summary':
        with csv_writer(path, OBS_HEADER, compresslevel=1) as writer:
            for row in summary_rows(raw, job['variables'], geographies):
                writer.writerow(row)
                counts[row[0]] += 1
                quality['estimate:' + row[5]] += 1
                quality['moe:' + row[6]] += 1
                this_geo = (row[0], row[1])
                if this_geo != last_geo:
                    geography_counts[row[0]] += 1
                    last_geo = this_geo
                total += 1
                if progress and total % 10000 == 0 and time.monotonic() - last_report > 10:
                    progress({'stage': 'normalizing', 'rows_by_geography': dict(counts),
                              'geography_counts': dict(geography_counts), 'normalized_rows': total})
                    last_report = time.monotonic()
    else:
        header = ['geo_type', 'geo_id', 'catalog_field_id', 'variant', 'data_year',
                  'estimate', 'ci_low', 'ci_high', 'estimate_status', 'ci_status', 'raw_ci']
        seen = set()
        with gzip.open(raw, 'rt', encoding='utf-8-sig', newline='') as f, csv_writer(path, header, compresslevel=1) as writer:
            reader = csv.DictReader(f)
            needed = {'tractfips', 'countyfips'} | {m + s for m in ['obesity', 'diabetes', 'lpa'] for s in ['_crudeprev', '_crude95ci']}
            if not needed <= set(reader.fieldnames or []):
                raise ValueError('invalid_places_header')
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError('duplicate_places_header')
            for record in reader:
                if None in record or any(value is None for value in record.values()):
                    raise ValueError('invalid_places_row_width')
                gid = record['tractfips']
                if not re.fullmatch(r'\d{11}', gid) or gid[:5] != record['countyfips'] or gid in seen:
                    raise ValueError('invalid_or_duplicate_places_geography')
                seen.add(gid)
                for field, measure in [('05.14', 'obesity'), ('05.15', 'diabetes'), ('05.16', 'lpa')]:
                    value, status, _ = cell(record.get(measure + '_crudeprev'))
                    ci = record.get(measure + '_crude95ci') or ''
                    match = re.fullmatch(r'\(?\s*([\d.]+)\s*,\s*([\d.]+)\s*\)?', ci)
                    low, high = match.groups() if match else ('', '')
                    if value and not 0 <= float(value) <= 100:
                        raise ValueError('invalid_prevalence')
                    if match and not 0 <= float(low) <= float(high) <= 100:
                        raise ValueError('invalid_confidence_interval')
                    writer.writerow(['tract', gid, field, 'crude_prevalence', job['data_year'],
                                     value, low, high, status, 'observed' if match else 'missing_or_unparsed', ci])
                    counts['tract'] += 1
                    quality['estimate:' + status] += 1
            if len(seen) >= job['row_limit']:
                raise ValueError('places_row_limit_reached_possible_truncation')
            if len(seen) != job['expected_native_rows']:
                raise ValueError('places_count_differs_from_pinned_release_83522')
            geography_counts['tract'] = len(seen)
    if not sum(counts.values()):
        raise ValueError('zero_normalized_rows')
    return {**artifact(path, out), 'rows_by_geography': dict(counts),
            'geography_counts': dict(geography_counts), 'quality_counts': dict(quality)}


def collect(out, provider, max_jobs, timeout, geographies, max_payload_bytes=4 * 1024 ** 3):
    if provider == 'cdc-places' and 'tract' not in geographies:
        raise ValueError('cdc_places_requires_tract_geography')
    jobs = [job for job in plan() if job['provider'] == provider]
    state_path = out / ('run-' + provider + '.json')
    bindings = {'collector_sha256': digest(Path(__file__)), 'contract_sha256': digest(CONTRACT),
                'plan_sha256': hashlib.sha256(canonical(jobs)).hexdigest(), 'geographies': sorted(geographies)}
    state = json.loads(state_path.read_text()) if state_path.exists() else {'bindings': bindings, 'jobs': {}}
    if state['bindings'] != bindings:
        raise ValueError('run_bindings_changed_use_new_output_directory')
    state.update({'status': 'running', 'started_at': state.get('started_at', now()),
                  'planned_jobs': len(jobs), 'completed_jobs': sum(x.get('status') == 'complete' for x in state['jobs'].values())})
    save(state_path, state)
    done = 0
    for job in jobs:
        saved = state['jobs'].get(job['id'], {})
        if saved.get('status') == 'complete':
            for item in [saved['raw'], saved['normalized']]:
                if digest(out / item['path']) != item['sha256']:
                    raise ValueError('completed_artifact_hash_mismatch')
            continue
        if done >= max_jobs:
            break
        done += 1
        started = now()
        def progress(update):
            state['active_job'] = {'id': job['id'], 'started_at': started, 'updated_at': now(), **update}
            save(state_path, state)
            print(json.dumps({'event': 'progress', **state['active_job']}), flush=True)
        progress({'stage': 'starting'})
        try:
            raw, metadata = download(job, out, timeout, max_payload_bytes, progress=progress)
            progress({'stage': 'normalizing', 'upstream_bytes': metadata['upstream_bytes']})
            output = normalize_job(job, raw, out, geographies, progress=progress)
            state['jobs'][job['id']] = {'status': 'complete', 'release': job['release'],
                                       'started_at': started, 'completed_at': now(),
                                       'data_period': '2020-2024' if provider == 'acs-summary' else '2023',
                                       'geography_vintage': '2024 ACS publication geography' if provider == 'acs-summary' else '2023',
                                       'raw': metadata, 'normalized': output}
            state['completed_jobs'] = sum(x.get('status') == 'complete' for x in state['jobs'].values())
            print(json.dumps({'event': 'job_complete', 'job': job['id'], 'coverage': output['geography_counts'],
                              'normalized_bytes': output['bytes'], 'completed_jobs': state['completed_jobs']}), flush=True)
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as error:
            reason = 'http_' + str(error.code) if isinstance(error, urllib.error.HTTPError) else 'network_' + type(error.reason).__name__ if isinstance(error, urllib.error.URLError) else type(error).__name__ + ':' + str(error)
            state['jobs'][job['id']] = {'status': 'blocked_or_failed', 'reason': reason, 'url': job['url'], 'attempted_at': now()}
            state['status'] = 'partial_or_blocked'
            save(state_path, state)
            return {'status': state['status'], 'job': job['id'], 'reason': reason}
        save(state_path, state)
        time.sleep(1)
    complete = sum(x.get('status') == 'complete' for x in state['jobs'].values())
    state['status'] = 'complete' if complete == len(jobs) else 'partial'
    state['completed_jobs'], state['planned_jobs'] = complete, len(jobs)
    state.pop('active_job', None)
    state['updated_at'] = now()
    save(state_path, state)
    return {'status': state['status'], 'completed_jobs': complete, 'planned_jobs': len(jobs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['recover-cache', 'plan', 'collect'])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--provider', choices=['acs-summary', 'cdc-places'], default='acs-summary')
    parser.add_argument('--max-jobs', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--geographies', default='county,tract,block_group')
    parser.add_argument('--max-payload-gib', type=float, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    geographies = set(args.geographies.split(','))
    if not geographies <= set(GEO_LENGTH) or args.max_jobs < 1 or args.timeout <= 0 or args.max_payload_gib <= 0:
        parser.error('invalid geography, job count or timeout')
    if args.command == 'collect' and args.provider == 'cdc-places' and 'tract' not in geographies:
        parser.error('CDC PLACES collector requires tract in --geographies')
    if args.command == 'recover-cache':
        result = recover(args.out)
    elif args.command == 'plan':
        save(args.out / 'collection-plan.json', {'jobs': plan(), 'excluded_food_fields': sorted(FOOD),
             'production_admission': False, 'api_key_required': False,
             'release_pin': 'ACS 2024 and PLACES 2025; mutable provider files require a fresh output directory on refresh.'})
        result = {'planned_jobs': len(plan()), 'path': str(args.out / 'collection-plan.json')}
    else:
        result = collect(args.out, args.provider, args.max_jobs, args.timeout, geographies, int(args.max_payload_gib * 1024 ** 3))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('status') == 'partial_or_blocked':
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
