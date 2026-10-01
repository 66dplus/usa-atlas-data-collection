#!/usr/bin/env python3
"""Bounded official TX/CO/WA collection; separate from pinned production scrapers."""
import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_BYTES = 32 * 1024 * 1024
MAX_GROUPS = 20000
PLAN = [
    {'id': 'tx-reservoir-current', 'jurisdiction': 'TX water network (including shared/out-of-state reservoirs)',
     'kind': 'reservoir', 'url': 'https://waterdatafortexas.org/reservoirs/recent-conditions.json',
     'official_provenance': 'https://www.twdb.texas.gov/surfacewater/conditions/index.asp',
     'download_documentation': 'https://waterdatafortexas.org/reservoirs/download',
     'geo_type': 'reservoir_gauge_point', 'boundary_vintage': None,
     'units': {'conservation_storage': 'acre_feet', 'conservation_capacity': 'acre_feet', 'volume': 'acre_feet',
               'elevation': 'feet', 'area': 'acres', 'percent_full': 'percent'},
     'limitations': ['Reservoir storage is not county/tract water availability or water accessible to a specific data center.',
                    'Some reservoirs cross borders; Elephant Butte is in New Mexico. No jurisdiction inferred from bounding box.',
                    'Gauge coordinates are not reservoir boundaries or service territories.',
                    'Flood-control-only reservoirs may have null conservation metrics; preserve null and source tags.',
                    'Texas shares and cross-border accounting require official notes before aggregation.',
                    'No independent live reservoir-count endpoint verified; complete bounded JSON response only.']},
    {'id': 'co-well-permits-county-status', 'jurisdiction': 'CO', 'kind': 'socrata',
     'host': 'data.colorado.gov', 'dataset': 'wumm-7awb', 'owner': 'Division of Water Resources',
     'name': 'DWR Well Application Permit', 'group': ['county', 'current_status'], 'where': None,
     'official_provenance': 'https://dwr.colorado.gov/services/data-information',
     'geo_type': 'provider_county_name', 'boundary_vintage': None,
     'limitations': ['Counts of application/permit source records by current status, not counts of operating wells.',
                    'Permit counts do not measure groundwater reserves, pumping volumes, or sustainable yield.',
                    'County labels retained as published; no unverified FIPS assignment.',
                    'No permit-holder names, residential addresses or individual well locations downloaded.',
                    'Record history and source statuses require interpretation before comparing counties.']},
    {'id': 'wa-electric-vehicles-tract-type', 'jurisdiction': 'WA', 'kind': 'socrata',
     'host': 'data.wa.gov', 'dataset': 'f6w7-q2d2', 'owner': 'Department of Licensing',
     'name': 'Electric Vehicle Population Data', 'group': ['_2020_census_tract', 'county', 'ev_type'],
     'where': "state='WA'", 'geo_type': 'tract', 'boundary_vintage': 2020,
     'official_provenance': 'https://data.wa.gov/Transportation/Electric-Vehicle-Population-Data/f6w7-q2d2',
     'limitations': ['WA registration records for BEV/PHEV; counts are not charging stations, electricity consumption or capacity.',
                    'Restricts source state to WA because the full registration dataset includes out-of-state addresses.',
                    '2020 tract GEOID comes from provider metadata; absent tracts are not automatically zeros.',
                    'No VIN, vehicle ID, owner address or vehicle point coordinates downloaded.',
                    'ODbL terms are preserved in metadata; attribution/license review required before product admission.']},
]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def make_url(base, query):
    return base + '?' + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})


class Fetcher:
    def __init__(self, out, job):
        self.out, self.job, self.requests = out, job, []

    def get(self, url, label, parse_json=True):
        error = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'USAAtlasRegionalResearch/1.0', 'Accept': 'application/json' if parse_json else 'text/html'})
                with urllib.request.urlopen(request, timeout=45) as response:
                    if response.status != 200:
                        raise ValueError('unexpected_http_status:' + str(response.status))
                    body = response.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise ValueError('payload_size_limit')
                    headers = {k: response.headers.get(k) for k in ['Content-Type', 'ETag', 'Last-Modified']}
                    final_url = response.url
                data = json.loads(body) if parse_json else None
                if isinstance(data, dict) and (data.get('error') or data.get('errorCode')):
                    raise ValueError('provider_error_payload:' + str(data)[:400])
                relative = Path('runtime/raw') / self.job / (label + '.gz')
                path = self.out / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                compressed = gzip.compress(body, mtime=0)
                path.write_bytes(compressed)
                item = {'url': url, 'final_url': final_url, 'retrieved_at': now(), 'headers': headers,
                        'body_bytes': len(body), 'body_sha256': digest(body), 'path': str(relative),
                        'gzip_bytes': len(compressed), 'gzip_sha256': digest(compressed)}
                self.requests.append(item)
                save(self.out / 'runtime/raw' / self.job / 'requests.json', self.requests)
                print(f'{self.job}: {label} {len(body)} bytes', flush=True)
                return data
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                error = exc
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in [408, 429, 500, 502, 503, 504]:
                    raise
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise error


