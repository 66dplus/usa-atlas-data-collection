#!/usr/bin/env python3
"""Derive national employer firm counts from hash-verified Census receipts bins."""
import csv
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT / 'full/runtime/public-20260928'


def derive(job_id, threshold, expected_bins):
    manifest = json.loads((DATA / 'manifest.json').read_text())
    job = manifest['jobs'][job_id]
    if job['status'] != 'source_tables_collected':
        raise ValueError('source_not_complete')
    path = DATA / job['table']['path']
    if hashlib.sha256(path.read_bytes()).hexdigest() != job['table']['sha256']:
        raise ValueError('table_hash_mismatch')
    bins, total = {}, None
    with gzip.open(path, 'rt', newline='') as stream:
        for row in csv.DictReader(stream):
            cells = json.loads(row['cells_json'])
            if len(cells) < 4 or cells[:2] != ['--', 'Total']:
                continue
            label = cells[2].split(': ', 1)[1]
            count = int(cells[3])
            if label == 'Total':
                if total is not None:
                    raise ValueError('duplicate_total')
                total = count
            else:
                if label in bins:
                    raise ValueError('duplicate_bin')
                bins[label] = count
    if len(bins) != expected_bins or sum(bins.values()) != total:
        raise ValueError('incomplete_or_overlapping_bins')
    selected = {}
    for label, count in bins.items():
        if label.startswith('<'):
            continue
        lower = int(label.split('-')[0].rstrip('+').replace(',', '')) * 1000
        if lower >= threshold:
            selected[label] = count
    if not selected or not any(int(b.split('-')[0].rstrip('+').replace(',', '')) * 1000 == threshold for b in selected):
        raise ValueError('threshold_not_aligned_to_source_bins')
    return {
        'metric_id': f'employer_firms_receipts_ge_{threshold}_usd',
        'geo_type': 'nation', 'geo_id': 'US', 'period': '2022',
        'value': sum(selected.values()), 'unit': 'employer_firms',
        'threshold_usd': threshold, 'threshold_measure': 'annual_receipts',
        'universe': 'Census SUSB covered employer firms, all industries',
        'source_url': job['url'], 'source_payload_sha256': job['raw']['sha256'],
        'source_table_sha256': job['table']['sha256'],
        'retrieved_at': job['raw']['retrieved_at'],
        'source_receipt_bin_unit': '1000 USD', 'selected_bins': selected,
        'all_firms_total': total, 'partition_check': 'pass',
        'limitations': ['National only in these receipts-size tables',
                        'Annual receipts do not measure valuation or net worth',
                        'Employer firms and establishments are different units',
                        'Nonemployers and industries outside SUSB coverage are excluded'],
        'production_admission': False,
    }


if __name__ == '__main__':
    observations = [derive('susb-receipts-2022', 1_000_000, 17),
                    derive('susb-large-receipts-2022', 1_000_000_000, 6)]
    target = HERE / 'company-receipts-2022.json'
    target.write_text(json.dumps(observations, indent=2) + '\n')
    print(json.dumps({o['metric_id']: o['value'] for o in observations}))
