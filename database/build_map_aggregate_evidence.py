#!/usr/bin/env python3
"""Reproduce D3/D4 local evidence from the read-only audit and hash-bound IRS files."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
from pathlib import Path

try:
    from .map_aggregates import OREGON_COUNTY_FIPS, US_STATE_FIPS, derive_national_unemployment, derive_oregon_published_agi
    from .map_quality import MetricObservation, summarize_domain
except ImportError:
    from map_aggregates import OREGON_COUNTY_FIPS, US_STATE_FIPS, derive_national_unemployment, derive_oregon_published_agi
    from map_quality import MetricObservation, summarize_domain


GUIDE_URL = 'https://www.irs.gov/pub/irs-soi/23incydocguide.docx'
GUIDE_SHA256 = 'd5cf162d19f08571f1e2e001b1ab314a2ed10ea6642fc766253916342eb26cb7'


def bind(path, expected=None):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError('source_artifact_hash_mismatch: ' + str(path))
    return {'path': str(path), 'sha256': digest, 'bytes': path.stat().st_size}


def irs_evidence(source_root, guide):
    guide_binding = bind(guide, GUIDE_SHA256)
    manifest = json.loads((source_root / 'manifest.json').read_text())
    county_job = manifest['jobs']['irs-county-agi-2023']
    state_job = manifest['jobs']['irs-state-agi-2023']
    artifacts = []
    for job in (county_job, state_job):
        for key in ('raw', 'table'):
            artifacts.append(bind(source_root/job[key]['path'], job[key]['sha256']))
    with gzip.open(source_root/county_job['table']['path'], 'rt', encoding='utf-8-sig', newline='') as stream:
        selected = [row for row in csv.DictReader(stream) if row['STATEFIPS'] == '41']
    cells, totals, invalid, duplicates = {}, {}, [], []
    for row in selected:
        key = (row['STATEFIPS']+row['COUNTYFIPS'], row['agi_stub'])
        target = totals if row['COUNTYFIPS']=='000' else cells
        if key in target:
            duplicates.append(key)
        try:
            value = Decimal(row['A00100'])
            if not value.is_finite():
                raise InvalidOperation()
            target[key] = value
        except InvalidOperation:
            invalid.append({'geo_id': key[0], 'agi_stub': key[1], 'token': row['A00100']})
    expected = {(geo,stub) for geo in OREGON_COUNTY_FIPS for stub in '12345678'}
    if duplicates or set(cells) != expected or len(totals)!=8 or invalid:
        raise ValueError('incomplete_or_invalid_oregon_source_cells')
    county_values = {geo: sum(cells[(geo,stub)] for stub in '12345678') for geo in sorted(OREGON_COUNTY_FIPS)}
    state_total = sum(totals.values())
    with gzip.open(source_root/state_job['table']['path'], 'rt', encoding='utf-8-sig', newline='') as stream:
        candidate = [row for row in csv.DictReader(stream) if row['STATE']=='OR' and row['AGI_STUB']=='0']
    if len(candidate) != 1:
        raise ValueError('ambiguous_native_state_agi_row')
    candidate = {key: candidate[0][key] for key in ('STATE','AGI_STUB','A00100','N1')}
    native_amount = Decimal(candidate['A00100'].replace(',',''))
    return {'source_artifacts': artifacts, 'guide': {**guide_binding, 'url': GUIDE_URL},
            'source_url': county_job['url'], 'period': '2023', 'source_release': 'IRS-SOI-COUNTY-2023',
            'oregon_counties': len(county_values), 'oregon_county_band_cells': len(cells),
            'missing_or_explicit_non_numeric_agi_cells': invalid, 'duplicate_cells': duplicates,
            'county_values_thousand_usd': {key: str(value) for key,value in county_values.items()},
            'same_publication_state_000_total_thousand_usd': str(state_total),
            'county_sum_thousand_usd': str(sum(county_values.values())),
            'zero_agi_band_cells': [{'geo_id': geo,'agi_stub': stub,'source_token': '0.0000'}
                                    for (geo,stub),value in sorted(cells.items()) if value == 0],
            'disclosure_review': {
                'geographic_roster_complete': True, 'underlying_tax_amount_complete': None,
                'policy': ['Under-20-return AGI classes can be combined within county; Excel identifies collapsed classes.',
                           'Under-20-return county items and dominance-protected individual items can be excluded.',
                           'Numeric CSV zero is not proof of an unsuppressed true zero or permission to reconstruct protected cells.',
                           'County publication excludes unmatched/missing ZIP codes and certain non-US return addresses.',
                           'IRS warns county-file state totals may differ from state totals published elsewhere.',
                           'Dollar amounts are in thousands; counts are rounded to nearest ten.']},
            'native_state_candidate': {'source_url': state_job['url'], 'publication': '2023 IRS state table, not admitted',
                                       'raw_row': candidate, 'agi_thousand_usd': str(native_amount),
                                       'difference_county_publication_minus_native_state_thousand_usd': str(state_total-native_amount),
                                       'selected_for_product': False, 'denominator_selected': False}}


def build(audit, source_root, guide):
    packet = json.loads(audit.read_text())
    irs = irs_evidence(source_root, guide)
    def unemployment_row(row):
        count = row['field_id'].split(':')[1]
        rate = count=='unemployment_rate'
        return MetricObservation(metric_id={'unemployment':'unemployment_count','labor_force':'labor_force_count','unemployment_rate':'unemployment_rate'}[count],
            definition_id='bls_laus_'+count+'_v1', field_id=row['field_id'], geo_type=row['geo_type'], geo_id=row['geo_id'],
            period=row['period'], source=row['source'], source_release=row['source_release'],
            unit='%' if rate else 'persons', universe='civilian_noninstitutional_population_age_16_plus',
            value=row['value'], statistic='share' if rate else 'count', adjustment='seasonally_adjusted',
            source_url=row['source_url'], methodology_note=row['methodology_note'])
    all_laus = packet['unemployment_supporting_observations']
    laus = [unemployment_row(row) for row in all_laus if row['geo_id'] in US_STATE_FIPS]
    unemployed = [row for row in laus if row.metric_id=='unemployment_count']
    labor_force = [row for row in laus if row.metric_id=='labor_force_count']
    rates = [row for row in laus if row.metric_id=='unemployment_rate']
    national = derive_national_unemployment(unemployed, labor_force)
    county_rows = packet['oregon_agi_counties']
    for row in county_rows:
        if Decimal(str(row['value'])) != Decimal(irs['county_values_thousand_usd'][row['geo_id']]):
            raise ValueError('live_and_raw_oregon_agi_value_mismatch')
    agi = [MetricObservation(metric_id='published_total_agi', definition_id='irs_county_published_agi_v1',
        field_id=row['field_id'], geo_type='county', geo_id=row['geo_id'], period=row['period'],
        source=row['source'], source_release=row['source_release'], unit=row['unit'],
        universe='published_individual_tax_returns_county_address', value=row['value'], statistic='amount',
        source_url=row['source_url'], methodology_note=row['methodology_note'], provenance_kind='derived',
        geo_vintage='unknown') for row in county_rows]
    derived_agi = derive_oregon_published_agi(agi, disclosure_reviewed=True,
                       source_state_total=float(irs['same_publication_state_000_total_thousand_usd']))
    return {'format':'usa_atlas_map_aggregate_evidence_v1','built_at':datetime.now(timezone.utc).isoformat(),
            'input_audit': bind(audit), 'production_snapshot':packet['snapshot'],
            'national_unemployment':national,
            'excluded_unemployment_source_geographies':sorted({row['geo_id'] for row in all_laus if row['geo_id'] not in US_STATE_FIPS}),
            'unemployment_definition_evidence': {'source_series_prefix':'LASST', 'adjustment':'seasonally_adjusted',
                'definition':'unemployed/civilian labor force age16+ in BLS LAUS; counts, not rounded published rates',
                'methodology_url':'https://www.bls.gov/lau/laumthd.htm',
                'national_distinction':'Official CPS national series not loaded; sum of seasonally adjusted state LAUS counts remains derived. NSA real-time benchmarking does not prove equivalence of this SA aggregate.'},
            'oregon_agi':derived_agi, 'irs_source_review':irs,
            'descriptive_domains':{'unemployment_state':summarize_domain(rates,geo_type='state'),
                                   'published_agi_oregon_county':summarize_domain(agi,geo_type='county')},
            'remaining_product_choice':'Total published AGI versus AGI per return is not selected. Native state and county publication totals stay distinct.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--irs-guide',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    evidence=build(args.audit,args.source_root,args.irs_guide)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':'complete','report':str(args.out)}))


if __name__=='__main__':
    main()
