#!/usr/bin/env python3
"""Build a reviewable nationwide discovery plan from current gaps. No network or collector changes."""
import collections
import csv
import datetime
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
FOOD = {'08.01', '08.02', '08.03', '08.06', '09.01', '09.02', '09.03'}


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, obj):
    (BASE / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def main():
    registry = load(BASE / 'registry.json')
    live_path = REPO / 'research/2026-09-28/geography/live-coverage.json'
    contract_path = REPO / 'full/field-contract.json'
    seed_path = REPO / 'research/2026-09-28/local-portals/query-seeds.json'
    live, seeds = load(live_path), load(seed_path)
    groups = {}
    gaps = []
    for field in live['fields']:
        fid = field['field_id']
        if fid in FOOD or field.get('excluded_food'):
            continue
        levels = set(field.get('available_native_levels', []))
        # Coverage includes collected alternatives; preserve their definitions below.
        for variant in field.get('extension_variants', []):
            if isinstance(variant, dict) and variant.get('status', '').startswith('collected'):
                levels.update(variant.get('available_native_levels', []))
        if 'block_group' in levels:
            continue
        seed = seeds.get(fid)
        gaps.append({'field_id': fid, 'label': field['label'], 'desired_geography': 'block_group',
            'available_native_levels_in_snapshot': sorted(levels),
            'source_snapshot_status': field['status'],
            'extension_variants': field.get('extension_variants', []),
            'status': 'planned_search' if seed else 'needs_query_definition',
            'reason': 'Native BG absent from this source snapshot; jurisdiction-specific absence is not established.'})
        if seed:
            groups.setdefault(seed['query'], []).append(fid)
    # New topics are discovery seeds, not assertions that each state publishes them.
    for query, topics in {
        'data center': ['new:data_centers'],
        'company revenue': ['new:companies_revenue_1m_1bn_definition_pending'],
        'net worth': ['07.06', '07.07'],
        'groundwater': ['new:groundwater'],
        'electricity': ['08.05'],
    }.items():
        groups.setdefault(query, []).extend(topics)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    queue = []
    # Round robin: every jurisdiction receives its first keyword before any gets its second.
    for query, fields in sorted(groups.items()):
        for jurisdiction in registry['jurisdictions']:
            catalog = jurisdiction['catalogs'][0]
            key = jurisdiction['jurisdiction_code'].lower() + '-' + hashlib.sha256(query.encode()).hexdigest()[:10]
            queue.append({'job_id': key, 'jurisdiction_code': jurisdiction['jurisdiction_code'],
                'state_fips': jurisdiction['state_fips'], 'catalog_id': catalog['catalog_id'],
                'catalog_url': catalog['catalog_url'], 'catalog_status': jurisdiction['status'],
                'query': query, 'field_ids': sorted(set(fields)),
                'desired_geography': 'block_group', 'fallback_geographies': ['tract', 'county'],
                'status': 'planned_needs_adapter_validation' if jurisdiction['status'] == 'verified_catalog'
                          else 'planned_needs_catalog_resolution',
                'execution_state': 'not_run', 'search_endpoint': catalog['search_endpoint'],
                'cursor': None, 'highwater': None, 'last_attempt_at': None,
                'candidate_count': None, 'response_sha256': None,
                'automatic_collection_allowed': False})
    write('gap-fields.json', {'generated_at': timestamp, 'coverage_source': str(live_path.relative_to(REPO)),
        'coverage_sha256': sha(live_path), 'coverage_captured_at': live.get('captured_at'),
        'contract_sha256': sha(contract_path), 'seed_sha256': sha(seed_path),
        'excluded_food_ids': sorted(FOOD), 'fields': gaps})
    policy = {'deployment_state': 'plan_only_not_installed', 'jurisdictions': 52,
        'ordering': 'round_robin_jurisdictions_then_topics; persist cursor between cycles',
        'max_catalog_requests_per_cycle': 52, 'max_requests_per_provider_per_cycle': 2,
        'cycle_interval_seconds': 21600, 'same_query_min_interval_seconds': 86400,
        'http_timeout_seconds': 30, 'max_attempts_per_request': 3,
        'retry_backoff_seconds': [2, 8], 'honor_retry_after': True,
        'page_size': 20, 'max_pages_per_query': 5, 'max_candidates_per_query': 100,
        'pagination': {
            'ckan': 'rows/start; result.count; require success=true',
            'socrata': 'limit/offset; domains filter and result-domain verification; resultSetSize',
            'arcgis_search': 'num/start and nextStart; official org/group restriction required before use',
            'arcgis_rest_directory': 'bounded folder traversal; review publisher and feature metadata before selecting layers',
            'agency_html': 'manual adapter review; do not invent API URL or scrape person-level records'},
        'collection_gate': 'Only reviewed aggregate dataset schema/license/units/privacy/coverage may join a separate allowlist.',
        'not_available_semantics': 'Zero matching catalog results for a completed bounded query only; never global absence.',
        'source_semantics': ['AGI is not wealth', 'company revenue is not valuation',
            'establishment is not firm', 'NAICS518210 is not every data center',
            'geocoded points are not native Census BG observations',
            'dataset geographic scope is not proven by catalog presence']}
    write('queue-policy.json', policy)
    write('search-queue.json', {'generated_at': timestamp, 'registry_sha256': sha(BASE / 'registry.json'),
        'deployment_state': 'plan_only_not_installed', 'query_groups': len(groups),
        'job_count': len(queue), 'jurisdiction_count': len(registry['jurisdictions']), 'jobs': queue})
    summary = {'checked_at': timestamp, 'inventory_jurisdictions': 52,
        'status_counts': {s: sum(r['status'] == s for r in registry['jurisdictions'])
                          for s in ['verified_catalog', 'official_page_only', 'unresolved']},
        'unverified_api_contracts': 52, 'new_dataset_downloads': 0, 'automatic_collectors_added': 0,
        'prior_local_datasets': 6, 'prior_collection_phase': '2026-09-28/local-portals',
        'queue_gap_fields': len(gaps), 'queue_query_groups': len(groups), 'planned_search_jobs': len(queue),
        'executed_queue_jobs': 0, 'scope': '50 states + DC + PR; catalog inventory, not collected data coverage'}
    write('summary.json', summary)
    with (BASE / 'coverage.csv').open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['jurisdiction_code','state_fips','name','status','catalog_url','platform','search_endpoint','checked_at','evidence_link'])
        for r in registry['jurisdictions']:
            c = r['catalogs'][0]
            writer.writerow([r['jurisdiction_code'],r['state_fips'],r['name'],r['status'],c['catalog_url'],c['platform'],c['search_endpoint'],r['checked_at'],c['evidence_links'][0]])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
