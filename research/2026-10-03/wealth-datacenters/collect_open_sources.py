#!/usr/bin/env python3
"""Bounded research collector. Public government sources only; no DB writes.

Run files are immutable. A failed source never supplies a zero observation.
Uses the Python standard library. HTTP timeout 25 s, at most 60 requests,
at most 25 MB per response, at most 10,000 records per GIS layer.
"""
from __future__ import annotations

import csv
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATES = {
    'Alabama': '01', 'Alaska': '02', 'Arizona': '04', 'Arkansas': '05',
    'California': '06', 'Colorado': '08', 'Connecticut': '09', 'Delaware': '10',
    'District of Columbia': '11', 'Florida': '12', 'Georgia': '13', 'Hawaii': '15',
    'Idaho': '16', 'Illinois': '17', 'Indiana': '18', 'Iowa': '19', 'Kansas': '20',
    'Kentucky': '21', 'Louisiana': '22', 'Maine': '23', 'Maryland': '24',
    'Massachusetts': '25', 'Michigan': '26', 'Minnesota': '27', 'Mississippi': '28',
    'Missouri': '29', 'Montana': '30', 'Nebraska': '31', 'Nevada': '32',
    'New Hampshire': '33', 'New Jersey': '34', 'New Mexico': '35', 'New York': '36',
    'North Carolina': '37', 'North Dakota': '38', 'Ohio': '39', 'Oklahoma': '40',
    'Oregon': '41', 'Pennsylvania': '42', 'Rhode Island': '44',
    'South Carolina': '45', 'South Dakota': '46', 'Tennessee': '47', 'Texas': '48',
    'Utah': '49', 'Vermont': '50', 'Virginia': '51', 'Washington': '53',
    'West Virginia': '54', 'Wisconsin': '55', 'Wyoming': '56',
}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Tables(HTMLParser):
    """Retain visible text and attributes from ordinary HTML table cells."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.table, self.row, self.cell = [], None, None, None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.depth == 1 and tag == 'tr':
            self.row = []
        elif self.depth == 1 and tag in ('td', 'th'):
            self.cell = {'text': [], 'tag': tag, 'attrs': dict(attrs)}
        elif self.cell is not None and tag in ('br', 'li', 'div', 'p'):
            self.cell['text'].append(' ')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'].append(data)

    def handle_endtag(self, tag):
        if self.depth == 1 and tag in ('td', 'th') and self.cell is not None:
            self.cell['text'] = ' '.join(''.join(self.cell['text']).split())
            self.row.append(self.cell)
            self.cell = None
        elif self.depth == 1 and tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == 'table':
            if self.depth == 1:
                self.tables.append(self.table)
                self.table = None
            self.depth -= 1


class Collector:
    def __init__(self):
        self.started = utc()
        self.run = ROOT / 'runs' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.run.mkdir(parents=True, exist_ok=False)
        self.receipts, self.observations, self.results = [], [], {}

    def get(self, label, url, params=None):
        if len(self.receipts) >= 60:
            raise RuntimeError('60-request limit reached')
        if params:
            url += '?' + urllib.parse.urlencode(params)
        receipt = {'label': label, 'url': url, 'started_utc': utc()}
        self.receipts.append(receipt)
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'USA-Atlas-Research/2026-10-03 (bounded public-data collector)',
                'Accept-Encoding': 'identity',
            })
            with urllib.request.urlopen(req, timeout=25) as response:
                body = response.read(25_000_001)
                if len(body) > 25_000_000:
                    raise RuntimeError('25 MB response limit')
                if response.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                    if len(body) > 25_000_000:
                        raise RuntimeError('25 MB decoded response limit')
                receipt.update(status=response.status, content_type=response.headers.get('Content-Type'),
                               final_url=response.url)
            digest = hashlib.sha256(body).hexdigest()
            filename = f'{len(self.receipts):03d}-{label}-{digest}.bin.gz'
            target = self.run / 'raw' / filename
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(gzip.compress(body, mtime=0))
            receipt.update(finished_utc=utc(), bytes=len(body), sha256_response_body=digest,
                           artifact=str(target.relative_to(ROOT)),
                           sha256_artifact=hashlib.sha256(target.read_bytes()).hexdigest())
            return body, receipt
        except Exception as error:
            receipt.update(finished_utc=utc(), error=f'{type(error).__name__}: {error}')
            raise

    def get_json(self, label, url, params=None):
        body, receipt = self.get(label, url, params)
        data = json.loads(body)
        if isinstance(data, dict) and data.get('error'):
            raise RuntimeError(f'Provider error: {data["error"]}')
        return data, receipt

    def observe(self, metric, geo_type, geo_id, geo_name, value, unit, source_id,
                receipt, period, quality, note, **extra):
        self.observations.append(dict(
            metric_id=metric, geo_type=geo_type, geo_id=geo_id, geo_name=geo_name,
            value=value, unit=unit, source_id=source_id, observation_period=period,
            retrieved_utc=receipt['finished_utc'], source_url=receipt['url'],
            source_response_sha256=receipt['sha256_response_body'],
            quality_flags=quality, coverage_note=note,
            admission_status='research_only', **extra))

    def epa(self):
        body, receipt = self.get('epa-energy-star', 'https://www.energystar.gov/buildings/certified-data-centers')
        parser = Tables(); parser.feed(body.decode('utf-8'))
        tables = [t for t in parser.tables if t and t[0][0]['text'] == 'Facility Name']
        if len(tables) != 1:
            raise RuntimeError('EPA table contract changed')
        match = re.search(rb'ENERGY STAR Certified Data Centers \((\d+)\)', body)
        if not match:
            raise RuntimeError('EPA published total unavailable')
        published = int(match.group(1))
        rows = tables[0][1:]
        if len(rows) != published or len(rows) > 5000:
            raise RuntimeError(f'EPA count mismatch: {len(rows)} != {published}')
        facilities, keys, counts, annual = [], set(), Counter(), Counter()
        for ordinal, cells in enumerate(rows, 1):
            if len(cells) != 8:
                raise RuntimeError('EPA row width changed')
            name, state, owner, manager, years, area, constructed, certs = [c['text'] for c in cells]
            if state not in STATES and state != 'Puerto Rico':
                raise RuntimeError(f'Unexpected state: {state}')
            key = (state, name.casefold(), owner.casefold())
            if key in keys:
                raise RuntimeError(f'Duplicate EPA descriptive key: {key}')
            keys.add(key)
            years = sorted(set(map(int, re.findall(r'\b(?:19|20)\d{2}\b', years))))
            if not years:
                raise RuntimeError('EPA missing label years')
            # EPA does not publish a stable property ID in this view.
            fingerprint = hashlib.sha256(json.dumps(key).encode()).hexdigest()
            facilities.append(dict(source_record_id=None, descriptive_fingerprint=fingerprint,
                snapshot_row_ordinal=ordinal, facility_name=name, state_name=state,
                state_fips=STATES.get(state), territory_fips='72' if state == 'Puerto Rico' else None,
                owner=owner, property_manager=manager,
                label_years=years, total_floor_space_raw=area,
                year_constructed_raw=constructed, certifications_raw=certs,
                source_url=receipt['url'], retrieved_utc=receipt['finished_utc']))
            if state == 'Puerto Rico':
                continue  # Preserve raw coverage; US territories are outside the requested 51.
            counts[state] += 1
            for year in years:
                annual[state, year] += 1
        dump(self.run / 'epa-facilities.json', facilities)
        for state, count in counts.items():
            self.observe('energy_star_data_center_listed_properties_ever_certified', 'state',
                STATES[state], state, count, 'listed_property_records', 'epa_energy_star',
                receipt, 'certification_history_through_retrieval',
                ['voluntary_certification_subset', 'stable_property_id_unavailable', 'current_operation_not_proven'],
                'One listed property per row; old certifications remain. Excludes unlisted data centers. '
                'Does not measure the total physical facilities currently operating in a state.')
        for (state, year), count in annual.items():
            self.observe('energy_star_data_center_listed_properties_with_label_year', 'state',
                STATES[state], state, count, 'listed_property_records', 'epa_energy_star',
                receipt, str(year), ['voluntary_certification_subset', 'stable_property_id_unavailable'],
                'Unique listed properties with this label year; ENERGY STAR and NextGen may both '
                'appear but a property is counted once per year. 2026 is partial at retrieval.')
        # Only absent registry entries, not population totals, are zero. Keep them out of observations.
        self.results['epa_energy_star'] = dict(status='collected', records=len(facilities),
            records_in_50_states_and_dc=sum(counts.values()), records_in_puerto_rico=1,
            states_with_records=len(counts), state_counts=dict(counts),
            states_with_no_listed_record=[s for s in STATES if s not in counts],
            stable_provider_ids_available=False)

    def texas(self):
        body, receipt = self.get('texas-registered', 'https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php')
        parser = Tables(); parser.feed(body.decode('utf-8'))
        tables = [t for t in parser.tables if t and t[0][0]['text'] == 'Data Center']
        if len(tables) != 2:
            raise RuntimeError('Texas two-program table contract changed')
        projects, groups, all_keys, stem_to_rows = [], {}, set(), defaultdict(list)
        for table, code, label in zip(tables, ('DC', 'LD'), ('qualifying_data_center', 'qualifying_large_data_center_project')):
            keys, rows = set(), table[1:]
            for cells in rows:
                texts = [c['text'] for c in cells]
                row_flags = []
                if len(texts) == 8 and re.fullmatch(r'(?:DC|LD)\d+-OP\d+', texts[-1]):
                    # Current official Pecos Ranch row omits its trailing expiry cell.
                    texts.append('')
                    row_flags.append('missing_exemption_end_date_cell')
                elif len(texts) != 9:
                    raise RuntimeError(f'Texas row width changed: {texts}')
                registrations = sorted(set(re.findall(r'\b(?:DC|LD)\d+-[A-Z]{2}\d+\b', ' '.join(texts))))
                project_ids = sorted(set(x.split('-')[0] for x in registrations))
                if not project_ids:
                    row_flags.append('registration_stem_not_published')
                if any(not x.startswith(code) for x in project_ids):
                    row_flags.append('registration_prefix_differs_from_displayed_program')
                project_id = project_ids[0] if len(project_ids) == 1 else None
                row_key = (label, texts[0].casefold(), texts[1])
                if row_key in keys or row_key in all_keys:
                    raise RuntimeError(f'Duplicate Texas descriptive row: {row_key}')
                keys.add(row_key); all_keys.add(row_key)
                date_flags = []
                try:
                    effective = dt.datetime.strptime(texts[1], '%m/%d/%Y').date().isoformat()
                    if effective > dt.datetime.now(dt.timezone.utc).date().isoformat():
                        date_flags.append('future_effective_date')
                except ValueError:
                    effective = None
                    date_flags.append('malformed_source_effective_date')
                row_fingerprint = hashlib.sha256(json.dumps(row_key).encode()).hexdigest()
                for sid in project_ids:
                    stem_to_rows[sid].append(row_fingerprint)
                projects.append(dict(project_id=project_id, project_id_candidates=project_ids,
                    descriptive_fingerprint=row_fingerprint, program=label, project_name=texts[0],
                    effective_date=effective, effective_date_raw=texts[1], exemption_end_date_raw=texts[8],
                    owner_names=texts[2], owner_registrations_raw=texts[3],
                    occupant_names=texts[4], occupant_registrations_raw=texts[5],
                    operator_names=texts[6], operator_registrations_raw=texts[7],
                    registration_ids=registrations, state_fips='48', county_fips=None,
                    source_url=receipt['url'], retrieved_utc=receipt['finished_utc'],
                    operation_status='not_established_by_this_list',
                    quality_flags=row_flags + date_flags + (['multiple_registration_stems_in_one_row'] if project_id is None else [])))
            groups[label] = len(keys)
            self.observe('texas_listed_' + label + '_project_rows', 'state', '48', 'Texas', len(keys),
                'listed_tax_registry_project_rows', 'texas_comptroller', receipt, 'registry_at_retrieval',
                ['tax_program_subset', 'county_unavailable', 'current_operation_not_proven',
                 'programs_may_overlap', 'source_registration_id_conflicts_require_review'],
                'One displayed project row counted once; owner/operator/occupant roles are not additional projects. '
                'Some source registration stems conflict; count is of published rows rather than confirmed '
                'distinct physical facilities. A large project may contain multiple buildings. Expiry dates are retained.')
        reused = {k:v for k,v in stem_to_rows.items() if len(v)>1}
        for row in projects:
            if any(sid in reused for sid in row['project_id_candidates']):
                row['quality_flags'].append('registration_stem_reused_across_rows')
        dump(self.run / 'texas-projects.json', projects)
        dump(self.run / 'texas-registration-audit.json', dict(
            ambiguous_rows=[r for r in projects if len(r['project_id_candidates']) != 1],
            reused_stem_to_row_fingerprints=reused,
            malformed_dates=[r for r in projects if 'malformed_source_effective_date' in r['quality_flags']],
            policy='Retain displayed rows, flag conflicting registration IDs, do not silently merge distinct named projects.'))
        self.results['texas_comptroller'] = dict(status='collected', records=len(projects), program_counts=groups,
            county_coverage=0, operation_status_known=False,
            rows_with_multiple_registration_stems=sum(r['project_id'] is None for r in projects),
            registration_stems_reused_across_rows=len(reused))

    def loudoun(self):
        base = 'https://services1.arcgis.com/MxjRokvPm7bjslyR/arcgis/rest/services/'
        specs = [
            ('loudoun_existing_parcels', 'Existing_Data_Center_Parcel/FeatureServer/1',
             'OBJECTID_1,PA_MCPI,Data_Center_Status,Built_Status,Overall_SQ_FT,ELECTION_DISTRICT', 'Built_Status'),
            ('loudoun_pipeline_areas', 'Pipeline_Data_Center_Areas/FeatureServer/1',
             'OBJECTID,Application,FIRST_Status,FIRST_Zoning_Case_Num,FIRST_Overall_SQ_FT', 'FIRST_Status'),
            ('loudoun_building_footprints', 'Data_Center_Building_Outlines/FeatureServer/0',
             'FID,Name,Shape_Area', None),
        ]
        for source_id, path, fields, status_field in specs:
            url = base + path
            meta, mr = self.get_json(source_id + '-metadata', url, {'f': 'json'})
            server, _ = self.get_json(source_id + '-service', url.rsplit('/', 1)[0], {'f': 'json'})
            item_id = server.get('serviceItemId')
            item, _ = self.get_json(source_id + '-item',
                'https://www.arcgis.com/sharing/rest/content/items/' + item_id, {'f': 'json'})
            if not str(item.get('owner', '')).endswith('@loudoun.gov_LoudounGIS'):
                raise RuntimeError('Loudoun government provenance check failed')
            ids_before, _ = self.get_json(source_id + '-ids-before', url + '/query',
                {'f': 'json', 'where': '1=1', 'returnIdsOnly': 'true'})
            ids = ids_before['objectIds']; oid = ids_before['objectIdFieldName']
            if not ids or len(ids) > 10000 or len(ids) != len(set(ids)):
                raise RuntimeError('GIS IDs missing, duplicated, or limit exceeded')
            features, feature_receipts = [], []
            for offset in range(0, len(ids), 200):
                data, fr = self.get_json(source_id + '-features-' + str(offset), url + '/query',
                    {'f': 'json', 'objectIds': ','.join(map(str, sorted(ids)[offset:offset + 200])),
                     'outFields': fields, 'returnGeometry': 'true', 'outSR': '4326'})
                if data.get('exceededTransferLimit'):
                    raise RuntimeError('GIS transfer limit exceeded')
                features.extend(data['features']); feature_receipts.append(fr)
            ids_after, _ = self.get_json(source_id + '-ids-after', url + '/query',
                {'f': 'json', 'where': '1=1', 'returnIdsOnly': 'true'})
            obtained = [f['attributes'][oid] for f in features]
            if set(ids) != set(ids_after['objectIds']) or set(obtained) != set(ids) or len(obtained) != len(ids):
                raise RuntimeError('GIS snapshot membership changed or page loss/duplication')
            status_counts = Counter(f['attributes'].get(status_field) or 'not_provided' for f in features)
            dump(self.run / (source_id + '.json'), dict(source_id=source_id, source_url=url,
                source_item_id=item_id, item_license_info=item.get('licenseInfo'),
                source_editing_info=meta.get('editingInfo'), spatial_reference={'wkid':4326},
                county_fips='51107', record_count=len(features), status_counts=dict(status_counts),
                object_id_field=oid, features=features, retrieved_utc=utc(),
                response_body_hashes=[r['sha256_response_body'] for r in feature_receipts]))
            if source_id == 'loudoun_existing_parcels':
                parc = [f['attributes'].get('PA_MCPI') for f in features]
                if None in parc:
                    raise RuntimeError('Parcel ID missing; distinct-parcel counting unavailable')
                grouped = defaultdict(list)
                for feature in features:
                    grouped[feature['attributes']['PA_MCPI']].append(feature)
                distinct_status_counts = Counter()
                for pid, components in grouped.items():
                    statuses = {f['attributes'].get(status_field) or 'not_provided' for f in components}
                    if len(statuses) != 1:
                        raise RuntimeError(f'Conflicting parcel status: {pid} {statuses}')
                    distinct_status_counts[next(iter(statuses))] += 1
                dump(self.run / 'loudoun-parcel-dedup-audit.json', dict(
                    feature_rows=len(features), distinct_parcel_ids=len(grouped),
                    feature_status_counts=dict(status_counts), unique_parcel_status_counts=dict(distinct_status_counts),
                    repeated_parcel_components={pid:fs for pid,fs in grouped.items() if len(fs)>1},
                    policy='Count each PA_MCPI once only when all component statuses agree. '
                    'Retain original geometries and floor-area discrepancies; do not sum area or floor space.'))
                status_counts = distinct_status_counts
            for status, count in status_counts.items():
                self.observe(source_id + '_count_by_source_status', 'county', '51107', 'Loudoun County, Virginia',
                    count, ('building_footprint_records' if not status_field else
                            'distinct_parcel_ids' if source_id == 'loudoun_existing_parcels' else 'pipeline_polygon_records'),
                    source_id, feature_receipts[0],
                    '2024-08' if source_id == 'loudoun_building_footprints' else 'county_layer_snapshot_at_retrieval',
                    ['operation_status_not_proven', 'layers_have_different_vintages', 'snapshot_membership_verified'],
                    'Source statuses retained verbatim. BUILT is not proof of current operation. '
                    'Buildings, existing parcels and pipeline areas must not be added together.',
                    source_status=status, source_last_edit=meta.get('editingInfo', {}).get('lastEditDate'),
                    complete_layer_response_hashes=[r['sha256_response_body'] for r in feature_receipts])
            self.results[source_id] = dict(status='collected', records=len(features), status_counts=dict(status_counts),
                counted_entities=sum(status_counts.values()),
                source_item_id=item_id, county_fips='51107', deepest_geo_admitted='county',
                has_geometry=True, census_spatial_join_done=False,
                source_last_edit=meta.get('editingInfo', {}).get('lastEditDate'))

    def minnesota(self):
        transcription_bytes = (ROOT / 'minnesota-transcription.json').read_bytes()
        transcription = json.loads(transcription_bytes)
        pdf, receipt = self.get('minnesota-deed-list', transcription['source_url'])
        if not pdf.startswith(b'%PDF-'):
            raise RuntimeError('Minnesota response is not PDF')
        if receipt['sha256_response_body'] != transcription['source_response_sha256']:
            raise RuntimeError('Minnesota PDF changed; update and review the dated manual transcription first')
        (self.run/'minnesota-transcription-used.json').write_bytes(transcription_bytes)
        rows = transcription['rows']
        if len(rows) != transcription['expected_rows']:
            raise RuntimeError('Minnesota transcription count mismatch')
        type_counts = Counter(r[2] for r in rows)
        if dict(type_counts) != transcription['expected_type_counts']:
            raise RuntimeError('Minnesota transcription type mismatch')
        keys = [(r[0], r[1], r[2]) for r in rows]
        if len(keys) != len(set(keys)) or any(r[3] != 'Certified' for r in rows):
            raise RuntimeError('Minnesota duplicate row/status mismatch')
        # Join to published Census administrative place/county relationships.
        place_bytes, pr = self.get('census2020-places',
            'https://www2.census.gov/geo/docs/reference/codes2020/national_place2020.txt')
        county_bytes, cr = self.get('census2020-counties',
            'https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt')
        places = list(csv.DictReader(io.StringIO(place_bytes.decode()), delimiter='|'))
        counties = list(csv.DictReader(io.StringIO(county_bytes.decode()), delimiter='|'))
        mn_places = {p['PLACENAME'].removesuffix(' city'):p for p in places if p['STATEFP']=='27'}
        mn_counties = {p['COUNTYNAME']:'27'+p['COUNTYFP'] for p in counties if p['STATEFP']=='27'}
        projects = []
        for ordinal, row in enumerate(rows, 1):
            name, city, typ, status = row
            place = mn_places.get(city)
            if place is None:
                raise RuntimeError(f'Unresolved Minnesota place: {city}')
            county_names = [x.strip() for x in place['COUNTIES'].split('~~~')]
            county_candidates = [mn_counties[n] for n in county_names]
            projects.append(dict(project_name=name, city_source=city, project_type=typ,
                status_source=status, document_row=ordinal, provider_project_id=None,
                place_fips_candidate='27'+place['PLACEFP'], county_fips_candidates=county_candidates,
                administrative_reference_vintage='2020',
                county_assignment_status='candidate_from_published_city_requires_location_validation',
                source_url=receipt['url'], source_response_sha256=receipt['sha256_response_body'],
                retrieved_utc=receipt['finished_utc'], source_date=transcription['source_observation_date']))
        dump(self.run / 'minnesota-designated-projects.json', projects)
        city_counts = Counter(r[1] for r in rows)
        for city, count in city_counts.items():
            self.observe('minnesota_designated_data_center_project_rows', 'provider_city_label',
                'MN:'+city, city+', Minnesota', count, 'designated_tax_exemption_project_rows',
                'minnesota_deed', receipt, transcription['source_observation_date'],
                ['tax_program_subset', 'current_operation_not_proven', 'source_city_label', 'manual_pdf_transcription'],
                'Official City label; facility addresses absent. Candidate Census 2020 place/county '
                'relationships retained separately; county aggregates are withheld until location validation.')
        for typ, count in type_counts.items():
            self.observe('minnesota_designated_data_center_project_rows_by_type', 'state', '27', 'Minnesota',
                count, 'designated_tax_exemption_project_rows', 'minnesota_deed', receipt,
                transcription['source_observation_date'],
                ['tax_program_subset', 'current_operation_not_proven', 'manual_pdf_transcription'],
                'Published Certified project rows; New/Refurbishment is the project type, '
                'and does not establish current operational status.', project_type=typ)
        self.results['minnesota_deed'] = dict(status='collected', records=len(projects),
            project_type_counts=dict(type_counts), source_cities=len(city_counts),
            inferred_candidate_counties=len(set(c for p in projects for c in p['county_fips_candidates'])),
            county_counts_admitted=False, source_date=transcription['source_observation_date'],
            extraction_method='manual_pdf_transcription',
            transcription_sha256=hashlib.sha256(transcription_bytes).hexdigest(),
            geographic_reference_response_hashes=[pr['sha256_response_body'], cr['sha256_response_body']])

    def scf(self):
        body, receipt = self.get('scf2022-extract', 'https://www.federalreserve.gov/econres/files/scfp2022excel.zip')
        macro, macro_receipt = self.get('scf-summary-macro', 'https://www.federalreserve.gov/econres/files/bulletin.macro.txt')
        if b'WGT=X42001/5' not in macro or b'NETWORTH=ASSET-DEBT' not in macro:
            raise RuntimeError('SCF weighting/networth source definitions changed')
        archive = zipfile.ZipFile(io.BytesIO(body))
        members = [x for x in archive.namelist() if x.lower().endswith('.csv')]
        if len(members) != 1:
            raise RuntimeError('SCF archive member contract changed')
        rows = list(csv.DictReader(io.StringIO(archive.read(members[0]).decode('utf-8-sig'))))
        if len(rows) != 22975:
            raise RuntimeError('SCF 2022 public extract expected 22975 implicate records')
        families, implicates = defaultdict(set), defaultdict(list)
        for row in rows:
            family_id, implicate = int(row['YY1']), int(row['Y1']) % 10
            families[family_id].add(implicate); implicates[implicate].append(row)
            if float(row['WGT']) <= 0:
                raise RuntimeError('SCF nonpositive weights')
            if abs(float(row['NETWORTH']) - (float(row['ASSET']) - float(row['DEBT']))) > 1:
                raise RuntimeError('SCF net-worth composition check failed')
        if len(families) != 4595 or any(x != {1,2,3,4,5} for x in families.values()):
            raise RuntimeError('SCF five-implicate family contract failed')
        # In this official SUMMARY extract, WGT already is X42001 / 5.
        count = sum(float(r['WGT']) for r in rows if float(r['NETWORTH']) >= 1_000_000)
        denominator = sum(float(r['WGT']) for r in rows)
        imputed_counts = {str(i): sum(float(r['WGT']) * 5 for r in rs if float(r['NETWORTH']) >= 1_000_000)
                          for i, rs in implicates.items()}
        if not 100_000_000 < denominator < 180_000_000:
            raise RuntimeError('SCF weight-total sanity check failed')
        estimate = dict(count_estimate=count, denominator_families_estimate=denominator,
            percentage_estimate=100 * count / denominator, implicate_count_estimates=imputed_counts,
            surveyed_public_families=len(families), implicate_rows=len(rows),
            source_url=receipt['url'], extract_sha256=receipt['sha256_response_body'],
            macro_url=macro_receipt['url'], macro_sha256=macro_receipt['sha256_response_body'],
            weight_formula='sum(WGT * I(NETWORTH >= 1000000)); WGT = X42001 / 5 in summary extract',
            observation_year=2022, nominal_threshold_usd=1_000_000,
            unit='SCF_primary_economic_unit_families', standard_error=None,
            confidence_interval=None, variance_status='replicate_weight_variance_not_computed',
            quality_flags=['survey_estimate', 'family_not_person', 'national_only', 'includes_residential_equity',
                           'excludes_Forbes_400_from_sampling', 'variance_not_computed', 'research_only'])
        dump(self.run / 'scf-millionaire-families-estimate.json', estimate)
        self.observe('scf_families_net_worth_ge_1m_usd', 'nation', 'US', 'United States',
            count, 'SCF_primary_economic_unit_families_estimate', 'federal_reserve_scf2022',
            receipt, '2022', estimate['quality_flags'],
            'Weighted 2022 estimate of families, including housing equity. Does not count individual '
            'millionaires or provide state/county detail. No sampling confidence interval computed.',
            denominator=denominator, denominator_unit='SCF_primary_economic_unit_families_estimate',
            confidence_interval=None)
        self.results['federal_reserve_scf2022'] = dict(status='collected', count_estimate=count,
            denominator_families_estimate=denominator, percentage_estimate=100 * count / denominator,
            surveyed_public_families=len(families), geography='nation', standard_error_computed=False)

    def run_all(self, selected=None):
        for source, function in [('epa_energy_star', self.epa), ('texas_comptroller', self.texas),
                                 ('loudoun', self.loudoun), ('minnesota_deed', self.minnesota),
                                 ('federal_reserve_scf2022', self.scf)]:
            if selected and source not in selected:
                continue
            start = len(self.observations)
            try:
                function()
            except Exception as error:
                # A source transaction contributes no partial observations after failure.
                del self.observations[start:]
                self.results[source] = {'status':'failed', 'error':f'{type(error).__name__}: {error}'}
            print(json.dumps({source:self.results.get(source,'see_layer_results')}, ensure_ascii=False), flush=True)
        dump(self.run / 'observations.json', self.observations)
        dump(self.run / 'receipts.json', self.receipts)
        manifest = dict(started_utc=self.started, completed_utc=utc(), results=self.results,
            observations=len(self.observations), production_writes=0,
            collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            run_path=str(self.run.relative_to(ROOT)), requests=len(self.receipts),
            artifact_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(self.run.rglob('*')) if p.is_file()})
        dump(self.run / 'manifest.json', manifest)
        dump(ROOT / 'latest.json', manifest)


if __name__ == '__main__':
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument('--sources', nargs='+',
        choices=['epa_energy_star', 'texas_comptroller', 'loudoun', 'minnesota_deed', 'federal_reserve_scf2022'])
    Collector().run_all(argument_parser.parse_args().sources)
