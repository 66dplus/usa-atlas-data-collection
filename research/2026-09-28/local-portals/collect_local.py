#!/usr/bin/env python3
"""Bounded official-catalog discovery and reviewed, aggregate local collection.

Only sources.json is a collection allowlist. Search results NEVER become collectors.
stdlib only; runtime holds original response bytes (gzip), state, data and logs.
"""
import argparse
import collections
import csv
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import time
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
RUN = BASE / 'runtime'
STOP = False
HEARTBEAT = {}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def heartbeat(phase=None, *, progress=False, **details):
    """Main-thread health signal: sleeping is distinct from collection progress."""
    if not HEARTBEAT:
        stat = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
        HEARTBEAT.update(pid=os.getpid(),
                         boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                         process_start_ticks=int(stat[19]), phase='starting')
    timestamp = now()
    HEARTBEAT['updated_at'] = timestamp
    if progress:
        HEARTBEAT['progress_at'] = timestamp
    if phase is not None:
        HEARTBEAT['phase'] = phase
    HEARTBEAT.update(details)
    dump(RUN / 'heartbeat.json', HEARTBEAT)


def log(message):
    heartbeat(progress=True)
    print(now(), message, flush=True)


class Fetch:
    def __init__(self, folder):
        self.folder = folder
        self.receipts = []
        folder.mkdir(parents=True, exist_ok=True)

    def get(self, url, params=None, as_format='json'):
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
        err = None
        for attempt in range(3):
            if STOP:
                raise RuntimeError('stop requested')
            heartbeat(progress=True)
            try:
                request = urllib.request.Request(url, headers={
                    'User-Agent': 'USA-Atlas-public-aggregate-research/1.0',
                    'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=45) as response:
                    body = response.read(40_000_001)
                    if len(body) > 40_000_000:
                        raise ValueError('response exceeded 40 MB bounded limit')
                    headers = {k: response.headers.get(k) for k in
                               ['ETag', 'Last-Modified', 'Content-Type']}
                    final_url = response.url
                value = json.loads(body) if as_format == 'json' else body
                if isinstance(value, dict) and value.get('error'):
                    raise ValueError(str(value['error']))
                sha = digest(body)
                compressed = gzip.compress(body, mtime=0)
                filename = sha + '.' + as_format + '.gz'
                (self.folder / filename).write_bytes(compressed)
                self.receipts.append({'url': url, 'final_url': final_url,
                    'retrieved_at': now(), 'raw_path': str((self.folder / filename).relative_to(BASE)),
                    'response_sha256': sha, 'file_sha256': digest(compressed),
                    'response_bytes': len(body), 'headers': headers})
                dump(self.folder / 'requests.json', self.receipts)
                heartbeat(progress=True)
                time.sleep(0.12)
                return value
            except Exception as exc:
                err = exc
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f'{url}: {err}')


def arcgis_csv(source, fetch):
    meta = fetch.get(source['metadata_endpoint'], {'f': 'json'})
    fields = {r['name']: r for r in meta['fields']}
    body = fetch.get(source['endpoint'], as_format='csv')
    reader = csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    if set(source['fields']) - set(reader.fieldnames or []):
        raise ValueError('CSV export missing selected columns')
    rows = []
    for raw in reader:
        if None in raw or any(v is None for v in raw.values()):
            raise ValueError('malformed/truncated CSV row')
        a = {key: raw[key] for key in source['fields']}
        for key, value in a.items():
            kind = fields.get(key, {}).get('type', '')
            if value == '':
                a[key] = None
            elif kind in ['esriFieldTypeOID', 'esriFieldTypeInteger', 'esriFieldTypeSmallInteger']:
                a[key] = int(value)
            elif kind in ['esriFieldTypeDouble', 'esriFieldTypeSingle']:
                a[key] = float(value)
        geo_id = a[source['geo_field']]
        if not isinstance(geo_id, str) or len(geo_id) != 12 or not geo_id.startswith('06'):
            raise ValueError(f'invalid CA block-group identifier {geo_id}')
        rows.append({'source_id': source['id'], 'source_record_id': str(a['OBJECTID']),
            'geo_type': source['geo_type'], 'geo_id': geo_id,
            'boundary_vintage': source.get('boundary_vintage'), 'attributes': a})
    if not rows or len(rows) != len({r['source_record_id'] for r in rows}):
        raise ValueError('empty export or duplicate source object IDs')
    if len(rows) != len({r['geo_id'] for r in rows}):
        raise ValueError('duplicate block-group identifiers')
    expected_counties = {'06' + str(n).zfill(3) for n in range(1, 116, 2)}
    actual_counties = {r['geo_id'][:5] for r in rows}
    if actual_counties != expected_counties:
        raise ValueError('export does not cover all 58 CA counties')
    return rows, {'complete_download_response': True, 'parsed_csv_rows': len(rows),
        'unique_geo_ids': len(rows), 'all_58_ca_counties': True,
        'source_expected_rows': None,
        'independent_source_count_available': False,
        'consistency': 'Entire official CSV response parsed; unique GEOIDs and all 58 counties checked. ArcGIS query service unavailable, so independent row count is unverified.',
        'categories': {f: dict(collections.Counter(str(r['attributes'].get(f)) for r in rows))
                       for f in source.get('inspect_categories', [])}}


def arcgis(source, fetch):
    endpoint = source['endpoint']
    meta = fetch.get(endpoint, {'f': 'json'})
    fields = {field['name'] for field in meta['fields']}
    missing = set(source['fields']) - fields
    if missing:
        raise ValueError(f'allowlisted schema changed; missing {sorted(missing)}')
    object_id = meta.get('objectIdField') or meta.get('objectIdFieldName') or 'OBJECTID'
    ids = sorted(fetch.get(endpoint + '/query', {
        'f': 'json', 'where': '1=1', 'returnIdsOnly': 'true'})['objectIds'])
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate source object IDs')
    rows = []
    for start in range(0, len(ids), 500):
        batch = ids[start:start + 500]
        response = fetch.get(endpoint + '/query', {
            'f': 'json', 'objectIds': ','.join(map(str, batch)),
            'outFields': ','.join(dict.fromkeys([object_id] + source['fields'])),
            'returnGeometry': str(source.get('geometry', False)).lower(),
            'outSR': '4326'})
        if response.get('exceededTransferLimit'):
            raise ValueError('ArcGIS response truncated')
        received = [r['attributes'][object_id] for r in response['features']]
        if sorted(received) != batch:
            raise ValueError('requested/received object IDs differ')
        rows.extend(response['features'])
        dump(fetch.folder / 'progress.json', {'expected': len(ids), 'received': len(rows),
            'highwater_object_id': batch[-1], 'updated_at': now()})
        log(f"{source['id']}: {len(rows)}/{len(ids)} rows")
    final_ids = sorted(fetch.get(endpoint + '/query', {
        'f': 'json', 'where': '1=1', 'returnIdsOnly': 'true'})['objectIds'])
    final_meta = fetch.get(endpoint, {'f': 'json'})
    if ids != final_ids or meta.get('editingInfo') != final_meta.get('editingInfo'):
        raise ValueError('source changed during collection; retry next scheduled attempt')
    unique = {f: len({r['attributes'].get(f) for r in rows})
              for f in source.get('inspect_unique_fields', [])}
    summary = {f: dict(collections.Counter(str(r['attributes'].get(f)) for r in rows))
               for f in source.get('inspect_categories', [])}
    out = []
    for row in rows:
        a = row['attributes']
        geo_id = a.get(source.get('geo_field', ''))
        if source['geo_type'] == 'block_group' and (not isinstance(geo_id, str)
                or len(geo_id) != 12 or not geo_id.startswith('06')):
            raise ValueError(f'invalid California BG GEOID {geo_id}')
        out.append({'source_id': source['id'], 'source_record_id': str(a[object_id]),
                    'geo_type': source['geo_type'], 'geo_id': geo_id,
                    'boundary_vintage': source.get('boundary_vintage'),
                    'attributes': a, **({'geometry_wgs84': row.get('geometry')}
                    if source.get('geometry') else {})})
    return out, {'source_expected_rows': len(ids), 'unique_fields': unique,
                 'categories': summary, 'source_editing_info': meta.get('editingInfo'),
                 'consistency': 'IDs before/after and editingInfo match; no transactional snapshot guarantee'}


def socrata(source, fetch):
    meta = fetch.get(source['metadata_endpoint'])
    fields = {r['fieldName'] for r in meta['columns']}
    if set(source['fields']) - fields:
        raise ValueError('Socrata allowlisted field missing')
    count = int(fetch.get(source['endpoint'], {'$select': 'count(*)'})[0]['count'])
    rows = []
    for offset in range(0, count, 2000):
        page = fetch.get(source['endpoint'], {
            '$select': ':id AS source_row_id,' + ','.join(source['fields']),
            '$order': ':id', '$limit': 2000, '$offset': offset})
        rows.extend(page)
        dump(fetch.folder / 'progress.json', {'expected': count, 'received': len(rows),
            'next_offset': offset + len(page), 'updated_at': now()})
    after = fetch.get(source['metadata_endpoint'])
    final_count = int(fetch.get(source['endpoint'], {'$select': 'count(*)'})[0]['count'])
    if (len(rows) != count or count != final_count
            or len({r['source_row_id'] for r in rows}) != count
            or meta.get('rowsUpdatedAt') != after.get('rowsUpdatedAt')):
        raise ValueError('Socrata count/identity/update changed')
    return [{'source_id': source['id'], 'source_record_id': r.pop('source_row_id'),
             'geo_type': source['geo_type'], 'geo_id': r.get('place_of_residence'),
             'attributes': r} for r in rows], {
                 'source_expected_rows': count, 'source_rows_updated_at': meta.get('rowsUpdatedAt'),
                 'years': sorted({r.get('tax_year') for r in rows}),
                 'income_classes': sorted({r.get('income_class') for r in rows}),
                 'disclosure_values': dict(collections.Counter(r.get('disclosure', '(missing)') for r in rows))}


def crime(source, fetch):
    endpoint = source['endpoint']
    fetch.get(endpoint, {'f': 'json'})
    count_params = {'f': 'json', 'where': '1=1', 'returnCountOnly': 'true'}
    count = fetch.get(endpoint + '/query', count_params)['count']
    stat = json.dumps([{'statisticType': 'count', 'onStatisticField': 'OBJECTID',
                        'outStatisticFieldName': 'incident_count'}])
    common = {'f': 'json', 'where': '1=1', 'returnGeometry': 'false', 'outStatistics': stat}
    offenses = fetch.get(endpoint + '/query', {**common, 'groupByFieldsForStatistics': 'OFFENSE'})
    if offenses.get('exceededTransferLimit'):
        raise ValueError('offense list truncated')
    rows = []
    for offense_row in offenses['features']:
        offense = offense_row['attributes']['OFFENSE']
        where = "OFFENSE = '" + offense.replace("'", "''") + "'" if offense else 'OFFENSE IS NULL'
        page = fetch.get(endpoint + '/query', {**common, 'where': where,
            'groupByFieldsForStatistics': 'BLOCK_GROUP,CENSUS_TRACT'})
        if page.get('exceededTransferLimit'):
            raise ValueError('aggregate groups truncated; needs explicit pagination review')
        for row in page['features']:
            a = row['attributes']
            # This ArcGIS service uppercases aggregate aliases in JSON.
            if 'INCIDENT_COUNT' in a:
                a['incident_count'] = a.pop('INCIDENT_COUNT')
            if not isinstance(a.get('incident_count'), int) or a['incident_count'] < 0:
                raise ValueError('unexpected aggregate count field/value')
            a['OFFENSE'] = offense
            key = '|'.join(str(a.get(f)) for f in ['BLOCK_GROUP', 'CENSUS_TRACT', 'OFFENSE'])
            rows.append({'source_id': source['id'], 'source_record_id': key,
                'geo_type': 'provider_block_group', 'geo_id': a.get('BLOCK_GROUP'),
                'boundary_vintage': None, 'attributes': a})
    final_count = fetch.get(endpoint + '/query', count_params)['count']
    summed = sum(r['attributes']['incident_count'] for r in rows)
    if count != final_count or summed != count or len(rows) != len({r['source_record_id'] for r in rows}):
        raise ValueError('crime grouped totals/keys/count-before-after inconsistent')
    return rows, {'source_incidents': count, 'sum_grouped_incidents': summed,
                  'source_offenses': len(offenses['features']),
                  'missing_bg_incidents': sum(r['attributes']['incident_count'] for r in rows if not r['geo_id']),
                  'consistency': 'aggregate sum equals count before/after; source can retrospectively revise assignments'}


def collect(source, state):
    key = source['id']
    folder = RUN / 'raw' / key / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    fetch = Fetch(folder)
    state['collections'][key] = {**state['collections'].get(key, {}),
        'status': 'source_matched', 'started_at': now(), 'last_attempt_epoch': time.time()}
    dump(RUN / 'state.json', state)
    try:
        for provenance in source.get('provenance_endpoints', []):
            fetch.get(provenance)
        rows, checks = {'arcgis': arcgis, 'arcgis_csv': arcgis_csv,
                        'socrata': socrata, 'crime_aggregate': crime}[source['kind']](source, fetch)
        data = ''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n' for r in rows).encode()
        normalized = RUN / 'normalized' / (key + '.jsonl.gz')
        normalized.parent.mkdir(parents=True, exist_ok=True)
        compressed = gzip.compress(data, mtime=0)
        temp = normalized.with_suffix('.tmp')
        temp.write_bytes(compressed)
        temp.replace(normalized)
        manifest = {'source_id': key, 'status': 'source_collected', 'complete': True,
            'retrieved_at': now(), 'endpoint': source['endpoint'], 'rows': len(rows),
            'geo_type': source['geo_type'], 'boundary_vintage': source.get('boundary_vintage'),
            'coverage': source['coverage'], 'release': source['release'],
            'limitations': source['limitations'], 'checks': checks,
            'review_status': source.get('review_status', 'validated_for_aggregate_download'),
            'production_admission': source.get('production_admission', 'needs_review'),
            'normalized_path': str(normalized.relative_to(BASE)),
            'normalized_sha256': digest(data), 'normalized_file_sha256': digest(compressed),
            'raw_requests_path': str((folder / 'requests.json').relative_to(BASE)),
            'request_count': len(fetch.receipts), 'raw_response_bytes': sum(r['response_bytes'] for r in fetch.receipts)}
        dump(BASE / 'manifests' / (key + '.json'), manifest)
        dump(BASE / 'samples' / (key + '.json'), {'sample_only': True, 'full_rows': len(rows), 'rows': rows[:3]})
        state['collections'][key].update(status='source_collected', completed_at=now(),
            last_success_epoch=time.time(), rows=len(rows), manifest=f'manifests/{key}.json', error=None)
        log(f'COLLECTED {key}: {len(rows)} rows')
    except Exception as exc:
        state['collections'][key].update(status='needs_review', error=str(exc), failed_at=now())
        log(f'FAILED {key}: {exc}')
    dump(RUN / 'state.json', state)


def search(portal, query, fetch, cursor):
    term = query['query']
    kind = portal['kind']
    if kind == 'ckan':
        body = fetch.get(portal['api'], {'q': term, 'rows': 20, 'start': cursor})
        if not body.get('success'):
            raise ValueError('CKAN search unsuccessful')
        result = body['result']
        items = [{'id': r['id'], 'title': r['title'],
                  'url': portal['landing'] + '/dataset/' + r['name'],
                  'publisher': (r.get('organization') or {}).get('title'),
                  'resources': [{'url': s['url'], 'format': s.get('format')} for s in r.get('resources', [])]}
                 for r in result['results']]
        total = result['count']
    elif kind == 'socrata':
        body = fetch.get(portal['api'], {'domains': portal['domain'], 'q': term, 'limit': 20, 'offset': cursor})
        if any(r['metadata']['domain'] != portal['domain'] for r in body['results']):
            raise ValueError('Socrata domain filter mismatch')
        items = [{'id': r['resource']['id'], 'title': r['resource']['name'],
                  'url': r.get('link'), 'publisher': r.get('owner', {}).get('display_name'),
                  'data_url': f"https://{portal['domain']}/resource/{r['resource']['id']}.json"}
                 for r in body['results']]
        total = body.get('resultSetSize', len(items))
    elif kind == 'arcgis':
        body = fetch.get(portal['api'], {'f': 'json', 'q': f'orgid:{portal["org_id"]} AND ({term})',
                                       'num': 20, 'start': cursor + 1})
        items = [{'id': r['id'], 'title': r['title'], 'publisher': r['owner'],
                  'url': 'https://www.arcgis.com/home/item.html?id=' + r['id'],
                  'data_url': r.get('url'), 'type': r.get('type')}
                 for r in body['results']]
        total = body['total']
    elif kind == 'dcat':
        body = fetch.get(portal['api'])
        matches = [r for r in body['dataset'] if term.lower() in
                   (r.get('title', '') + ' ' + r.get('description', '')).lower()]
        items = [{'id': r.get('identifier'), 'title': r['title'],
                  'publisher': r.get('publisher'), 'url': r.get('landingPage'),
                  'resources': r.get('distribution', [])} for r in matches[cursor:cursor + 20]]
        total = len(matches)
    else:
        raise ValueError('unreviewed portal adapter')
    return items, total


def discovery(config, sources, state, limit):
    portals = {p['id']: p for p in config['portals']}
    queue = state.setdefault('discovery', {})
    done = 0
    # Never-attempted gaps go first, then oldest attempts; avoids starvation.
    ordered = sorted(config['queries'], key=lambda q: queue.get(q['id'], {}).get('last_attempt_epoch', 0))
    for query in ordered:
        key = query['id']
        old = queue.get(key, {})
        if time.time() - old.get('last_attempt_epoch', 0) < config['query_cadence_seconds']:
            continue
        if done >= limit or STOP:
            break
        done += 1
        portal = portals[query['portal_id']]
        cursor = old.get('next_cursor', 0)
        fetch = Fetch(RUN / 'discovery-raw' / key / str(int(time.time())))
        try:
            items, total = search(portal, query, fetch, cursor)
            matched = [s['id'] for s in sources if s['portal_id'] == portal['id'] and
                       s.get('catalog_id') in {item.get('id') for item in items}]
            for item in items:
                item['status'] = 'source_matched' if any(s.get('catalog_id') == item.get('id') and
                    s['portal_id'] == portal['id'] for s in sources) else 'needs_review'
            status = 'source_matched' if matched else ('needs_review' if items else 'not_available')
            last_cursor = cursor + len(items)
            next_cursor = last_cursor if len(items) == 20 and last_cursor < min(total, 100) else 0
            previous = read(BASE / 'candidates' / (key + '.json'), {}) if cursor else {}
            candidates = {str(r['id']): r for r in previous.get('candidates', [])}
            candidates.update({str(r['id']): r for r in items})
            evidence = {'query': query, 'checked_at': now(), 'status': status,
                'total_catalog_matches': total, 'page_offset': cursor,
                'next_cursor': next_cursor, 'max_search_results_per_cycle': 100,
                'search_complete': last_cursor >= total, 'candidates': list(candidates.values()),
                'meaning': 'not_available means zero matches for this query only; unknown schemas require review',
                'response_sha256': fetch.receipts[-1]['response_sha256']}
            dump(BASE / 'candidates' / (key + '.json'), evidence)
            queue[key] = {k: evidence[k] for k in ['status', 'next_cursor', 'total_catalog_matches', 'response_sha256']}
            queue[key]['last_attempt_epoch'] = time.time()
        except Exception as exc:
            queue[key] = {'status': 'needs_review', 'error': str(exc),
                          'last_attempt_epoch': time.time(), 'next_cursor': cursor}
        log(f'DISCOVERY {key}: {queue[key]["status"]}')
        dump(RUN / 'state.json', state)


def ingest_gaps(config, state):
    """Intake missing native BG coverage; this is not a statement of global unavailability."""
    repo = BASE.parents[2]
    coverage_path = BASE.parent / 'geography' / 'live-coverage.json'
    contract_path = repo / 'full' / 'field-contract.json'
    food = {'08.01', '08.02', '08.03', '08.06', '09.01', '09.02', '09.03'}
    seeds = read(BASE / 'query-seeds.json', {})
    if not coverage_path.exists():
        dump(BASE / 'gap-intake.json', {'status': 'needs_review', 'reason': 'live coverage snapshot absent'})
        return
    coverage_bytes = coverage_path.read_bytes()
    coverage = json.loads(coverage_bytes)
    contract_bytes = contract_path.read_bytes() if contract_path.exists() else b'[]'
    contract = {r['field_id']: r for r in json.loads(contract_bytes)}
    gaps, generated = [], {}
    for field in coverage.get('fields', []):
        field_id = field['field_id']
        if field_id in food or field.get('excluded_food'):
            continue
        levels = set(field.get('available_native_levels', []))
        for variant in field.get('extension_variants', []):
            if isinstance(variant, dict):
                levels.update(variant.get('available_native_levels', []))
        if 'block_group' in levels:
            continue
        seed = seeds.get(field_id)
        ids = []
        if seed:
            for portal_id in seed['portals']:
                identity = f"gap-{portal_id}-" + digest(seed['query'].encode())[:10]
                ids.append(identity)
                item = generated.setdefault(identity, {'id': identity, 'portal_id': portal_id,
                    'query': seed['query'], 'desired_geo': 'block_group', 'field_ids': [],
                    'source': 'live-coverage gap intake', 'food_excluded': True})
                item['field_ids'].append(field_id)
        gaps.append({'field_id': field_id, 'label': field['label'], 'desired_geo': 'block_group',
            'available_native_levels': sorted(levels), 'live_status': field['status'],
            'contract_state': contract.get(field_id, {}).get('planned_state'),
            'native_gap': 'block_group absent from this live source snapshot; other workstreams may have data',
            'status': 'queued' if seed else 'needs_query_definition', 'query_ids': ids,
            'query_states': {q: state.get('discovery', {}).get(q, {}).get('status', 'queued') for q in ids}})
    config['queries'].extend(generated.values())
    dump(BASE / 'gap-intake.json', {'updated_at': now(), 'status': 'active',
        'coverage_source': str(coverage_path.relative_to(repo)), 'coverage_sha256': digest(coverage_bytes),
        'coverage_captured_at': coverage.get('captured_at'), 'contract_sha256': digest(contract_bytes),
        'excluded_food_ids': sorted(food), 'desired_geo': 'block_group', 'gap_fields': len(gaps),
        'generated_unique_queries': len(generated), 'scope_portals': [p['id'] for p in config['portals']],
        'limitations': 'Search candidates do not fill geography gaps until semantic/geographic review and admission. Portal scope is regional, not all US states.',
        'gaps': gaps})


def cycle(args):
    config = read(BASE / 'portals.json', {})
    sources = read(BASE / 'sources.json', [])
    state = read(RUN / 'state.json', {'collections': {}, 'discovery': {}})
    state['pid'] = os.getpid()
    state['cycle_started_at'] = now()
    ingest_gaps(config, state)
    for source in sources:
        if STOP:
            break
        previous = state['collections'].get(source['id'], {})
        cadence = source['cadence_seconds'] if previous.get('status') == 'source_collected' else 21600
        if args.force or time.time() - previous.get('last_attempt_epoch', 0) >= cadence:
            collect(source, state)
    if not STOP:
        discovery(config, sources, state, args.discovery_limit)
    # Refresh query statuses without appending duplicate generated jobs to this cycle.
    ingest_gaps({**config, 'queries': []}, state)
    state['cycle_completed_at'] = now()
    state['running'] = not STOP
    dump(RUN / 'state.json', state)
    dump(BASE / 'status.json', {'updated_at': now(), 'pid': os.getpid(),
         'mode': args.mode, 'runtime_state': 'runtime/state.json',
         'collections': state['collections'], 'discovery': state['discovery']})


def shutdown(signum, frame):
    global STOP
    STOP = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['once', 'daemon', 'status'])
    parser.add_argument('--interval', type=int, default=21600)
    parser.add_argument('--discovery-limit', type=int, default=12)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    if args.mode == 'status':
        print(json.dumps(read(RUN / 'state.json', {}), indent=2))
        return
    lock = (RUN / 'collector.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('another local collector holds collector.lock')
    (RUN / 'collector.pid').write_text(str(os.getpid()) + '\n')
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log(f'START mode={args.mode} pid={os.getpid()}')
    while not STOP:
        heartbeat('cycle', progress=True, next_cycle_at=None)
        try:
            cycle(args)
            heartbeat(progress=True, last_cycle_outcome='success',
                      consecutive_cycle_errors=0, last_error_class=None)
        except Exception as exc:
            heartbeat('cycle_error', last_cycle_outcome='error',
                      consecutive_cycle_errors=HEARTBEAT.get('consecutive_cycle_errors', 0) + 1,
                      last_error_class=type(exc).__name__)
            log(f'CYCLE ERROR: {exc}')
        if args.mode == 'once':
            break
        args.force = False
        until = time.monotonic() + max(args.interval, 60)
        next_cycle = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(args.interval, 60))
        heartbeat('sleeping', next_cycle_at=next_cycle.isoformat())
        next_heartbeat = time.monotonic() + 15
        while not STOP and time.monotonic() < until:
            time.sleep(1)
            if time.monotonic() >= next_heartbeat:
                heartbeat()
                next_heartbeat = time.monotonic() + 15
    state = read(RUN / 'state.json', {})
    state.update(running=False, stopped_at=now())
    dump(RUN / 'state.json', state)
    heartbeat('stopped', progress=True, next_cycle_at=None)
    log('STOP')


if __name__ == '__main__':
    main()
