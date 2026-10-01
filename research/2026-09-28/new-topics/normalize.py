#!/usr/bin/env python3
"""Rebuild research aggregates from saved extracts, with no network or DB writes."""
from pathlib import Path
import csv
import hashlib
import json
import re

BASE = Path(__file__).resolve().parent
FIPS = dict(line.split('|') for line in '''Alabama|01
Alaska|02
Arizona|04
Arkansas|05
California|06
Colorado|08
Connecticut|09
Delaware|10
District of Columbia|11
Florida|12
Georgia|13
Hawaii|15
Idaho|16
Illinois|17
Indiana|18
Iowa|19
Kansas|20
Kentucky|21
Louisiana|22
Maine|23
Maryland|24
Massachusetts|25
Michigan|26
Minnesota|27
Mississippi|28
Missouri|29
Montana|30
Nebraska|31
Nevada|32
New Hampshire|33
New Jersey|34
New Mexico|35
New York|36
North Carolina|37
North Dakota|38
Ohio|39
Oklahoma|40
Oregon|41
Pennsylvania|42
Rhode Island|44
South Carolina|45
South Dakota|46
Tennessee|47
Texas|48
Utah|49
Vermont|50
Virginia|51
Washington|53
West Virginia|54
Wisconsin|55
Wyoming|56'''.splitlines())


def read(name):
    return json.loads((BASE / 'raw' / name).read_text())


def write_csv(name, rows):
    target = BASE / 'normalized' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def wealth_rows():
    source = read('irs-wealth-2019-table6.web-extract.json')
    rows = []
    for line in source['lines']:
        line = re.sub(r'^L\d+@P15: ', '', line)
        match = re.fullmatch(r'(.+?)\s+(\d[\d,]*|d+)\s*(.*)', line)
        if not match:
            raise ValueError(f'Unexpected IRS row: {line}')
        name, first, rest = match.groups()
        # "Other areas [2]" has a numeric footnote, so parse it explicitly.
        if name == 'Other areas [2]':
            geo_type, geo_id = 'provider_other_areas', 'IRS:other_areas'
        elif name == 'Total':
            geo_type, geo_id = 'provider_total', 'IRS:table6_total'
        else:
            geo_type, geo_id = 'state', FIPS[name]
        if first.startswith('d'):
            count, amount, quality = None, None, 'suppressed'
        else:
            values = [first] + rest.split()
            if len(values) != 10:
                raise ValueError(f'Unexpected IRS field count: {line}')
            count = int(values[2].replace(',', ''))
            amount = int(values[3].replace(',', ''))
            quality = 'estimate'
        rows.append(dict(source_id='irs_personal_wealth_2019', geo_type=geo_type,
                         geo_id=geo_id, geo_name=name, period=2019,
                         threshold_net_worth_usd=11400000,
                         adult_count_estimate=count,
                         net_worth_total_million_usd=amount,
                         quality=quality, source_url=source['source_url']))
    expected_names = set(FIPS) | {'Total', 'Other areas [2]'}
    names = [r['geo_name'] for r in rows]
    if len(names) != len(set(names)) or set(names) != expected_names:
        raise ValueError('IRS table must contain each state, DC, Total and Other exactly once')
    suppressed = {r['geo_name'] for r in rows if r['quality'] == 'suppressed'}
    if suppressed != {'Alaska', 'Rhode Island'}:
        raise ValueError('IRS suppression changed')
    return rows


