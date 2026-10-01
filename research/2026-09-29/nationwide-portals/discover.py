#!/usr/bin/env python3
"""Bounded public-catalog queries. Downloads metadata only; never production data.

ArcGIS Hub OGC API: https://developers.arcgis.com/hub/services/search/
All candidates require independent publisher/schema/geography review.
"""
import argparse
import collections
import concurrent.futures
import datetime as dt
import email.utils
import fcntl
import gzip
import hashlib
import http.client
from html.parser import HTMLParser
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
PRIORITIES = ['data center', 'electricity', 'water', 'overdose', 'crime']
SOCRATA_HOSTS = {'data.ny.gov','data.colorado.gov','data.ct.gov','data.delaware.gov',
 'data.illinois.gov','data.iowa.gov','opendata.maryland.gov','data.michigan.gov',
 'data.mo.gov','data.nj.gov','data.oregon.gov','data.pa.gov','data.texas.gov',
 'data.vermont.gov','data.wa.gov','opendata.utah.gov','opendata.hawaii.gov'}
LOCK = threading.Lock()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


class Fetch:
    def __init__(self, folder, budget, timeout):
        self.folder, self.budget, self.timeout = folder, budget, timeout
        self.count = 0
        self.receipts = []
        self.folder.mkdir(parents=True, exist_ok=True)

    def get(self, url, params=None, purpose='metadata', expect_json=True):
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
        for attempt in range(2):
            with LOCK:
                if self.count >= self.budget:
                    raise RuntimeError('global HTTP request budget exhausted')
                self.count += 1
                sequence = self.count
            record = {'sequence': sequence, 'url': url, 'purpose': purpose,
                      'attempt': attempt + 1, 'started_at': now()}
            body = None
            try:
                request = urllib.request.Request(url, headers={
                    'User-Agent': 'USA-Atlas-official-catalog-research/1.0',
                    'Accept': 'application/json' if expect_json else 'text/html'})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(5_000_001)
                    record.update(status=response.status, final_url=response.url,
                        content_type=response.headers.get('Content-Type'),
                        etag=response.headers.get('ETag'),
                        last_modified=response.headers.get('Last-Modified'))
                    if len(body) > 5_000_000:
                        raise ValueError('response exceeds bounded 5MB limit')
                value = json.loads(body) if expect_json else body.decode('utf-8', errors='replace')
                if isinstance(value, dict) and value.get('error'):
                    raise ValueError('API error: ' + str(value['error']))
                record['result'] = 'received'
            except Exception as exc:
                record.update(result='error', error=f'{type(exc).__name__}: {exc}',
                    transient_network_error=isinstance(exc, (TimeoutError, ConnectionError, http.client.RemoteDisconnected)) or (
                        isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)))
                if isinstance(exc, urllib.error.HTTPError):
                    record['status'] = exc.code
                    record['retry_after'] = exc.headers.get('Retry-After')
                    body = exc.read(200_000)
                value = None
            if body is not None:
                compressed = gzip.compress(body, mtime=0)
                name = f'{sequence:05d}-{sha(body)}.gz'
                (self.folder / name).write_bytes(compressed)
                record.update(response_sha256=sha(body), file_sha256=sha(compressed),
                              response_bytes=len(body), raw_path=str((self.folder / name).relative_to(BASE)))
            record['completed_at'] = now()
            with LOCK:
                self.receipts.append(record)
                dump(self.folder / 'requests.json', sorted(self.receipts, key=lambda r: r['sequence']))
            if record['result'] == 'received':
                time.sleep(0.15)
                return value, record
            # Auth/URL/schema errors need review; retries cannot fix them.
            if attempt == 0 and (record.get('transient_network_error') or record.get('status') in [429, 500, 502, 503, 504]):
                wait = 4.0
                if record.get('retry_after'):
                    try:
                        wait = max(0, float(record['retry_after']))
                    except ValueError:
                        try:
                            when = email.utils.parsedate_to_datetime(record['retry_after'])
                            wait = max(0, when.timestamp() - time.time())
                        except (ValueError, TypeError):
                            wait = 4.0
                if wait > 60:
                    raise RuntimeError(record['error'] + '; Retry-After exceeds60s; defer to next cycle')
                time.sleep(wait)
                continue
            raise RuntimeError(record['error'])


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.current = [], None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = {'href': dict(attrs).get('href'), 'text': ''}

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            if self.current['href']:
                self.links.append(self.current)
            self.current = None