def reservoir(job, fetch):
    fetch.get(job['official_provenance'], 'official-source', False)
    fetch.get(job['download_documentation'], 'download-documentation', False)
    data = fetch.get(job['url'], 'conditions')
    if not isinstance(data, dict) or not data:
        raise ValueError('reservoir_dict_expected')
    rows, quality = [], Counter()
    for source_id, item in sorted(data.items()):
        if not isinstance(item, dict) or not {'timestamp', 'full_name', 'gauge_location'} <= set(item):
            raise ValueError('reservoir_schema_changed')
        timestamp = item['timestamp']
        if timestamp is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', timestamp):
            raise ValueError('reservoir_date_format')
        location = item['gauge_location']
        if location:
            coord = location.get('coordinates')
            if location.get('type') != 'Point' or not isinstance(coord, list) or len(coord) != 2 or not (-180 <= coord[0] <= 180 and -90 <= coord[1] <= 90):
                raise ValueError('reservoir_geometry')
        for key in job['units']:
            quality[key + '_missing'] += item.get(key) is None
        rows.append({'source_id': job['id'], 'source_record_id': source_id, 'geo_type': job['geo_type'],
                     'boundary_vintage': None, 'date': timestamp, 'geometry': location, 'attributes': item})
    return rows, {'source_records': len(rows), 'unique_reservoir_ids': len(rows),
                  'points_present': sum(r['geometry'] is not None for r in rows),
                  'observation_dates': sorted({r['date'] for r in rows if r['date']}),
                  'quality': dict(quality), 'independent_source_count_available': False,
                  'numeric_values_not_reinterpreted': True}


def socrata(job, fetch):
    root = 'https://' + job['host']
    metadata_url = root + '/api/views/' + job['dataset'] + '.json'
    data_url = root + '/resource/' + job['dataset'] + '.json'
    before = fetch.get(metadata_url, 'metadata-before')
    if before.get('name') != job['name'] or before.get('owner', {}).get('displayName') != job['owner']:
        raise ValueError('publisher_or_dataset_identity_changed')
    required = set(job['group']) | ({'state'} if job.get('where') else set())
    if required - {c['fieldName'] for c in before['columns']}:
        raise ValueError('source_columns_missing')
    if job['id'].startswith('wa-'):
        column = next(c for c in before['columns'] if c['fieldName'] == '_2020_census_tract')
        if '2020' not in str(column):
            raise ValueError('tract_vintage_no_longer_confirmed')
    count_url = make_url(data_url, {'$select': 'count(*) as source_count', '$where': job.get('where')})
    expected = int(fetch.get(count_url, 'count-before')[0]['source_count'])
    groups = ','.join(job['group'])
    query = {'$select': groups + ',count(*) as source_count', '$group': groups, '$where': job.get('where'),
             '$order': groups, '$limit': MAX_GROUPS}
    raw = fetch.get(make_url(data_url, query), 'aggregates')
    if not isinstance(raw, list) or not raw or len(raw) >= MAX_GROUPS:
        raise ValueError('empty_or_possible_truncated_aggregate')
    rows, keys = [], set()
    missing_count, total = 0, 0
    for item in raw:
        if set(item) - (set(job['group']) | {'source_count'}):
            raise ValueError('unexpected_aggregate_columns')
        key = tuple(item.get(k) for k in job['group'])
        if key in keys:
            raise ValueError('duplicate_aggregate_key')
        keys.add(key)
        if not re.fullmatch(r'\d+', item.get('source_count', '')):
            raise ValueError('noninteger_aggregate_count')
        count = int(item['source_count'])
        total += count
        geo_id = item.get('_2020_census_tract') if job['geo_type'] == 'tract' else item.get('county')
        if job['geo_type'] == 'tract' and geo_id and not re.fullmatch(r'53\d{9}', geo_id):
            raise ValueError('invalid_wa_tract')
        if not geo_id:
            missing_count += count
        rows.append({'source_id': job['id'], 'geo_type': job['geo_type'], 'geo_id': geo_id,
                     'boundary_vintage': job['boundary_vintage'], 'dimensions': {k: item.get(k) for k in job['group']},
                     'count': count, 'count_unit': 'source_records', 'geography_status': 'observed' if geo_id else 'missing'})
    final_count = int(fetch.get(count_url, 'count-after')[0]['source_count'])
    after = fetch.get(metadata_url, 'metadata-after')
    if expected != total or final_count != total or before.get('rowsUpdatedAt') != after.get('rowsUpdatedAt'):
        raise ValueError('source_count_or_revision_changed')
    stats = {'source_records': total, 'aggregate_rows': len(rows), 'unique_nonnull_geographies': len({r['geo_id'] for r in rows if r['geo_id']}),
             'missing_geography_source_records': missing_count,
             'nonnull_county_labels': sorted({r['dimensions']['county'] for r in rows if r['dimensions'].get('county')}),
             'rowsUpdatedAt': before.get('rowsUpdatedAt'), 'metadata_temporal': before.get('metadata', {}).get('custom_fields', {}).get('Temporal'),
             'provider_license': before.get('license'), 'consistency': 'sum of groups equals count before/after; rowsUpdatedAt unchanged',
             'transactional_snapshot_guarantee': False}
    return rows, stats


