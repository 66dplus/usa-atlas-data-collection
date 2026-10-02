#!/usr/bin/env python3
"""Admit native 2023 IRS county totals for the three existing ZIP tax fields.

The source has eight AGI-size bands per county. This adapter sums the published
band cells by variable. It does not allocate ZIP values to counties, invent a
missing N00100 column, or treat county FIPS 000 state totals as counties.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()
BASE = ROOT / 'full/runtime/public-20260928'
CONTRACT = ROOT / 'full/field-contract.json'
DATASET = 'irs_soi/2023-county/agi-capital-gains-dividends'
RELEASE = 'IRS-SOI-COUNTY-2023'
VERSION = 'irs-county-native-v1'
VARIABLES = (
    ('07.01', 'A00100', 'thousand_USD'),
    ('07.03', 'N01000', 'returns'),
    ('07.03', 'A01000', 'thousand_USD'),
    ('07.04', 'N00600', 'returns'),
    ('07.04', 'A00600', 'thousand_USD'),
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def within(path):
    p = path.resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('path_outside_repository')
    return p


def bound(path, expected=None):
    path = within(path)
    value = sha(path)
    if expected is not None and value != expected:
        raise ValueError('source_hash_changed')
    return {'path': str(path.relative_to(ROOT)), 'sha256': value,
            'bytes': path.stat().st_size}


def atomic(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + '\n')
    os.chmod(temp, 0o600)
    temp.replace(path)


def candidate():
    manifest_path = BASE / 'manifest.json'
    job = json.loads(manifest_path.read_text())['jobs']['irs-county-agi-2023']
    if job['status'] != 'source_tables_collected' or job['period'] != '2023' or job['geo'] != 'county':
        raise ValueError('irs_source_not_complete_or_wrong_period')
    table = job['table']
    if table['table_rows_including_preserved_headers_when_nested'] != 25552:
        raise ValueError('irs_2023_row_count_changed')
    table_file = within(BASE / table['path'])
    raw_file = within(BASE / job['raw']['path'])
    inputs = [bound(table_file, table['sha256']),
              bound(raw_file, job['raw']['sha256']), bound(CONTRACT)]
    source_manifest = bound(manifest_path)
    adapter = bound(HERE)
    result = {
        'dataset_id': DATASET, 'source': 'irs_soi', 'source_release': RELEASE,
        'snapshot_at': job['raw']['retrieved_at'],
        'source_manifest_path': source_manifest['path'],
        'source_manifest_sha256': source_manifest['sha256'],
        'source_artifacts': inputs, 'input_rows': 25552,
        'source_url': job['url'], 'table_path': str(table_file.relative_to(ROOT)),
        'adapter': adapter,
    }
    result['revision'] = digest(result)
    return result


def write_gzip(path, rows):
    temp = path.with_suffix(path.suffix + '.tmp')
    count = size = 0
    with temp.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
            for row in rows:
                line = (canonical(row) + '\n').encode()
                zipped.write(line)
                count += 1
                size += len(line)
    os.chmod(temp, 0o600)
    temp.replace(path)
    return {'path': path.name, 'sha256': sha(path), 'rows': count,
            'bytes': path.stat().st_size, 'uncompressed_bytes': size}


def prepare(candidate_file, out, max_rows, cursor):
    selected = json.loads(within(candidate_file).read_text())
    fresh = candidate()
    if selected != fresh:
        raise ValueError('candidate_superseded_or_unregistered')
    if cursor is not None or max_rows < fresh['input_rows']:
        raise ValueError('irs_snapshot_requires_one_complete_batch')
    out = within(out)
    out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out).free < 13 * 1024 ** 3:
        raise ValueError('insufficient_preparation_disk_headroom')
    table = within(ROOT / fresh['table_path'])
    sums = {}
    stubs = {}
    state_totals = set()
    rows_read = 0
    with gzip.open(table, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'STATEFIPS', 'COUNTYFIPS', 'agi_stub', *(v for _, v, _ in VARIABLES)}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError('irs_columns_missing')
        for row in reader:
            rows_read += 1
            state, county, stub = row['STATEFIPS'], row['COUNTYFIPS'], row['agi_stub']
            if len(state) != 2 or len(county) != 3 or not (state + county).isdigit() or stub not in '12345678':
                raise ValueError('irs_geo_or_stub_invalid')
            if county == '000':
                state_totals.add(state)
                continue
            geo = state + county
            key = (geo, stub)
            if key in stubs:
                raise ValueError('irs_duplicate_county_stub')
            stubs[key] = True
            bucket = sums.setdefault(geo, {variable: Decimal(0) for _, variable, _ in VARIABLES})
            for _, variable, _ in VARIABLES:
                try:
                    value = Decimal(row[variable])
                except InvalidOperation as error:
                    raise ValueError('irs_numeric_cell_invalid') from error
                if not value.is_finite():
                    raise ValueError('irs_nonfinite_cell')
                bucket[variable] += value
    if rows_read != fresh['input_rows'] or len(state_totals) != 51 or len(sums) != 3143:
        raise ValueError('irs_source_coverage_changed')
    if len(stubs) != 3143 * 8 or any((geo, stub) not in stubs for geo in sums for stub in '12345678'):
        raise ValueError('irs_county_band_incomplete')
    for item in fresh['source_artifacts']:
        bound(ROOT / item['path'], item['sha256'])
    if sha(HERE) != fresh['adapter']['sha256']:
        raise ValueError('adapter_changed_during_preparation')
    contract_copy = out / 'field-contract.json'
    shutil.copyfile(CONTRACT, contract_copy)
    os.chmod(contract_copy, 0o600)
    contract = bound(contract_copy)
    released = datetime.fromisoformat(fresh['snapshot_at'].replace('Z', '+00:00')).isoformat()

    def observations():
        for geo in sorted(sums):
            for field, variable, unit in VARIABLES:
                yield {
                    'geo_id': geo, 'geo_type': 'county', 'year': '2023',
                    'field_id': field + ':' + variable + ':county_sum_agi_stubs_1_8',
                    'catalog_field_id': field, 'value': float(sums[geo][variable]),
                    'unit': unit, 'source': 'irs_soi', 'source_release': RELEASE,
                    'source_url': fresh['source_url'],
                    'methodology_note': 'IRS county table 2023; sum of published AGI-size rows 1-8 for '
                                        + variable + '; source cells are rounded; tax return address geography; '
                                        'state-total county code 000 excluded.',
                    'retrieved_at': released,
                }

    observations_file = write_gzip(out / 'observations.jsonl.gz', observations())
    quality_file = write_gzip(out / 'quality.jsonl.gz', ())
    adapter_version = VERSION + ':' + fresh['adapter']['sha256']
    snapshot_id = digest({'candidate': fresh['revision'], 'contract': contract['sha256'],
                          'adapter_version': adapter_version})
    batch_id = digest({'snapshot_id': snapshot_id, 'observations': observations_file['sha256'],
                       'quality': quality_file['sha256']})

    def relative_binding(item):
        return {'path': os.path.relpath(ROOT / item['path'], out), 'sha256': item['sha256'],
                'bytes': item['bytes']}

    manifest = {
        'format': 'usa_atlas_admission_v1', 'status': 'complete',
        'batch_id': batch_id, 'snapshot_id': snapshot_id,
        'dataset_key': DATASET, 'kind': 'observations', 'source': 'irs_soi',
        'source_release': RELEASE, 'snapshot_at': released,
        'adapter_version': adapter_version, 'adapter': relative_binding(fresh['adapter']),
        'scope': {'type': 'input_row_range', 'start_row': 0, 'end_row_exclusive': rows_read,
                  'total_input_rows': rows_read, 'data_period': '2023',
                  'source_geo_units': {'county': len(sums), 'state_totals_excluded': len(state_totals)},
                  'row_counts': {'observations:county': observations_file['rows']},
                  'derivation': 'sum eight IRS AGI-size bands by county and source variable; no ZIP allocation',
                  'rounding': 'published source band values retained before summation'},
        'completeness': {'complete': True,
                         'basis': 'All 25,552 source rows, 3,143 counties, 51 state totals and eight bands per county checked.'},
        'contract': {'path': contract_copy.name, 'sha256': contract['sha256']},
        'inputs': [relative_binding(item) for item in fresh['source_artifacts']],
        'observations': observations_file, 'quality': quality_file, 'records': None,
    }
    manifest_file = out / 'admission-manifest.json'
    atomic(manifest_file, manifest)
    result = {'status': 'ready', 'manifest': str(manifest_file),
              'manifest_sha256': sha(manifest_file), 'prepared_rows': observations_file['rows'],
              'next_cursor': None, 'complete': True, 'batch_id': batch_id,
              'snapshot_id': snapshot_id}
    atomic(out / 'prepare-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest='command', required=True)
    discovery = command.add_parser('discover')
    discovery.add_argument('--json', action='store_true')
    build = command.add_parser('prepare')
    build.add_argument('--candidate', required=True, type=Path)
    build.add_argument('--out', required=True, type=Path)
    build.add_argument('--max-rows', required=True, type=int)
    build.add_argument('--cursor', default='null')
    args = parser.parse_args()
    try:
        if args.command == 'discover':
            packet = {'status': 'complete', 'candidates': [candidate()], 'blocked': []}
        else:
            packet = prepare(args.candidate, args.out, args.max_rows, json.loads(args.cursor))
        print(json.dumps(packet, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'quarantine', 'reason': type(error).__name__}, sort_keys=True))
        return 65


if __name__ == '__main__':
    raise SystemExit(main())