def candidate(identifier, title, url, publisher=None, **extra):
    return {'id': str(identifier), 'title': title, 'url': url,
        'publisher': publisher, 'status': 'needs_review',
        'publisher_verified': False, 'native_geography': None,
        'production_admission': False, **extra}


def probe(jurisdiction, fetch):
    catalog = jurisdiction['catalogs'][0]
    url = catalog['catalog_url']
    split = urllib.parse.urlsplit(url)
    origin = split.scheme + '://' + split.netloc
    result = {'jurisdiction_code': jurisdiction['jurisdiction_code'],
        'catalog_id': catalog['catalog_id'], 'catalog_url': url,
        'started_at': now(), 'attempts': [], 'status': 'unresolved_adapter'}
    if catalog['platform'] == 'arcgis_rest':
        options = [('arcgis_directory', catalog['search_endpoint'], {'f': 'json'})]
    elif 'ckan' in catalog['platform']:
        options = [('ckan', origin + '/api/3/action/package_search', {'q': 'water', 'rows': 1}),
                   ('hub', origin + '/api/search/v1/collections/all/items', {'limit': 1})]
    elif split.netloc in SOCRATA_HOSTS:
        options = [('socrata', 'https://api.us.socrata.com/api/catalog/v1',
                    {'domains': split.netloc, 'limit': 1}),
                   ('hub', origin + '/api/search/v1/collections/all/items', {'limit': 1})]
    else:
        options = [('hub', origin + '/api/search/v1/collections/all/items', {'limit': 1}),
                   ('ckan', origin + '/api/3/action/package_search', {'q': 'water', 'rows': 1})]
    for kind, endpoint, params in options:
        try:
            data, receipt = fetch.get(endpoint, params, purpose='adapter_probe')
            if kind == 'arcgis_directory':
                valid = isinstance(data, dict) and isinstance(data.get('services'), list)
            elif kind == 'ckan':
                valid = data.get('success') is True and isinstance(data.get('result', {}).get('results'), list)
            elif kind == 'socrata':
                valid = isinstance(data.get('results'), list) and bool(data['results']) and all(
                    r.get('metadata', {}).get('domain') == split.netloc for r in data['results'])
            else:
                valid = data.get('type') == 'FeatureCollection' and isinstance(data.get('features'), list)
                # The endpoint is under the verified catalog host, not a global Hub search.
                if urllib.parse.urlsplit(receipt['final_url']).netloc == 'hub.arcgis.com':
                    valid = False
            if not valid:
                raise ValueError('response schema/domain does not validate adapter')
            result.update(status='validated_metadata_adapter', adapter=kind, endpoint=endpoint,
                          domain=split.netloc, validation_receipt=receipt['sequence'],
                          catalog_scope_verified=kind != 'hub',
                          catalog_scope_status='official_domain_catalog_only_geography_unverified')
            if kind == 'hub':
                result['catalog_scope_status'] = 'needs_review_possible_global_index'
                try:
                    scope, scope_receipt = fetch.get(origin + '/api/search/v1/catalog',
                                                     purpose='hub_scope_metadata')
                    result['scope_metadata_receipt'] = scope_receipt['sequence']
                    result['scope_metadata'] = scope
                except Exception as exc:
                    result['scope_metadata_error'] = str(exc)
                # Site-hosted Hub URLs may expose global results. Human review must verify
                # catalog org/group restrictions against official site configuration.
            if kind == 'arcgis_directory':
                result['_directory'] = data
            return result
        except Exception as exc:
            result['attempts'].append({'adapter': kind, 'endpoint': endpoint, 'error': str(exc)})
    # Some official agency catalogs expose HTML only. Record that separately.
    try:
        html, receipt = fetch.get(url, purpose='official_catalog_html', expect_json=False)
        links = Links()
        links.feed(html)
        result.update(status='html_catalog_only', adapter='html_catalog_scan', endpoint=url,
                      validation_receipt=receipt['sequence'], _links=links.links,
                      _page_sha256=receipt['response_sha256'], catalog_scope_verified=True,
                      catalog_scope_status='official_page_links_only_geography_unverified')
    except Exception as exc:
        result['attempts'].append({'adapter': 'html_catalog_scan', 'endpoint': url, 'error': str(exc)})
    return result