def collect(out):
    out.mkdir(parents=True, exist_ok=True)
    bindings = {'collector_sha256': digest(Path(__file__).read_bytes()), 'plan_sha256': digest(json.dumps(PLAN, sort_keys=True).encode())}
    summary_path = out / 'collection-summary.json'
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {'jobs': {}}
    if summary.get('bindings') and summary['bindings'] != bindings:
        raise ValueError('bindings_changed_use_new_out')
    summary.update(bindings=bindings, updated_at=now(), status='running', production_admission=False)
    save(out / 'sources.json', PLAN)
    failures = 0
    for job in PLAN:
        previous = summary['jobs'].get(job['id'], {})
        if previous.get('status') == 'complete':
            manifest = json.loads((out / previous['manifest']).read_text())
            artifacts = [(manifest['normalized']['path'], manifest['normalized']['sha256'])] + [(r['path'], r['gzip_sha256']) for r in manifest['requests']]
            if all((out / p).is_file() and digest((out / p).read_bytes()) == sha for p, sha in artifacts):
                print(job['id'] + ': complete cache verified', flush=True)
                continue
            raise ValueError('completed_artifact_corrupt:' + job['id'])
        fetch = Fetcher(out, job['id'])
        summary['jobs'][job['id']] = {'status': 'running', 'started_at': now()}
        save(summary_path, summary)
        try:
            rows, stats = reservoir(job, fetch) if job['kind'] == 'reservoir' else socrata(job, fetch)
            body = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n' for r in rows).encode()
            compressed = gzip.compress(body, mtime=0)
            relative = 'runtime/normalized/' + job['id'] + '.jsonl.gz'
            target = out / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix('.tmp')
            tmp.write_bytes(compressed)
            tmp.replace(target)
            manifest = {**job, 'status': 'complete', 'retrieved_at': now(), 'bindings': bindings, 'production_admission': 'needs_review',
                        'normalized': {'path': relative, 'rows': len(rows), 'bytes': len(compressed), 'sha256': digest(compressed), 'body_sha256': digest(body)},
                        'checks': stats, 'requests': fetch.requests}
            manifest_path = 'manifests/' + job['id'] + '.json'
            save(out / manifest_path, manifest)
            save(out / 'samples' / (job['id'] + '.json'), rows[:3])
            summary['jobs'][job['id']] = {'status': 'complete', 'rows': len(rows), 'checks': stats, 'manifest': manifest_path}
        except Exception as error:
            failures += 1
            summary['jobs'][job['id']] = {'status': 'failed', 'error': type(error).__name__ + ':' + str(error), 'failed_at': now()}
            print(job['id'] + ': FAILED ' + str(error), flush=True)
        summary['updated_at'] = now()
        save(summary_path, summary)
    summary['status'] = 'partial_failed' if failures else 'complete'
    summary['updated_at'] = now()
    save(summary_path, summary)
    return 2 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'runtime').mkdir(exist_ok=True)
    with (args.out / 'runtime/collector.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(collect(args.out.resolve()))
