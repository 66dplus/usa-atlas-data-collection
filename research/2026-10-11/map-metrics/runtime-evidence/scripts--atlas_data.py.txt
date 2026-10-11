"""Read-only PostgreSQL boundary for the local atlas; no ingestion or inferred values."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATE_CODES = dict(zip(
    'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split(),
    '01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 49 50 51 53 54 55 56'.split(),
))
DEFAULT_SERIES = {'03.06': '03.06:unemployment_rate', '04.09': '04.09:violent-crime:yoy',
                  '08.05': '08.05:sector_ALL', '09.02': '09.02:percent'}
# Original units/labels from the collector's USDA FEA 2025 VariableList.csv.
# Preserve stored values: the old UI catalog's per-10k label was incorrect.
USDA = {
    '09.01': ('Fast-food restaurants per 1,000 residents', 'per 1,000 people'),
    '09.02:count': ('Low access to a grocery store · population', 'people'),
    '09.02:percent': ('Low access to a grocery store · population share', '%'),
    '09.03': ("Farmers’ markets per 1,000 residents", 'per 1,000 people'),
    '09.04': ('Recreation & fitness facilities per 1,000 residents', 'per 1,000 people'),
}
SOURCE_NAMES = {'bls_laus': 'BLS LAUS', 'bea_rpp': 'BEA Regional Price Parities',
                'fbi_cde': 'FBI Crime Data Explorer', 'cdc_places': 'CDC PLACES',
                'eia': 'EIA Electricity', 'usda_fea': 'USDA Food Environment Atlas'}


class DatabaseUnavailable(RuntimeError):
    pass


def query(sql, variables=None, *, statement_timeout_ms=8000):
    env = {**os.environ, 'PGCONNECT_TIMEOUT': '3',
           'PGAPPNAME': 'usa_atlas_ui',
           'PGOPTIONS': f'-c default_transaction_read_only=on -c statement_timeout={statement_timeout_ms}'}
    args = ['psql', '-X', '-w', '-qAt', '--dbname', 'usa_atlas', '--set', 'ON_ERROR_STOP=1']
    for name, value in (variables or {}).items():
        args.extend(['--set', f'{name}={value}'])
    try:
        result = subprocess.run(args, input='BEGIN READ ONLY;\n' + sql + ';\nCOMMIT;\n',
                                text=True, capture_output=True, timeout=statement_timeout_ms / 1000 + 4, env=env)
        if result.returncode:
            raise DatabaseUnavailable('PostgreSQL is unavailable. Check the configured database connection and retry.')
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise DatabaseUnavailable('PostgreSQL is unavailable. Check the configured database connection and retry.') from error


ACS_SERIES = json.loads((ROOT / 'ux/acs-series.json').read_text())['variables']


def series_label(base, field):
    variable = field.split(':', 1)[-1]
    if variable in ACS_SERIES:
        metadata = ACS_SERIES[variable]
        return metadata['concept'] + ' · ' + metadata['label']
    if field in USDA:
        return USDA[field][0]
    if field.startswith('03.06:'):
        return {'employment': 'Employment · people', 'labor_force': 'Labor force · people',
                'unemployment': 'Unemployment · people', 'unemployment_rate': 'Unemployment rate'}.get(field.split(':')[1], base + ' · ' + field.split(':', 1)[1].replace('_', ' '))
    if field.startswith('08.05:sector_'):
        sector = field.split('_')[-1]
        return base + ' · ' + {'ALL': 'All sectors', 'RES': 'Residential', 'COM': 'Commercial',
                              'IND': 'Industrial', 'TRA': 'Transportation'}.get(sector, sector)
    if field.startswith('04.09:'):
        return 'Crime trends · ' + field.split(':')[1].replace('-', ' ') + ' · year over year'
    return base if ':' not in field else base + ' · ' + field.split(':', 1)[1].replace('_', ' ')


def catalog():
    # Probe each indexed (catalog, geography) range, skipping large tract/block-group
    # ranges. All probes still use the reader-granted view and passed ingests only.
    # Exact all-geography counts require scanning production's large observation view;
    # null means uncounted, never a fabricated zero or an ingest row_count sum.
    data = query("""
      WITH RECURSIVE inventory(catalog_field_id,geo_type) AS (
        SELECT c.catalog_field_id,o.geo_type FROM usa_atlas.catalog_field c
        CROSS JOIN LATERAL (
          SELECT o.geo_type FROM usa_atlas.observation o
          JOIN usa_atlas.ingest_run i USING(ingest_id)
          WHERE o.catalog_field_id=c.catalog_field_id AND i.status='pass'
          ORDER BY o.geo_type LIMIT 1
        ) o
        UNION ALL
        SELECT p.catalog_field_id,o.geo_type FROM inventory p
        CROSS JOIN LATERAL (
          SELECT o.geo_type FROM usa_atlas.observation o
          JOIN usa_atlas.ingest_run i USING(ingest_id)
          WHERE o.catalog_field_id=p.catalog_field_id AND o.geo_type>p.geo_type AND i.status='pass'
          ORDER BY o.geo_type LIMIT 1
        ) o
      ), geographies AS (
        SELECT catalog_field_id,array_agg(geo_type ORDER BY geo_type) geographies
        FROM inventory GROUP BY catalog_field_id
      ), series AS (
        SELECT c.catalog_field_id,o.* FROM usa_atlas.catalog_field c
        CROSS JOIN LATERAL (
          SELECT o.field_id,bool_or(o.geo_type='state') state_supported,
            bool_or(o.geo_type='county') county_supported
          FROM usa_atlas.observation o JOIN usa_atlas.ingest_run i USING(ingest_id)
          WHERE o.catalog_field_id=c.catalog_field_id
            AND o.geo_type IN ('state','county') AND i.status='pass'
          GROUP BY o.field_id
        ) o
      )
      SELECT json_build_object(
        'fields',(SELECT json_agg(t ORDER BY catalog_field_id) FROM (
          SELECT c.catalog_field_id,c.catalog_label,c.planned_state,c.contract,
            CASE WHEN g.geographies IS NULL THEN 0 ELSE NULL END rows,
            COALESCE(g.geographies,ARRAY[]::text[]) geographies
          FROM usa_atlas.catalog_field c LEFT JOIN geographies g USING(catalog_field_id)) t),
        'series',(SELECT COALESCE(json_agg(s ORDER BY field_id),'[]'::json) FROM series s))
    """, statement_timeout_ms=20000)
    field_rows = data['fields']
    fields = {row['catalog_label']: row for row in field_rows}
    original = json.loads((ROOT / 'ux/catalog.json').read_text())['metrics']
    proposals = json.loads((ROOT / 'ux/catalog-proposals.json').read_text())
    proposed = proposals['metrics']
    v2 = json.loads((ROOT / 'ux/catalog-v2.json').read_text())
    original_names = {m['name'] for m in original}
    v2_metrics = v2['metrics']
    v2_by_id = {m['catalogId']: m for m in v2_metrics}
    row_ids = [row['catalog_field_id'] for row in field_rows]
    base_ids = [m['id'] for m in original]
    proposal_ids = [m['id'] for m in proposed]
    if (len(fields) != len(field_rows) or len(set(row_ids)) != len(row_ids) or
            len(original_names) != len(original) or len(set(base_ids + proposal_ids)) != len(base_ids) + len(proposal_ids) or
            proposals['baseCatalogCount'] != len(original) or
            len(v2_metrics) != 6 or len(v2_by_id) != 6 or
            len(set(base_ids + [m['id'] for m in v2_metrics])) != len(base_ids) + len(v2_metrics) or
            v2.get('baseCatalogCount') != len(original) or v2.get('catalogCount') != len(original) + 6):
        raise DatabaseUnavailable('The database catalog does not match this atlas catalog.')
    extra_ids = set(v2_by_id)
    expected_parent_fields = {item['catalogId']: item['catalogLabel'] for item in v2.get('parentFields', [])}
    expected_parent_ids = set(expected_parent_fields)
    legacy_parent_ids = expected_parent_ids - extra_ids
    base_ids_by_label = {row['catalog_label']: row['catalog_field_id'] for row in field_rows}
    legacy_fields = (set(base_ids_by_label) == original_names and len(field_rows) == len(original) and
                     set(row_ids) == legacy_parent_ids and
                     all(expected_parent_fields[row['catalog_field_id']] == row['catalog_label']
                         for row in field_rows))
    v2_fields = (len(field_rows) == len(original) + len(v2_metrics) and
                 len(expected_parent_ids) == len(original) + len(v2_metrics) and
                 set(row_ids) == expected_parent_ids and
                 all(expected_parent_fields[row['catalog_field_id']] == row['catalog_label']
                     for row in field_rows) and
                 set(base_ids_by_label) == original_names | {m['catalogLabel'] for m in v2_metrics} and
                 extra_ids == {m['catalogId'] for m in v2_metrics} and
                 all(base_ids_by_label.get(m['catalogLabel']) == m['catalogId'] for m in v2_metrics))
    if legacy_fields:
        version_metrics = proposed
        published_count = len(original)
    elif v2_fields:
        version_metrics = v2_metrics
        published_count = len(original) + len(v2_metrics)
    else:
        raise DatabaseUnavailable('The database catalog does not match this atlas catalog.')
    metrics = []
    base_rows = [(base, fields[base['name']]) for base in original]
    if v2_fields:
        fields_by_id = {row['catalog_field_id']: row for row in field_rows}
        base_rows.extend((metadata, fields_by_id[metadata['catalogId']]) for metadata in v2_metrics)
    for base, field in base_rows:
        choices = [s for s in data['series'] if s['catalog_field_id'] == field['catalog_field_id']]
        default = DEFAULT_SERIES.get(field['catalog_field_id'], field['catalog_field_id'])
        if choices and default not in {s['field_id'] for s in choices}:
            default = next((choice['field_id'] for choice in choices
                            if re.fullmatch(r'[0-9]{2}\.[0-9]{2}:B[0-9]{5}_[0-9]{3}E', choice['field_id'])), choices[0]['field_id'])
        for choice in choices or [None]:
            m = {**base, 'catalogId': field['catalog_field_id'], 'observations': field['rows'],
                 'hasObservations': bool(field['geographies']),
                 'geographies': field['geographies'], 'plannedState': field['planned_state']}
            m.update(availability='loaded' if choice else 'unavailable',
                     stateSupported=bool(choice and choice['state_supported']),
                     countySupported=bool(choice and choice['county_supported']),
                     fieldId=choice['field_id'] if choice else None)
            if choice:
                m['name'] = series_label(base['name'], choice['field_id'])
                if choice['field_id'] != default:
                    m['id'] += '--' + re.sub(r'[^a-z0-9]+', '-', choice['field_id'].lower()).strip('-')
            m['coverageNote'] = ('Available from PostgreSQL; select a place for its observation.' if choice else
                'Collected at ' + ', '.join(field['geographies']) + ' level; no state/county allocation is inferred.' if field['geographies'] else
                'No observations have been loaded for this indicator.')
            metrics.append(m)
    if legacy_fields:
        for proposal in proposed:
            metrics.append({**proposal, 'availability': 'unavailable', 'plannedState': 'proposed',
                            'observations': 0, 'hasObservations': False, 'geographies': [], 'stateSupported': False,
                            'countySupported': False, 'fieldId': None,
                            'coverageNote': proposal['note'] + ' No observations have been loaded.'})
    return {'metrics': metrics, 'catalogCount': len(original) + len(version_metrics),
            'publishedCatalogCount': published_count,
            'availableSeries': len(data['series']), 'observationCount': (sum(f['rows'] for f in fields.values())
                if all(f['rows'] is not None for f in fields.values()) else None)}


def canonical_geo(source, kind, identifier):
    if kind == 'county':
        return identifier if re.fullmatch(r'[0-9]{5}', identifier) else None
    if kind != 'state':
        return None
    if source == 'bea_rpp':
        if identifier == '00000':
            return 'US'
        identifier = identifier[:2] if re.fullmatch(r'[0-9]{2}000', identifier) else ''
    elif source in ('fbi_cde', 'eia'):
        return 'US' if identifier == 'US' else STATE_CODES.get(identifier)
    return identifier if identifier in STATE_CODES.values() else None


def observations(field_id):
    if not re.fullmatch(r'[0-9]{2}\.[0-9]{2}(?::[a-zA-Z0-9_:-]{1,80})?', field_id):
        raise ValueError('Invalid field identifier')
    rows = query("""
      WITH chosen AS (
        SELECT o.period,o.source_release FROM usa_atlas.observation o
        JOIN usa_atlas.ingest_run i USING(ingest_id)
        WHERE o.catalog_field_id=:'catalog_id' AND o.field_id=:'field_id'
          AND o.geo_type IN ('state','county') AND i.status='pass'
        ORDER BY o.period DESC,o.source_release DESC LIMIT 1
      )
      SELECT COALESCE(json_agg(t ORDER BY geo_type,geo_id),'[]'::json) FROM (
        SELECT o.geo_id,o.geo_type,o.period,o.value,o.unit,o.source,o.source_release,
          o.source_url,o.methodology_note,o.retrieved_at
        FROM usa_atlas.observation o JOIN chosen c USING(period,source_release)
        JOIN usa_atlas.ingest_run i USING(ingest_id)
        WHERE o.catalog_field_id=:'catalog_id' AND o.field_id=:'field_id'
          AND o.geo_type IN ('state','county') AND i.status='pass'
      ) t
    """, {'catalog_id': field_id[:5], 'field_id': field_id})
    if not rows:
        raise LookupError('No state/county observations exist for this series')
    identities = {(r['period'], r['unit'], r['source'], r['source_release']) for r in rows}
    if len(identities) != 1:
        raise DatabaseUnavailable('The selected snapshot has incompatible units or sources.')
    period, unit, source, release = next(iter(identities))
    result, excluded, seen = [], [], set()
    for row in rows:
        identifier = canonical_geo(row['source'], row['geo_type'], row['geo_id'])
        if identifier is None:
            excluded.append(row['geo_id'])
            continue
        if identifier in seen:
            raise DatabaseUnavailable('The selected snapshot has ambiguous geography identifiers.')
        seen.add(identifier)
        result.append({'id': identifier, 'geoType': row['geo_type'], 'sourceGeoId': row['geo_id'],
                       'value': row['value'], 'sourceUrl': row['source_url'],
                       'methodologyNote': row['methodology_note'], 'retrievedAt': row['retrieved_at']})
    return {'fieldId': field_id, 'period': period, 'sourceUnit': unit,
            'unit': USDA[field_id][1] if field_id in USDA else
                    {'index_us_100': 'index · US = 100', 'persons': 'people'}.get(unit, unit),
            'source': SOURCE_NAMES.get(source, source), 'sourceRelease': release,
            'observations': result, 'excludedGeographies': excluded,
            'selection': 'Latest single period and release in the loaded database; no older-place fallback.'}
