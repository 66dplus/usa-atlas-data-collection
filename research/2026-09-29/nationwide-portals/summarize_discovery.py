#!/usr/bin/env python3
"""Summarize downloaded catalog metadata; does not make requests or admit datasets."""
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.parse

BASE = Path(__file__).resolve().parent


def main():
    latest = json.loads((BASE / 'discovery-latest.json').read_text())
    run = BASE / latest['run']
    queries = [json.loads(p.read_text()) for p in sorted((run / 'queries').glob('*.json'))]
    providers = [json.loads(p.read_text()) for p in sorted((run / 'providers').glob('*.json'))]
    grouped = {}
    topic_counts = collections.Counter()
    for query in queries:
        for candidate in query['candidates']:
            kind = query['adapter']
            key = ('arcgis:' + candidate['id']) if kind == 'hub' else (candidate.get('url') or kind + ':' + candidate['id'])
            item = grouped.setdefault(key, {'key': key, 'catalog_record_id': candidate['id'],
                'title': candidate.get('title'), 'url': candidate.get('url'),
                'adapter': kind, 'catalog_jurisdictions': set(), 'queries': set(),
                'occurrences': 0, 'status': 'needs_review',
                'verified_native_geography': None, 'observation_downloaded_by_discovery': False})
            item['catalog_jurisdictions'].add(query['jurisdiction_code'])
            item['queries'].add(query['query'])
            item['occurrences'] += 1
            topic_counts[query['query']] += 1
    index = []
    for key in sorted(grouped):
        item = grouped[key]
        for field in ['catalog_jurisdictions', 'queries']:
            item[field] = sorted(item[field])
        index.append(item)
    scope_evidence = []
    for p in providers:
        if p.get('adapter') != 'hub':
            continue
        scope = (p.get('scope_metadata') or {}).get('scopes', {}).get('item', {})
        group_ids = set()
        for f in scope.get('filters', []):
            for predicate in f.get('predicates', []):
                groups = predicate.get('group', [])
                if isinstance(groups, dict):
                    groups = groups.get('any', [])
                if isinstance(groups, list):
                    group_ids.update(groups)
        scope_evidence.append({'jurisdiction': p['jurisdiction_code'],
            'scope_metadata_receipt': p.get('scope_metadata_receipt'),
            'configured_item_group_count': len(group_ids), 'group_ids': sorted(group_ids),
            'review_status': 'site_group_filter_configuration_observed' if group_ids else 'scope_unresolved',
            'candidate_geography_verified': False,
            'note': 'Configuration evidence only; item publisher, scope membership and actual geographic coverage require review.'})
    history = []
    for p in sorted((BASE / 'discovery').glob('*/manifest.json')):
        m = json.loads(p.read_text())
        history.append({'run': str(p.parent.relative_to(BASE)), 'started_at': m['started_at'],
            'completed_at': m.get('completed_at'), 'stage': m['stage'],
            'runner_sha256': m['runner_sha256'], 'registry_sha256': m['registry_sha256'],
            'http_attempts': m.get('http_attempts'), 'server_query_pages': m.get('actual_server_catalog_query_pages'),
            'candidate_occurrences': m.get('candidate_occurrences'), 'errors': m.get('errors_requiring_attention')})
    report = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'latest_run': latest['run'], 'latest_manifest_sha256': hashlib.sha256((run / 'manifest.json').read_bytes()).hexdigest(),
        'jurisdictions_attempted': len(providers), 'query_results': len(queries),
        'provider_statuses': latest['provider_statuses'], 'provider_adapters': latest['provider_adapters'],
        'successful_server_catalog_query_pages': latest['actual_server_catalog_query_pages'],
        'local_catalog_listing_filter_jobs': latest['catalog_listing_filter_jobs'],
        'http_attempts': latest['http_attempts'], 'candidate_occurrences': latest['candidate_occurrences'],
        'distinct_catalog_records_after_cross_catalog_hub_id_deduplication': len(index),
        'hub_distinct_catalog_records': sum(x['adapter'] == 'hub' for x in index),
        'catalog_records_found_in_multiple_jurisdiction_catalogs': sum(len(x['catalog_jurisdictions']) > 1 for x in index),
        'candidate_occurrences_by_query': dict(sorted(topic_counts.items())),
        'query_statuses': latest['query_statuses'], 'errors_requiring_attention': latest['errors_requiring_attention'],
        'jurisdictions_with_unresolved_adapters': [p['jurisdiction_code'] for p in providers if p['status'] == 'unresolved_adapter'],
        'jurisdictions_with_html_only': [p['jurisdiction_code'] for p in providers if p['status'] == 'html_catalog_only'],
        'hub_scope_evidence': scope_evidence, 'run_history': history,
        'new_observation_datasets_downloaded_by_discovery': 0, 'production_mutations': 0,
        'count_semantics': 'Catalog records may be maps, dashboards, reports, duplicate views or irrelevant keyword matches. Counts are not usable datasets or geographic coverage.',
        'remaining_pagination': 'Only one page up to10records/query; next_offset recorded, no next-page resume.',
        'candidate_native_bg_coverage_claimed': False}
    for name, data in [('discovery-report.json', report), ('candidate-index.json', index)]:
        (BASE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['hub_scope_evidence','run_history']}, indent=2))


if __name__ == '__main__':
    main()
