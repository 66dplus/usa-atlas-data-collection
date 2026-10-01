#!/usr/bin/env python3
"""Collect bounded public PWC data-center building records, with source census checks."""
import collections
import datetime as dt
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
SOURCE = 'https://gisweb.pwcva.gov/arcgis/rest/services/Planning/Build_Out_Analysis/MapServer/9'
SELECT = ['OBJECTID', 'GlobalID', 'BuildingID', 'BuildingStatus', 'YearBuilt',
          'GFA', 'ApprovedGFA', 'PermittedGFA', 'REATaxedGFA', 'BPGFA', 'OCCDate',
          'PermitStatus', 'DCOOD', 'CreateDate', 'LastEditDate']


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def main():
    BASE.mkdir(exist_ok=True)
    lock = (BASE / '.collection.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run = BASE / 'runs' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (run / 'raw').mkdir(parents=True)
    receipts = []
    manifest = {'started_at': now(), 'status': 'running', 'source_url': SOURCE,
        'collector_sha256': sha(Path(__file__).read_bytes()), 'unit': 'data_center_building_record',
        'source_publisher': 'Prince William County Planning Office',
        'publisher_evidence': 'https://www.pwcva.gov/department/planning-office/build-out-analysis/',
        'catalog_evidence': 'https://data.virginia.gov/dataset/data-center-buildings',
        'declared_geographic_scope': 'Prince William County, Virginia',
        'native_geography': 'point', 'census_bg_join_performed': False,
        'production_admission': False, 'projects_layer_included': False,
        'privacy_projection': 'Public-facility IDs, statuses, floor areas, dates and geometry only; names, addresses, creator users excluded.'}
    write(run / 'manifest.json', manifest)

    def get(label, endpoint, params):
        url = endpoint + '?' + urllib.parse.urlencode(params)
        for attempt in range(1, 3):
            receipt = {'label': label, 'url': url, 'attempt': attempt, 'started_at': now()}
            body = None
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'USA-Atlas-PWC-public-building-collection/1.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = response.read(10_000_001)
                    receipt.update(http_status=response.status, final_url=response.url,
                        etag=response.headers.get('ETag'), last_modified=response.headers.get('Last-Modified'))
                if len(body) > 10_000_000:
                    raise ValueError('response exceeds10MB limit')
                value = json.loads(body)
                if value.get('error'):
                    raise ValueError('ArcGIS error: ' + str(value['error']))
                receipt['status'] = 'received'
            except Exception as exc:
                receipt.update(status='error', error=f'{type(exc).__name__}: {exc}',
                    transient_network_error=isinstance(exc, (TimeoutError, ConnectionError)) or (
                        isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)))
                if isinstance(exc, urllib.error.HTTPError):
                    receipt['http_status'] = exc.code
                    receipt['retry_after'] = exc.headers.get('Retry-After')
                    body = exc.read(200000)
                value = None
            if body is not None:
                compressed = gzip.compress(body, mtime=0)
                path = run / 'raw' / f'{len(receipts)+1:03d}-{label}-{sha(body)}.json.gz'
                path.write_bytes(compressed)
                receipt.update(raw_path=str(path.relative_to(BASE)), response_sha256=sha(body),
                    compressed_sha256=sha(compressed), bytes=len(body))
            receipt['completed_at'] = now()
            receipts.append(receipt)
            write(run / 'receipts.json', receipts)
            if value is not None:
                time.sleep(0.2)
                return value
            if attempt == 1 and (receipt.get('transient_network_error') or receipt.get('http_status') in [429, 500, 502, 503, 504]):
                delay = receipt.get('retry_after')
                if delay and (not delay.isdigit() or int(delay) > 30):
                    raise RuntimeError(receipt['error'] + '; defer Retry-After')
                time.sleep(int(delay) if delay else 3)
                continue
            raise RuntimeError(receipt['error'])

    try:
        metadata = get('metadata', SOURCE, {'f': 'json'})
        fields = {f['name']: f for f in metadata['fields']}
        required = {'OBJECTID', 'GlobalID', 'BuildingStatus'}
        if not required <= fields.keys() or metadata['geometryType'] != 'esriGeometryPoint':
            raise ValueError('source schema/geometry differs from reviewed building layer')
        selected = [name for name in SELECT if name in fields]
        manifest.update(source_geometry_type=metadata['geometryType'], selected_fields=selected,
                        field_domains={k: v.get('domain') for k,v in fields.items() if k in selected},
                        editing_info=metadata.get('editingInfo'), source_copyright=metadata.get('copyrightText'))
        before = get('count-before', SOURCE + '/query', {'where': '1=1', 'returnCountOnly': 'true', 'f': 'json'})['count']
        ids_before = get('ids-before', SOURCE + '/query', {'where': '1=1', 'returnIdsOnly': 'true', 'f': 'json'})['objectIds']
        if isinstance(before, bool) or not isinstance(before, int) or not 0 <= before <= 20000:
            raise ValueError('count outside bounded0..20000')
        if len(ids_before) != len(set(ids_before)) or len(ids_before) != before:
            raise ValueError('source count/uniqueID mismatch before collection')
        ids_before.sort()
        features = []
        for start in range(0, len(ids_before), 100):
            chunk = ids_before[start:start+100]
            result = get(f'features-{start//100:03d}', SOURCE + '/query', {
                'objectIds': ','.join(map(str, chunk)), 'outFields': ','.join(selected),
                'returnGeometry': 'true', 'outSR': 4326, 'f': 'json'})
            if result.get('exceededTransferLimit'):
                raise ValueError('source truncated bounded objectID page')
            received = result['features']
            page_ids = [f['attributes']['OBJECTID'] for f in received]
            if len(page_ids) != len(set(page_ids)) or set(page_ids) != set(chunk):
                raise ValueError('source returned missing/duplicate/unrequested IDs')
            features.extend(received)
        after = get('count-after', SOURCE + '/query', {'where': '1=1', 'returnCountOnly': 'true', 'f': 'json'})['count']
        ids_after = get('ids-after', SOURCE + '/query', {'where': '1=1', 'returnIdsOnly': 'true', 'f': 'json'})['objectIds']
        ids_received = [f['attributes']['OBJECTID'] for f in features]
        global_ids = [f['attributes']['GlobalID'] for f in features]
        if before != after or sorted(ids_after) != ids_before or len(ids_received) != len(set(ids_received)):
            raise ValueError('source snapshot changed or duplicate records occurred; do not admit snapshot')
        if any(not g for g in global_ids) or len(global_ids) != len(set(global_ids)):
            raise ValueError('GlobalID missing or duplicated')
        records = []
        for feature in sorted(features, key=lambda f: f['attributes']['OBJECTID']):
            attrs = feature['attributes']
            geom = feature.get('geometry')
            if geom is None or not -180 <= geom.get('x', 999) <= 180 or not -90 <= geom.get('y', 999) <= 90:
                raise ValueError('missing/invalid EPSG4326 point')
            records.append({'source_record_id': attrs['GlobalID'], 'source_object_id': attrs['OBJECTID'],
                'native_geometry_type': 'Point', 'longitude': geom['x'], 'latitude': geom['y'],
                'geometry_crs': 'EPSG:4326', 'attributes': attrs})
        payload = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'id': r['source_record_id'],
            'properties': r['attributes'], 'geometry': {'type': 'Point', 'coordinates': [r['longitude'], r['latitude']]}}
            for r in records]}
        write(run / 'buildings.geojson', payload)
        write(run / 'buildings.normalized.json', records)
        statuses = dict(sorted(collections.Counter(r['attributes'].get('BuildingStatus') or '__NULL__' for r in records).items()))
        artifacts = []
        for name in ['buildings.geojson', 'buildings.normalized.json', 'receipts.json']:
            p = run / name
            artifacts.append({'path': str(p.relative_to(BASE)), 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())})
        manifest.update(status='collected_verified_source_snapshot', completed_at=now(),
            source_count_before=before, source_count_after=after, source_ids_before=len(ids_before),
            source_ids_after=len(ids_after), unique_object_ids=len(set(ids_received)),
            unique_global_ids=len(set(global_ids)), actual_building_records=len(records),
            object_id_pages=(len(ids_before)+99)//100, status_counts=statuses,
            native_point_records=len(records), census_tract_or_bg_observations=0,
            operating_facilities_count=None,
            status_semantics='BuildingStatus preserved verbatim; Completed does not independently prove operational data-center facility count.',
            source_ids_sha256=sha(json.dumps(ids_before).encode()), artifacts=artifacts,
            request_count=len(receipts), license_review='Public official source; review stated reuse terms before downstream publication.')
        write(run / 'manifest.json', manifest)
        write(BASE / 'latest.json', {'run': str(run.relative_to(BASE)), **manifest})
        print(json.dumps(manifest, indent=2), flush=True)
    except Exception as exc:
        manifest.update(status='collection_failed', completed_at=now(), error=f'{type(exc).__name__}: {exc}', request_count=len(receipts))
        write(run / 'manifest.json', manifest)
        write(BASE / 'latest.json', {'run': str(run.relative_to(BASE)), **manifest})
        raise


if __name__ == '__main__':
    main()