def search(provider, query, fetch, page_size, pages):
    kind = provider.get('adapter')
    result = {'jurisdiction_code': provider['jurisdiction_code'], 'query': query,
        'adapter': kind, 'status': 'needs_review', 'executed_at': now(),
        'candidates': [], 'page_receipts': [], 'http_query_count': 0,
        'native_geography_verified': False,
        'catalog_scope_verified': provider.get('catalog_scope_verified', False),
        'catalog_scope_status': provider.get('catalog_scope_status', 'unresolved'),
        'candidate_geographic_scope_verified': False}
    if not kind:
        return {**result, 'status': 'blocked_adapter', 'error': provider['attempts']}
    try:
        if kind in ['arcgis_directory', 'html_catalog_scan']:
            # Scan the actually fetched official catalog listing. This is not a server search.
            terms = query.lower().split()
            if kind == 'arcgis_directory':
                root = provider['endpoint'].split('/rest/services')[0] + '/rest/services/'
                records = [{'text': s['name'], 'href': root + s['name'] + '/' + s['type']}
                           for s in provider['_directory']['services']]
            else:
                records = provider['_links']
            matches = [r for r in records if all(t in r['text'].lower() for t in terms)]
            result['candidates'] = [candidate(r['href'], r['text'].strip(),
                urllib.parse.urljoin(provider['catalog_url'], r['href'])) for r in matches[:page_size * pages]]
            result.update(search_mode='local_filter_of_fetched_catalog_metadata',
                total_matches_in_fetched_listing=len(matches),
                search_complete=len(matches) <= page_size * pages,
                catalog_receipt=provider['validation_receipt'],
                coverage_note='Only this fetched listing was searched; folders/pages beyond it remain unsearched.')
        else:
            result['search_mode'] = 'server_catalog_query'
            offset = 0
            for page in range(pages):
                if kind == 'socrata':
                    params = {'domains': provider['domain'], 'q': query, 'limit': page_size, 'offset': offset}
                elif kind == 'ckan':
                    params = {'q': query, 'rows': page_size, 'start': offset}
                else:
                    params = {'q': query, 'limit': page_size, 'startindex': offset + 1}
                data, receipt = fetch.get(provider['endpoint'], params, purpose='catalog_search')
                result['page_receipts'].append(receipt['sequence'])
                result['http_query_count'] += 1
                if kind == 'socrata':
                    records = data['results']
                    if any(r['metadata']['domain'] != provider['domain'] for r in records):
                        raise ValueError('Socrata domain mismatch')
                    total = data.get('resultSetSize')
                    found = [candidate(r['resource']['id'], r['resource']['name'], r.get('link'),
                        r.get('owner', {}).get('display_name'),
                        data_url=f"https://{provider['domain']}/resource/{r['resource']['id']}.json",
                        description=(r['resource'].get('description') or '')[:1500]) for r in records]
                elif kind == 'ckan':
                    if data.get('success') is not True:
                        raise ValueError('CKAN query unsuccessful')
                    records = data['result']['results']
                    total = data['result']['count']
                    found = [candidate(r['id'], r['title'],
                        urllib.parse.urljoin(provider['catalog_url'], '/dataset/' + r['name']),
                        (r.get('organization') or {}).get('title'),
                        resources=[{'url': s['url'], 'format': s.get('format')} for s in r.get('resources', [])],
                        description=(r.get('notes') or '')[:1500]) for r in records]
                else:
                    if data.get('type') != 'FeatureCollection':
                        raise ValueError('Hub OGC records schema changed')
                    records = data['features']
                    total = data.get('numberMatched')
                    found = []
                    for record in records:
                        props = record.get('properties', {})
                        links = record.get('links', [])
                        url = props.get('url') or next((l.get('href') for l in links if l.get('rel') in ['item','alternate','self']), None)
                        found.append(candidate(record.get('id'), props.get('title') or props.get('name'), url,
                            props.get('owner'), properties=props, links=links))
                result['candidates'].extend(found)
                offset += len(records)
                result.update(total_catalog_matches=total, next_offset=offset,
                    response_sha256=receipt['response_sha256'],
                    search_complete=len(records) < page_size or (isinstance(total, int) and offset >= total))
                if result['search_complete']:
                    break
        result['status'] = 'candidates_need_review' if result['candidates'] else 'zero_matches_in_bounded_search'
        if result['candidates'] and not result['catalog_scope_verified']:
            result['status'] = 'candidates_need_catalog_scope_review'
    except Exception as exc:
        result.update(status='query_error', error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-requests', type=int, default=600)
    parser.add_argument('--timeout', type=int, default=25)
    parser.add_argument('--page-size', type=int, default=10)
    parser.add_argument('--max-pages', type=int, default=1)
    parser.add_argument('--jurisdictions', help='Comma-separated optional subset; default all52')
    parser.add_argument('--queries', nargs='+', default=PRIORITIES)
    args = parser.parse_args()
    runtime = BASE / 'runtime'
    runtime.mkdir(exist_ok=True)
    lock = (runtime / 'discovery.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('another nationwide discovery process holds the lock')
    registry = json.loads((BASE / 'registry.json').read_text())
    jurisdictions = registry['jurisdictions']
    if args.jurisdictions:
        selected = set(args.jurisdictions.split(','))
        jurisdictions = [j for j in jurisdictions if j['jurisdiction_code'] in selected]
    run = BASE / 'discovery' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run.mkdir(parents=True, exist_ok=True)
    fetch = Fetch(run / 'raw', args.max_requests, args.timeout)
    manifest = {'started_at': now(), 'stage': 'validating_catalog_adapters',
        'jurisdictions_planned': len(jurisdictions), 'priority_queries': args.queries,
        'registry_sha256': sha((BASE / 'registry.json').read_bytes()),
        'runner_sha256': sha(Path(__file__).read_bytes()), 'new_observation_datasets_downloaded': 0,
        'production_mutations': 0, 'arguments': vars(args)}
    dump(run / 'manifest.json', manifest)
    providers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(probe, j, fetch): j for j in jurisdictions}
        for future in concurrent.futures.as_completed(future_map):
            provider = future.result()
            providers.append(provider)
            public = {k: v for k, v in provider.items() if not k.startswith('_')}
            dump(run / 'providers' / (provider['jurisdiction_code'] + '.json'), public)
            print(now(), 'PROVIDER', provider['jurisdiction_code'], provider['status'], provider.get('adapter'), flush=True)
    results = []
    manifest['stage'] = 'searching_metadata'
    dump(run / 'manifest.json', manifest)
    for query in args.queries:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(search, p, query, fetch, args.page_size, args.max_pages) for p in providers]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                name = result['jurisdiction_code'] + '-' + sha(query.encode())[:10] + '.json'
                dump(run / 'queries' / name, result)
                print(now(), 'QUERY', result['jurisdiction_code'], query, result['status'], len(result['candidates']), flush=True)
    manifest.update(completed_at=now(), stage='complete_bounded_metadata_discovery',
        http_attempts=fetch.count, provider_statuses=dict(collections.Counter(p['status'] for p in providers)),
        provider_adapters=dict(collections.Counter(p.get('adapter', 'unresolved') for p in providers)),
        query_results=len(results), query_statuses=dict(collections.Counter(r['status'] for r in results)),
        actual_server_catalog_query_pages=sum(r['http_query_count'] for r in results),
        catalog_listing_filter_jobs=sum(r.get('search_mode') == 'local_filter_of_fetched_catalog_metadata' for r in results),
        candidate_occurrences=sum(len(r['candidates']) for r in results),
        jurisdictions_searched_returning_candidate_records=sorted({r['jurisdiction_code'] for r in results if r['candidates']}),
        candidate_occurrences_needing_catalog_scope_review=sum(len(r['candidates']) for r in results if not r['catalog_scope_verified']),
        verified_local_candidate_occurrences=0,
        errors_requiring_attention={
            'http_error_attempts': sum(r['result'] == 'error' for r in fetch.receipts),
            'unresolved_adapters': sum(p['status'] == 'unresolved_adapter' for p in providers),
            'query_errors': sum(r['status'] == 'query_error' for r in results),
            'blocked_query_jobs': sum(r['status'] == 'blocked_adapter' for r in results)},
        unique_candidate_keys=len({(r['jurisdiction_code'], str(c['id'])) for r in results for c in r['candidates']}))
    dump(run / 'manifest.json', manifest)
    dump(BASE / 'discovery-latest.json', {'run': str(run.relative_to(BASE)), **manifest})
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == '__main__':
    main()
