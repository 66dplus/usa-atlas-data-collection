#!/usr/bin/env python3
"""Admit explicitly monitor-derived 2025 EPA county air concentration statistics.

Each county value is the largest published arithmetic mean among its complete,
qualifying monitors. Counties with no such monitor have no observation. This is
not a countywide exposure estimate, and the EPA county AQI is a different metric.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import gzip
import json
import os
from pathlib import Path
import shutil

import prepare_irs_county_admission as common


ROOT = common.ROOT
HERE = Path(__file__).resolve()
BASE = ROOT / 'full/runtime/public-20260928'
CONTRACT = ROOT / 'full/field-contract.json'
DATASET = 'epa_airdata/2025-county/complete-monitor-max-mean'
RELEASE = 'EPA-AirData-2025-county-monitor-max'
VERSION = 'epa-county-monitor-max-v1'
PROFILES = {
    '88101': {
        'field': '09.06', 'standard': 'PM25 Annual 2024',
        'metric': 'Quarterly Means of Daily Means',
        'durations': {'24-HR BLK AVG', '24 HOUR'},
        'unit': 'Micrograms/cubic meter (LC)',
        'expected_monitors': 1144, 'expected_counties': 555,
    },
    '44201': {
        'field': '09.07', 'standard': 'Ozone 8-hour 2015',
        'metric': 'Daily maximum of 8-hour running average',
        'durations': {'8-HR RUN AVG BEGIN HOUR'},
        'unit': 'Parts per million',
        'expected_monitors': 1146, 'expected_counties': 721,
    },
}


def candidate():
    manifest_path = BASE / 'manifest.json'
    job = json.loads(manifest_path.read_text())['jobs']['epa-monitors-2025']
    if job['status'] != 'source_tables_collected' or job['period'] != '2025' or job['geo'] != 'monitor':
        raise ValueError('epa_source_not_complete_or_wrong_period')
    table = job['table']
    if table['table_rows_including_preserved_headers_when_nested'] != 19584:
        raise ValueError('epa_2025_source_row_count_changed')
    table_file = common.within(BASE / table['path'])
    raw_file = common.within(BASE / job['raw']['path'])
    inputs = [common.bound(table_file, table['sha256']),
              common.bound(raw_file, job['raw']['sha256']),
              common.bound(CONTRACT), common.bound(common.HERE)]
    source_manifest = common.bound(manifest_path)
    adapter = common.bound(HERE)
    result = {
        'dataset_id': DATASET, 'source': 'epa_airdata', 'source_release': RELEASE,
        'snapshot_at': job['raw']['retrieved_at'],
        'source_manifest_path': source_manifest['path'],
        'source_manifest_sha256': source_manifest['sha256'],
        'source_artifacts': inputs, 'input_rows': 19584,
        'source_url': job['url'], 'table_path': str(table_file.relative_to(ROOT)),
        'adapter': adapter,
    }
    result['revision'] = common.digest(result)
    return result


def prepare(candidate_file, out, max_rows, cursor):
    selected = json.loads(common.within(candidate_file).read_text())
    fresh = candidate()
    if selected != fresh:
        raise ValueError('candidate_superseded_or_unregistered')
    if cursor is not None or max_rows < fresh['input_rows']:
        raise ValueError('epa_snapshot_requires_one_complete_batch')
    out = common.within(out)
    out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out).free < 13 * 1024 ** 3:
        raise ValueError('insufficient_preparation_disk_headroom')

    table = common.within(ROOT / fresh['table_path'])
    header = None
    seen = set()
    buckets = {code: {} for code in PROFILES}
    accepted = {code: 0 for code in PROFILES}
    rows_read = 0
    previous_source_row = 0
    required = {'State Code', 'County Code', 'Site Num', 'Parameter Code', 'POC',
                'Sample Duration', 'Pollutant Standard', 'Metric Used', 'Year',
                'Units of Measure', 'Event Type', 'Completeness Indicator', 'Arithmetic Mean'}
    with gzip.open(table, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or ()) != {'source_member', 'source_row', 'cells_json'}:
            raise ValueError('epa_wrapper_columns_changed')
        for row in reader:
            rows_read += 1
            source_row = int(row['source_row'])
            if source_row <= previous_source_row or row['source_member'] != 'annual_conc_by_monitor_2025.csv':
                raise ValueError('epa_source_row_order_changed')
            previous_source_row = source_row
            cells = json.loads(row['cells_json'])
            if rows_read == 1:
                if not isinstance(cells, list) or not required.issubset(cells) or len(set(cells)) != len(cells):
                    raise ValueError('epa_header_changed')
                header = {name: index for index, name in enumerate(cells)}
                continue
            if not isinstance(cells, list) or len(cells) != len(header):
                raise ValueError('epa_row_width_changed')
            cell = lambda name: cells[header[name]]
            code = cell('Parameter Code')
            profile = PROFILES.get(code)
            if profile is None or cell('Pollutant Standard') != profile['standard']:
                continue
            if cell('Year') != '2025':
                raise ValueError('epa_period_mismatch')
            if cell('Metric Used') != profile['metric'] or cell('Units of Measure') != profile['unit'] or cell('Sample Duration') not in profile['durations']:
                raise ValueError('epa_profile_variant_changed')
            if cell('Event Type') != 'No Events' or cell('Completeness Indicator') != 'Y':
                continue
            state, county = cell('State Code'), cell('County Code')
            if state == '80':  # EPA includes a non-US Mexico monitor record.
                continue
            if len(state) != 2 or len(county) != 3 or not (state + county).isdigit() or county == '000':
                raise ValueError('epa_county_fips_invalid')
            key = (code, state, county, cell('Site Num'), cell('POC'))
            if key in seen:
                raise ValueError('epa_duplicate_monitor_profile')
            seen.add(key)
            try:
                value = Decimal(cell('Arithmetic Mean'))
            except InvalidOperation as error:
                raise ValueError('epa_arithmetic_mean_invalid') from error
            if not value.is_finite() or value < 0:
                raise ValueError('epa_arithmetic_mean_nonfinite_or_negative')
            geo = state + county
            bucket = buckets[code].setdefault(geo, [])
            bucket.append(value)
            accepted[code] += 1
    if rows_read != fresh['input_rows']:
        raise ValueError('epa_source_row_count_changed')
    for code, profile in PROFILES.items():
        if accepted[code] != profile['expected_monitors'] or len(buckets[code]) != profile['expected_counties']:
            raise ValueError('epa_qualifying_coverage_changed')
    for item in fresh['source_artifacts']:
        common.bound(ROOT / item['path'], item['sha256'])
    if common.sha(HERE) != fresh['adapter']['sha256']:
        raise ValueError('epa_adapter_changed_during_preparation')

    contract_copy = out / 'field-contract.json'
    shutil.copyfile(CONTRACT, contract_copy)
    os.chmod(contract_copy, 0o600)
    contract = common.bound(contract_copy)
    released = datetime.fromisoformat(fresh['snapshot_at'].replace('Z', '+00:00')).isoformat()

    def observations():
        for code in sorted(PROFILES):
            profile = PROFILES[code]
            for geo, values in sorted(buckets[code].items()):
                yield {
                    'geo_id': geo, 'geo_type': 'county', 'year': '2025',
                    'field_id': profile['field'] + ':' + code + ':county_max_complete_monitor_mean',
                    'catalog_field_id': profile['field'], 'value': float(max(values)),
                    'unit': profile['unit'], 'source': 'epa_airdata',
                    'source_release': RELEASE, 'source_url': fresh['source_url'],
                    'methodology_note': 'EPA AirData annual_conc_by_monitor 2025; '
                        + profile['standard'] + '; ' + profile['metric']
                        + '; No Events; Completeness Indicator Y; maximum published Arithmetic Mean '
                        + 'among ' + str(len(values)) + ' qualifying monitor profile(s) in this county; '
                        + 'monitor-based statistic, not countywide exposure; unmonitored counties omitted.',
                    'retrieved_at': released,
                }

    observations_file = common.write_gzip(out / 'observations.jsonl.gz', observations())
    quality_file = common.write_gzip(out / 'quality.jsonl.gz', ())
    adapter_version = VERSION + ':' + fresh['adapter']['sha256']
    snapshot_id = common.digest({'candidate': fresh['revision'], 'contract': contract['sha256'],
                                 'adapter_version': adapter_version})
    batch_id = common.digest({'snapshot_id': snapshot_id, 'observations': observations_file['sha256'],
                              'quality': quality_file['sha256']})

    def relative_binding(item):
        return {'path': os.path.relpath(ROOT / item['path'], out), 'sha256': item['sha256'],
                'bytes': item['bytes']}

    manifest = {
        'format': 'usa_atlas_admission_v1', 'status': 'complete',
        'batch_id': batch_id, 'snapshot_id': snapshot_id,
        'dataset_key': DATASET, 'kind': 'observations', 'source': 'epa_airdata',
        'source_release': RELEASE, 'snapshot_at': released,
        'adapter_version': adapter_version, 'adapter': relative_binding(fresh['adapter']),
        'scope': {'type': 'input_row_range', 'start_row': 0, 'end_row_exclusive': rows_read,
                  'total_input_rows': rows_read, 'data_period': '2025',
                  'source_geo_units': {'monitor': sum(accepted.values()),
                                       'pm25_counties': len(buckets['88101']),
                                       'ozone_counties': len(buckets['44201'])},
                  'row_counts': {'observations:county': observations_file['rows']},
                  'derivation': 'maximum published Arithmetic Mean across complete matching monitors per county',
                  'geography_limit': 'only counties with a qualifying monitor; not countywide exposure'},
        'completeness': {'complete': True,
                         'basis': 'All 19,584 preserved source rows checked; 1,144 qualifying PM2.5 monitor profiles in 555 counties and 1,146 qualifying ozone profiles in 721 counties.'},
        'contract': {'path': contract_copy.name, 'sha256': contract['sha256']},
        'inputs': [relative_binding(item) for item in fresh['source_artifacts']],
        'observations': observations_file, 'quality': quality_file, 'records': None,
    }
    manifest_file = out / 'admission-manifest.json'
    common.atomic(manifest_file, manifest)
    result = {'status': 'ready', 'manifest': str(manifest_file),
              'manifest_sha256': common.sha(manifest_file), 'prepared_rows': observations_file['rows'],
              'next_cursor': None, 'complete': True, 'batch_id': batch_id,
              'snapshot_id': snapshot_id}
    common.atomic(out / 'prepare-result.json', result)
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
