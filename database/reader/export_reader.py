#!/usr/bin/env python3
"""Validate and export the versioned, read-only application reader contract."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'database/reader/v1'
FIELD_CONTRACT_SHA256 = 'dbb2b080683dd17cf53f5252f7937b00e22b9eafaf57cc2ed8ab9d4837886b45'
REQUIRED = {
    'catalog_field': {'catalog_field_id':'text','catalog_label':'text','planned_state':'text','rate_limit_profile':'text','source_release':'text','contract':'jsonb','contract_sha256':'character(64)'},
    'observation': {'geo_id':'text','geo_type':'text','period':'text','field_id':'text','catalog_field_id':'text','value':'double precision','unit':'text','source':'text','source_release':'text','source_url':'text','methodology_note':'text','retrieved_at':'timestamp with time zone','ingest_id':'uuid'},
    'ingest_run': {'ingest_id':'uuid','status':'text','source':'text','artifact_path':'text','artifact_sha256':'character(64)','contract_sha256':'character(64)','row_count':'bigint','started_at':'timestamptz','completed_at':'timestamptz','error_code':'text'},
}
OBSERVATION_VIEW = {
    'geo_id': ('o', 'geo_id', 'text'),
    'geo_type': ('o', 'geo_type', 'text'),
    'period': ('o', 'period', 'text'),
    'field_id': ('o', 'field_id', 'text'),
    'catalog_field_id': ('o', 'catalog_field_id', 'text'),
    'value': ('o', 'value', 'double precision'),
    'unit': ('o', 'unit', 'text'),
    'source': ('o', 'source', 'text'),
    'source_release': ('o', 'source_release', 'text'),
    'source_url': ('r', 'source_url', 'text'),
    'methodology_note': ('m', 'methodology_note', 'text'),
    'retrieved_at': ('o', 'retrieved_at', 'timestamp with time zone'),
    'ingest_id': ('o', 'ingest_id', 'uuid'),
}

def canonical(value): return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n').encode()
def sha(data): return hashlib.sha256(data).hexdigest()
def sql_type_pattern(typ):
    return re.escape(typ).replace('timestamp\\ with\\ time\\ zone', '(?:timestamp\\s+with\\s+time\\s+zone|timestamptz)')
def validate():
    schema = (ROOT/'database/schema.sql').read_text()
    for table, columns in REQUIRED.items():
        object_pattern = (rf'CREATE TABLE(?: IF NOT EXISTS)? usa_atlas\.{table}\s*\('
                          if table != 'observation' else r'CREATE(?: OR REPLACE)? VIEW usa_atlas\.observation\s+AS')
        if not re.search(object_pattern, schema, re.I):
            raise ValueError(f'required_object_missing:{table}')
        for column, typ in columns.items():
            if table != 'observation':
                body = re.split(rf'CREATE TABLE(?: IF NOT EXISTS)? usa_atlas\.{table}', schema, flags=re.I)[1].split(');',1)[0]
                valid = re.search(rf'\b{column}\s+{sql_type_pattern(typ)}(?=\s|\(|,|$)', body, re.I)
                if not valid:
                    raise ValueError(f'required_column_changed:{table}.{column}:{typ}')
    view = re.split(r'CREATE(?: OR REPLACE)? VIEW usa_atlas\.observation\s+AS', schema, flags=re.I)[1].split(';',1)[0]
    projection = view.split('FROM', 1)[0]
    projected = {}
    for item in projection.split('SELECT', 1)[1].split(','):
        match = re.fullmatch(r'\s*(\w+)\.(\w+)(?:\s+AS\s+(\w+))?\s*', item, re.I)
        if match:
            relation_alias, source_column, alias = match.groups()
            projected[alias or source_column] = (relation_alias.lower(), source_column.lower())
    for column, (relation_alias, source_column, typ) in OBSERVATION_VIEW.items():
        if projected.get(column) != (relation_alias, source_column):
            raise ValueError(f'required_column_changed:observation.{column}:{typ}')
        relation = {'o': 'observation_data', 'r': 'source_resource', 'm': 'methodology'}[relation_alias]
        table_body = re.split(rf'CREATE TABLE(?: IF NOT EXISTS)? usa_atlas\.{relation}', schema, flags=re.I)[1].split(');',1)[0]
        if not re.search(rf'\b{source_column}\s+{sql_type_pattern(typ)}(?=\s|\(|,|$)', table_body, re.I):
            raise ValueError(f'required_column_changed:observation.{column}:{typ}')
    # Use the admission validator as the canonical 81-field source contract.
    sys.path.insert(0, str(ROOT/'database'))
    import load
    field_path = ROOT/'full/field-contract.json'
    rows, by_id = load.validate_contract(load.load_json(field_path))
    if len(by_id) != 81: raise ValueError('field_contract_count_changed')
    if sha(field_path.read_bytes()) != FIELD_CONTRACT_SHA256:
        raise ValueError('field_or_geography_contract_changed:review_and_version')
    geography = {'geo_types':['state','county','nation'], 'state_source_ids':'two digit Census FIPS (or provider native ID normalized by source adapter)',
       'state_fips_to_postal':dict(zip('01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 49 50 51 53 54 55 56'.split(),'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())),
       'county_source_ids':'five digit Census county FIPS', 'canonical_ids':'state two digit FIPS; county five digit FIPS; nation US',
       'admitted_geographies_only':True, 'coverage_claim':'none; contract does not assert completeness'}
    return schema, rows, geography

def export():
    schema, rows, geography = validate()
    # The bootstrap is deliberately limited to the application reader objects.
    (OUT/'schema.sql').write_text('''CREATE SCHEMA usa_atlas;\nCREATE TABLE usa_atlas.catalog_field (catalog_field_id text PRIMARY KEY, catalog_label text NOT NULL, planned_state text NOT NULL, rate_limit_profile text NOT NULL, source_release text NOT NULL, contract jsonb NOT NULL, contract_sha256 character(64) NOT NULL);\nCREATE TABLE usa_atlas.ingest_run (ingest_id uuid PRIMARY KEY, source text NOT NULL, artifact_path text NOT NULL, artifact_sha256 character(64) NOT NULL, contract_sha256 character(64) NOT NULL, row_count bigint NOT NULL, started_at timestamptz NOT NULL, completed_at timestamptz, status text NOT NULL, error_code text);\nCREATE TABLE usa_atlas.observation (geo_id text NOT NULL, geo_type text NOT NULL, period text NOT NULL, field_id text NOT NULL, catalog_field_id text NOT NULL REFERENCES usa_atlas.catalog_field, value double precision NOT NULL, unit text NOT NULL, source text NOT NULL, source_release text NOT NULL, source_url text NOT NULL, methodology_note text NOT NULL, retrieved_at timestamptz NOT NULL, ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run, PRIMARY KEY (geo_id,period,field_id,source_release));\n''')
    doc = {'format':'usa_atlas_reader_contract','contract_id':'usa_atlas.application_reader','version':'1.0.0','compatibility':{'policy':'additive-compatible within v1; removing/renaming objects or columns, changing key/period/release/provenance meaning requires a new major version','deployed_binding':'unverified'},
      'read_only':True,'admission_filter':"usa_atlas.ingest_run.status = 'pass'",'objects':REQUIRED,
      'minimum_read_contract':{'required_objects':['usa_atlas.catalog_field','usa_atlas.observation','usa_atlas.ingest_run'],'admission':'join observation.ingest_id to ingest_run.ingest_id and include only status=pass','observation_columns':list(REQUIRED['observation']),'observation_key':['geo_id','period','field_id','source_release'],'period_type':'text','source_release_required':True,'provenance_columns':['source','source_url','methodology_note','retrieved_at','ingest_id'],'catalog_field_count':81,'completeness_claim':'none'},
      'adapter_reads':{'catalog_field':['catalog_field_id','catalog_label','planned_state','contract'],'observation':list(REQUIRED['observation']),'ingest_run':['ingest_id','status']},
      'keys':{'catalog_field':['catalog_field_id'],'observation':['geo_id','period','field_id','source_release'],'ingest_run':['ingest_id']},
      'semantics':{'period':'text period label; do not assume calendar year','source_release':'distinct source snapshot/release selector','zero':'numeric zero is a present value; absence is no row','provenance':['source','source_url','methodology_note','retrieved_at','ingest_id'],'catalog_field_id':'first five characters of field_id; field_id may be a series child such as 03.06:unemployment_rate'},
      'geography':geography,'catalog_fields':[{'field_id':r['field_id'],'label':r['catalog_label'],'planned_state':r['planned_state'],'unit':r['unit'],'source_release':r['source_release'],'target_geographies':r['target_geographies']} for r in rows],
      'schema_fingerprint':sha(canonical({'objects':REQUIRED,'observation_key':['geo_id','period','field_id','source_release'],'catalog_key':['catalog_field_id'],'admission':'status=pass'})),
      'artifacts':{'bootstrap':'schema.sql','fixtures':['fixtures/reader-fixture.sql','fixtures/reader-query.sql']}}
    doc['artifact_sha256'] = {name: sha((OUT/name).read_bytes()) for name in ('schema.sql','fixtures/reader-fixture.sql','fixtures/reader-query.sql')}
    (OUT/'contract.json').write_bytes(canonical(doc))
    return
if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--check',action='store_true'); a=p.parse_args()
    try:
        if a.check:
            with tempfile.TemporaryDirectory() as temp:
                expected = Path(temp)
                for name in ('reader-fixture.sql','reader-query.sql'):
                    (expected/'fixtures').mkdir(exist_ok=True)
                    shutil.copyfile(OUT/'fixtures'/name, expected/'fixtures'/name)
                original = OUT
                OUT = expected
                try: export()
                finally: OUT = original
                names = ('contract.json','schema.sql')
                stale = [name for name in names if (OUT/name).read_bytes() != (expected/name).read_bytes()]
                if stale: raise ValueError('reader_bundle_stale:' + ','.join(stale))
            print('reader contract source and bundle validation passed')
        else: export(); print('exported', OUT)
    except (ValueError, OSError) as e: print(str(e),file=sys.stderr); sys.exit(1)