def loudoun_rows():
    source = read('loudoun-datacenters-2026-03-01.transcription.json')
    expected_districts = ['Algonkian', 'Ashburn', 'Broad Run', 'Catoctin', 'Dulles',
                          'Leesburg', 'Little River', 'Sterling', 'Countywide']
    expected_statuses = {
        'built_or_under_construction', 'site_plan_approved_no_building_permit',
        'site_plan_in_review', 'legislatively_approved_no_active_site_plan',
        'subtotal_approved_no_building_permit', 'total_built_construction_approved',
        'legislative_application_in_review',
    }
    if source['districts'] != expected_districts:
        raise ValueError('Loudoun district ordering or coverage changed')
    statuses = [r['status'] for r in source['rows']]
    if len(statuses) != len(set(statuses)) or set(statuses) != expected_statuses:
        raise ValueError('Loudoun stage coverage changed')
    by_status = {r['status']: r for r in source['rows']}
    rows = []
    for status in source['rows']:
        for field in ('buildings', 'square_feet'):
            values = status[field]
            if len(values) != 9 or any(type(v) is not int or v < 0 for v in values):
                raise ValueError('Invalid Loudoun count/area array')
            if status['components']:
                sums = [sum(by_status[s][field][i] for s in status['components']) for i in range(9)]
                if sums != values:
                    raise ValueError('Loudoun subtotal does not reconcile')
        if sum(status['buildings'][:-1]) != status['buildings'][-1]:
            raise ValueError('Loudoun district building counts do not reconcile')
        if sum(status['square_feet'][:-1]) != status['square_feet'][-1]:
            raise ValueError('Loudoun district areas do not reconcile')
        for i, name in enumerate(source['districts']):
            county = name == 'Countywide'
            # Local names in a dated namespace; these are not official Census IDs.
            geo_id = '51107' if county else 'LOUDOUN:2026-03-01:' + name.upper().replace(' ', '_')
            rows.append(dict(source_id='loudoun_dc_2026_03',
                             geo_type='county' if county else 'local_election_district',
                             geo_id=geo_id, geo_name='Loudoun County' if county else name,
                             period=source['reference_date'], status=status['status'],
                             buildings_estimate=status['buildings'][i],
                             square_feet=status['square_feet'][i],
                             area_quality='derived_zero_from_zero_buildings' if not status['buildings'][i] else 'rounded_to_1000',
                             is_overlapping_total=bool(status['components']),
                             quality='provider_estimate', source_url=source['source_url']))
    keys = [(r['geo_id'], r['period'], r['status']) for r in rows]
    if len(rows) != 63 or len(set(keys)) != len(keys):
        raise ValueError('Loudoun row count or uniqueness failed')
    return rows


def energy_rows():
    source = read('lbnl-2025-update.facts.json')
    return [dict(source_id='lbnl_dc_energy_2025_update', geo_type='nation', geo_id='US',
                 period=2024, metric=r['metric'], value=r['value'], unit=r['unit'],
                 quality='model_estimate', source_url=source['source_url'])
            for r in source['observations']]


def publisher_wealth_rows():
    source = read('ubs-national-wealth.facts.json')
    rows = source['observations']
    keys = [(r['source_id'], r['period'], r['metric']) for r in rows]
    if len(rows) != 2 or len(keys) != len(set(keys)):
        raise ValueError('UBS aggregate coverage changed')
    return [dict(source_id=r['source_id'], geo_type='nation', geo_id='US', period=r['period'],
                 metric=r['metric'], value=r['value'], unit=r['unit'],
                 precision=r['precision'], quality='publisher_estimate',
                 source_url=r['source_url']) for r in rows]


def main():
    wealth = wealth_rows()
    loudoun = loudoun_rows()
    energy = energy_rows()
    publisher_wealth = publisher_wealth_rows()
    counts = {
        'normalized/irs-wealth-2019.csv': write_csv('irs-wealth-2019.csv', wealth),
        'normalized/loudoun-datacenters-2026-03-01.csv': write_csv('loudoun-datacenters-2026-03-01.csv', loudoun),
        'normalized/lbnl-energy-2024.csv': write_csv('lbnl-energy-2024.csv', energy),
        'normalized/ubs-national-wealth.csv': write_csv('ubs-national-wealth.csv', publisher_wealth),
    }
    artifacts = []
    for folder in ('raw', 'normalized'):
        for path in sorted((BASE / folder).glob('*')):
            if not path.is_file():
                continue
            data = path.read_bytes()
            rel = str(path.relative_to(BASE))
            artifacts.append(dict(path=rel, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                  row_count=counts.get(rel),
                                  representation='web_extraction_or_transcription' if folder == 'raw' else 'normalized_aggregate_csv'))
    manifest = dict(schema_version=1, scope='research_only_not_admitted_to_production',
                    retrieved_date='2026-09-28', provider_original_bytes_downloaded=False,
                    original_download_blocker='Sandbox DNS failure; web tool parses PDF/HTML but rejects CSV/XLSX transport',
                    artifacts=artifacts, normalized_rows=sum(counts.values()),
                    checks=dict(irs_rows=len(wealth), irs_suppressed_states=sum(r['quality'] == 'suppressed' for r in wealth),
                                irs_exact_geography_coverage=True,
                                loudoun_rows=len(loudoun), loudoun_district_sums_match_county=True,
                                loudoun_components_match_subtotals=True,
                                loudoun_keys_unique=True,
                                energy_rows=len(energy), publisher_wealth_rows=len(publisher_wealth)),
                    note='Hashes bind local extraction/transcription and CSV bytes, not source PDF/XLSX bytes.')
    (BASE / 'collection-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(normalized_rows=manifest['normalized_rows'], files=counts)))


if __name__ == '__main__':
    main()
