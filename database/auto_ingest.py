#!/usr/bin/env python3
"""Stream verified admission-v1 batches into the existing USA Atlas v3 database.

No schema bootstrap is performed here. See ADMISSION-PROTOCOL.md. Each COPY,
numeric/quality publication and checkpoint update commits in one transaction.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
PRODUCTION=Path('/opt/usa-atlas-production/admission-20260922')
CONTAINER='usa-atlas-postgres'
SCHEMA_MANIFEST=ROOT/'database/pipeline-schema-manifest.json'
HEX=re.compile(r'^[0-9a-f]{64}$')
WIRE={'geo_id','geo_type','year','field_id','catalog_field_id','value','unit','source',
      'source_release','source_url','methodology_note','retrieved_at'}
QUALITY_FIELDS=(WIRE-{'value'})|{'quality_status','raw_value','annotation'}
QUALITY_STATES={'missing','suppressed','not_applicable','invalid','sentinel'}
STAGE_COLUMNS=('ingest_id','geo_id','geo_type','period','field_id','catalog_field_id','value',
               'unit','source','source_release','source_url','methodology_note','retrieved_at','record_key')
KEYS='geo_id,period,field_id,source_release'
MAX_OUTPUT_ROWS=250_000


class AdmissionError(Exception):
    def __init__(self,reason,status='quarantine',retry=0):
        super().__init__(reason);self.reason=reason;self.status=status;self.retry=retry


def fail(reason):raise AdmissionError(reason)
def retry(reason):raise AdmissionError(reason,'transient_failure',900)
def maintenance(reason):raise AdmissionError(reason,'deferred_maintenance',300)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def literal(value):return "'"+str(value).replace("'","''")+"'"
def reject_constant(value):raise AdmissionError('nonfinite_json_token')


def read_json(path):
    try:return json.loads(Path(path).read_text(),parse_constant=reject_constant)
    except (ValueError,UnicodeError):fail('invalid_json_document')


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    os.chmod(tmp,0o600);tmp.replace(path)


def timestamp(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:fail('timestamp_timezone_missing')
        return result.astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError):fail('timestamp_invalid')


def integer(value,name):
    if isinstance(value,bool) or not isinstance(value,int) or value<0:fail(name+'_invalid')
    return value


def bound_path(base,description,*,output=False):
    if not isinstance(description,dict):fail('artifact_descriptor_invalid')
    name=description.get('path');expected=description.get('sha256')
    if not isinstance(name,str) or not name or not HEX.fullmatch(str(expected)):fail('artifact_binding_invalid')
    path=(base/name).resolve()
    if not path.is_relative_to(base if output else ROOT):fail('artifact_path_outside_allowed_root')
    if not path.is_file():retry('bound_artifact_missing')
    if sha(path)!=expected:fail('bound_artifact_sha256_mismatch')
    return path


def extract_constant(path,name):
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)
    fail('loader_schema_constant_missing')


def loader_module():
    spec=importlib.util.spec_from_file_location('usa_atlas_admission_legacy',ROOT/'database/load.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def preflight(path):
    path=path.resolve()
    if not path.is_relative_to(ROOT):fail('manifest_outside_repository')
    data=read_json(path);base=path.parent
    if not isinstance(data,dict) or data.get('format')!='usa_atlas_admission_v1':fail('manifest_format_invalid')
    if data.get('status')!='complete' or data.get('completeness',{}).get('complete') is not True:fail('artifact_incomplete')
    if not isinstance(data['completeness'].get('basis'),str) or not data['completeness']['basis'].strip():fail('completeness_proof_missing')
    for name in ('batch_id','snapshot_id'):
        if not HEX.fullmatch(str(data.get(name,''))):fail(name+'_invalid')
    for name in ('dataset_key','source','source_release','adapter_version'):
        if not isinstance(data.get(name),str) or not data[name].strip() or '\x00' in data[name]:fail(name+'_invalid')
    if len(data['dataset_key'])>512:fail('dataset_key_too_long')
    if data.get('kind') not in ('observations','records'):fail('dataset_kind_invalid')
    timestamp(data.get('snapshot_at'))
    scope=data.get('scope',{})
    if scope.get('type')!='input_row_range':fail('unsupported_partition_scope')
    start=integer(scope.get('start_row'),'start_row');end=integer(scope.get('end_row_exclusive'),'end_row')
    total=integer(scope.get('total_input_rows'),'total_input_rows')
    if not 0<=start<=end<=total or (start==end and total!=0):fail('partition_range_invalid')
    adapter=bound_path(base,data.get('adapter'))
    inputs=data.get('inputs')
    if not isinstance(inputs,list) or not inputs:fail('source_input_bindings_missing')
    bound_inputs=[(bound_path(base,x),x['sha256']) for x in inputs]
    bound_inputs.append((adapter,data['adapter']['sha256']))
    payloads={};row_count=0;uncompressed=0
    for name in ('observations','quality','records'):
        desc=data.get(name)
        if desc is None:continue
        p=bound_path(base,desc,output=True)
        rows=integer(desc.get('rows'),name+'_rows');size=integer(desc.get('bytes'),name+'_bytes')
        expanded=integer(desc.get('uncompressed_bytes'),name+'_uncompressed_bytes')
        if p.stat().st_size!=size:fail('artifact_size_mismatch')
        if rows and not expanded:fail('artifact_uncompressed_size_missing')
        payloads[name]=(p,desc);row_count+=rows;uncompressed+=expanded
    if data['kind']=='observations':
        if set(payloads)!={'observations','quality'}:fail('canonical_and_quality_artifacts_required')
        contract_path=bound_path(base,data.get('contract'))
        bound_inputs.append((contract_path,data['contract']['sha256']))
        legacy=loader_module()
        try:contract,by_id=legacy.validate_contract(read_json(contract_path))
        except (ValueError,TypeError,KeyError):fail('catalog_contract_invalid')
    else:
        if set(payloads)!={'records'} or data.get('contract') is not None:fail('generic_artifact_layout_invalid')
        contract_path=None;legacy=None;by_id={}
    if row_count>MAX_OUTPUT_ROWS:fail('batch_output_row_limit_exceeded')
    semantic={k:data[k] for k in ('dataset_key','kind','source','source_release','snapshot_id','snapshot_at','adapter_version','scope')}
    semantic['adapter_sha256']=data['adapter']['sha256'];semantic['input_sha256']=[x['sha256'] for x in inputs]
    semantic['contract_sha256']=data.get('contract',{}).get('sha256') if data.get('contract') else None
    semantic['artifacts']={name:{k:desc[k] for k in ('sha256','rows','bytes','uncompressed_bytes')} for name,(_,desc) in payloads.items()}
    return {'data':data,'path':path,'manifest_sha256':sha(path),'admission_sha256':digest(semantic),
            'payloads':payloads,'bound_inputs':bound_inputs,'adapter_path':adapter,
            'legacy':legacy,'by_id':by_id,'contract_path':contract_path,
            'rows':row_count,'uncompressed_bytes':uncompressed,
            'allow_legacy':data['kind']=='observations' and adapter==ROOT/'full/prepare_admission.py'}


def jsonl(path,stats):
    opener=gzip.open if path.suffix=='.gz' else open
    try:
        with opener(path,'rt',encoding='utf-8') as stream:
            for line in stream:
                stats['bytes']+=len(line.encode('utf-8'))
                if len(line)>16*1024**2:fail('individual_record_too_large')
                if not line.strip():fail('blank_payload_record')
                yield json.loads(line,parse_constant=reject_constant)
    except (ValueError,UnicodeError,EOFError,gzip.BadGzipFile):fail('invalid_jsonl_payload')


def key_for(row):return 'observation:'+digest([row['geo_id'],row['year'],row['field_id'],row['source_release']])


def validate_wire(row,batch,quality=False):
    fields=QUALITY_FIELDS if quality else WIRE
    if not isinstance(row,dict) or set(row)!=fields:fail('record_fields_invalid')
    check=dict(row)
    if quality:
        if row['quality_status'] not in QUALITY_STATES:fail('quality_status_invalid')
        if row['raw_value'] is not None and (isinstance(row['raw_value'],bool) or not isinstance(row['raw_value'],(str,int,float))):fail('quality_raw_value_invalid')
        if row['annotation'] is not None and not isinstance(row['annotation'],str):fail('quality_annotation_invalid')
        check={k:v for k,v in row.items() if k in WIRE};check['value']=0
        # This zero exists only inside the legacy structural validator. It is
        # never emitted, copied, stored or used as an observation value.
    try:batch['legacy'].validate_record(check,batch['data']['source'],batch['by_id'])
    except (ValueError,TypeError,KeyError):fail('canonical_record_contract_invalid')
    if row['source_release']!=batch['data']['source_release']:fail('record_release_mismatch')
    if batch['allow_legacy']:
        widths={'state':2,'county':5,'place':7,'tract':11,'block_group':12}
        geo=row['geo_type'];ident=row['geo_id'];job=batch['data']['scope'].get('job_id')
        if geo=='nation':
            if ident!='US':fail('national_geo_id_invalid')
        elif geo not in widths or not re.fullmatch('[0-9]{'+str(widths[geo])+'}',ident):fail('national_geo_width_invalid')
        parent=row['catalog_field_id'];field=row['field_id']
        if row['source']=='census_acs':
            if row['year']!='2024' or row['source_release']!='2024-acs-acs5' or row['unit']!='source_defined':fail('acs_release_period_or_unit_invalid')
            variable=field.removeprefix(parent+':')
            table=variable.split('_')[0]
            allowed=set(batch['by_id'][parent]['source_variables'])
            if table=='B17021' and parent=='02.08':allowed={f'B17021_{n:03}{suffix}' for n in (1,2) for suffix in ('E','M')}
            if table=='B05012' and parent=='01.05':allowed={f'B05012_{n:03}{suffix}' for n in (1,2,3) for suffix in ('E','M')}
            if variable not in allowed or job!='acs-summary-'+table:fail('acs_source_variable_or_job_invalid')
        elif row['source']=='cdc_places':
            allowed={parent+':'+suffix for suffix in ('crude_prevalence','crude_prevalence:ci_low','crude_prevalence:ci_high')}
            if (parent not in ('05.14','05.15','05.16') or field not in allowed or job!='cdc-places-2025-tract'
                or geo!='tract' or row['year']!='2023' or row['source_release']!='PLACES-2025' or row['unit']!='%'):
                fail('cdc_source_variable_or_job_invalid')
        else:fail('unreviewed_national_source')
    if not quality and row['value'] in (-222222222,-333333333,-555555555,-666666666,-888888888,-999999999):
        fail('numeric_missing_sentinel_requires_quality_record')
    canonical(row)  # Reject NaN/Infinity nested in source annotations as well.
    return row


def db_command(app='usa_atlas_auto_ingest'):
    return ['docker','exec','-i','-u','postgres','-e','PGAPPNAME='+app,CONTAINER,
            'sh','-c','exec psql -X -w -qAt --username "$POSTGRES_USER" --dbname usa_atlas --set ON_ERROR_STOP=1 --set VERBOSITY=sqlstate']


class Session:
    def __init__(self,error_dir):
        self.error_dir=error_dir;self.committed=False;self.in_copy=False;self.query_active=False;self.backend_pid=None
        self.app='usa_atlas_auto_ingest_'+uuid.uuid4().hex[:12]
    def __enter__(self):
        self.error_dir.mkdir(parents=True,exist_ok=True)
        self.error_path=self.error_dir/(uuid.uuid4().hex+'.log')
        self.error=self.error_path.open('w+');os.chmod(self.error_path,0o600)
        self.p=subprocess.Popen(db_command(self.app),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.error,text=True,bufsize=1)
        try:
            self.query("BEGIN; SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='10min'; SET LOCAL idle_in_transaction_session_timeout='60s'; SET LOCAL work_mem='64MB'; SET LOCAL max_parallel_workers_per_gather=0; SET LOCAL enable_parallel_hash=off; SET LOCAL temp_file_limit='16GB'; DO $$ BEGIN IF NOT pg_try_advisory_xact_lock(66280928) THEN RAISE EXCEPTION USING ERRCODE='55P03',MESSAGE='maintenance busy'; END IF; END $$;")
            self.backend_pid=int(self.query('SELECT pg_backend_pid();'))
        except BaseException:
            self.__exit__(*sys.exc_info());raise
        return self
    def error_out(self):
        self.error.flush();self.error.seek(0);message=self.error.read()
        if any(code in message for code in ('55P03','40P01','40001','57014','57P03','53100','53200','53300','53400','08006','08001')):
            retry('postgres_retryable_transaction_failure')
        if 'permission denied' in message.lower() or 'cannot connect' in message.lower() or 'connection' in message.lower():
            maintenance('database_access_unavailable')
        fail('postgres_statement_failed_details_private')
    def query(self,text):
        self.query_active=True
        marker='END_'+uuid.uuid4().hex
        try:self.p.stdin.write(text+'\n;\nSELECT '+literal(marker)+';\n');self.p.stdin.flush()
        except (BrokenPipeError,OSError):self.error_out()
        lines=[]
        while True:
            line=self.p.stdout.readline()
            if not line:self.error_out()
            if line.strip()==marker:
                self.query_active=False;return '\n'.join(lines).strip()
            lines.append(line.rstrip('\n'))
    def copy(self,table,columns,rows):
        self.in_copy=True
        self.p.stdin.write('COPY '+table+' ('+','.join(columns)+') FROM STDIN;\n')
        count=0
        try:
            for row in rows:
                def escape(value):
                    if value is None:return '\\N'
                    return str(value).replace('\\','\\\\').replace('\t','\\t').replace('\r','\\r').replace('\n','\\n')
                self.p.stdin.write('\t'.join(escape(v) for v in row)+'\n');count+=1
                if count>MAX_OUTPUT_ROWS:fail('actual_batch_row_limit_exceeded')
            self.p.stdin.write('\\.\n');self.p.stdin.flush()
            self.query('SELECT 1;')
            self.in_copy=False
        except (BrokenPipeError,OSError):self.error_out()
        return count
    def __exit__(self,*exc):
        if self.p.poll() is None:
            if exc[0] and self.backend_pid and (self.in_copy or self.query_active):
                # Cancel only this invocation's backend. This bounds shutdown
                # after an orchestrator SIGTERM without touching other work.
                try:
                    subprocess.run(db_command(self.app+'_cancel'),input=f"SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE pid={self.backend_pid} AND datname='usa_atlas' AND application_name={literal(self.app)};",text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
                except (OSError,subprocess.SubprocessError):pass
            try:
                # SQL must never be written while the frontend is in COPY data
                # mode. Closing stdin then the session rolls back that batch.
                if not self.committed and not self.in_copy and not self.query_active:self.query('ROLLBACK;')
            except (AdmissionError,BrokenPipeError,OSError):pass
            try:self.p.stdin.close()
            except BrokenPipeError:pass
            try:self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
        self.p.stdout.close();self.error.close()
        if not exc[0]:self.error_path.unlink(missing_ok=True)


def verify_schema(db):
    if not SCHEMA_MANIFEST.is_file():maintenance('pipeline_schema_not_deployed')
    meta=read_json(SCHEMA_MANIFEST)
    if (meta.get('format')!='usa_atlas_pipeline_schema_v3'
        or meta.get('schema_sha256')!=sha(ROOT/'database/schema.sql')
        or meta.get('pipeline_schema_sha256')!=sha(ROOT/'database/pipeline_schema.sql')):
        maintenance('pipeline_schema_code_binding_mismatch')
    expected=extract_constant(ROOT/'database/load.py','EXPECTED_SCHEMA_CATALOG_SHA256')
    if meta.get('catalog_sha256')!=expected:maintenance('pipeline_catalog_pin_not_deployed')
    observed=db.query("SELECT schema_sha256 FROM usa_atlas.schema_metadata WHERE singleton;")
    if observed!=meta['schema_sha256']:maintenance('database_schema_pin_mismatch')
    text=db.query(extract_constant(ROOT/'database/load.py','CATALOG_DOCUMENT_SQL'))
    if hashlib.sha256(text.encode()).hexdigest()!=expected:maintenance('database_catalog_pin_mismatch')
    if db.query("SELECT to_regclass('usa_atlas_pipeline.dataset') IS NOT NULL;")!='t':maintenance('pipeline_namespace_missing')


def stage(db,batch,ingest_id):
    data=batch['data']
    db.query("CREATE TEMP TABLE auto_numeric_stage (LIKE usa_atlas.observation_stage INCLUDING DEFAULTS, record_key text NOT NULL, PRIMARY KEY(geo_id,period,field_id,source_release)) ON COMMIT DROP; CREATE TEMP TABLE auto_quality_stage (geo_id text NOT NULL,geo_type text NOT NULL,period text NOT NULL,field_id text NOT NULL,catalog_field_id text NOT NULL,source text NOT NULL,source_release text NOT NULL,record_key text NOT NULL,payload jsonb NOT NULL,PRIMARY KEY(geo_id,period,field_id,source_release)) ON COMMIT DROP; CREATE TEMP TABLE auto_record_stage (record_key text PRIMARY KEY,kind text NOT NULL,payload jsonb NOT NULL) ON COMMIT DROP;")
    counts={'observations':0,'quality':0,'records':0}
    for name,(path,desc) in batch['payloads'].items():
        stats={'bytes':0}
        def rows():
            for row in jsonl(path,stats):
                if name=='observations':
                    r=validate_wire(row,batch)
                    yield (ingest_id,r['geo_id'],r['geo_type'],r['year'],r['field_id'],r['catalog_field_id'],r['value'],r['unit'],r['source'],r['source_release'],r['source_url'],r['methodology_note'],r['retrieved_at'],key_for(r))
                elif name=='quality':
                    r=validate_wire(row,batch,True)
                    yield (r['geo_id'],r['geo_type'],r['year'],r['field_id'],r['catalog_field_id'],r['source'],r['source_release'],key_for(r),canonical(r))
                else:
                    if not isinstance(row,dict) or set(row)!={'record_key','kind','payload'}:fail('generic_record_fields_invalid')
                    if row['kind']!='source_record' or not isinstance(row['payload'],dict):fail('generic_record_kind_invalid')
                    if not isinstance(row['record_key'],str) or not 1<=len(row['record_key'])<=2048:fail('generic_record_key_invalid')
                    yield (row['record_key'],row['kind'],canonical(row['payload']))
        columns=STAGE_COLUMNS if name=='observations' else ('geo_id','geo_type','period','field_id','catalog_field_id','source','source_release','record_key','payload') if name=='quality' else ('record_key','kind','payload')
        counts[name]=db.copy('auto_'+('numeric' if name=='observations' else 'quality' if name=='quality' else 'record')+'_stage',columns,rows())
        if counts[name]!=desc['rows'] or stats['bytes']!=desc['uncompressed_bytes'] or sha(path)!=desc['sha256']:fail('payload_changed_or_row_count_mismatch')
    if sha(batch['path'])!=batch['manifest_sha256']:fail('manifest_changed_during_copy')
    for path,expected in batch['bound_inputs']:
        if sha(path)!=expected:fail('source_input_changed_during_copy')
    return counts


def scoped_keys_sql():
    return 'SELECT '+KEYS+',geo_type,catalog_field_id,source,record_key FROM auto_numeric_stage UNION ALL SELECT '+KEYS+',geo_type,catalog_field_id,source,record_key FROM auto_quality_stage'


def ensure_ownership(db,batch):
    d=batch['data'];key=literal(d['dataset_key']);snap=literal(d['snapshot_id']);bid=literal(d['batch_id'])
    if db.query('SELECT EXISTS(SELECT 1 FROM auto_numeric_stage n JOIN auto_quality_stage q USING('+KEYS+'));')=='t':fail('numeric_quality_key_overlap')
    invalid=db.query(f"WITH s AS ({scoped_keys_sql()}) SELECT EXISTS(SELECT 1 FROM s JOIN usa_atlas.observation_data e USING({KEYS}) LEFT JOIN usa_atlas_pipeline.snapshot_batch b ON b.ingest_id=e.ingest_id WHERE e.source<>s.source OR e.geo_type<>s.geo_type OR e.catalog_field_id<>s.catalog_field_id OR (b.dataset_key IS NOT NULL AND b.dataset_key<>{key}) OR (b.dataset_key IS NULL AND {'false' if batch['allow_legacy'] else 'true'}) OR (b.snapshot_id={snap} AND b.batch_id<>{bid}));")
    if invalid=='t':fail('canonical_key_ownership_conflict')
    invalid=db.query(f"WITH s AS ({scoped_keys_sql()}) SELECT EXISTS(SELECT 1 FROM s JOIN usa_atlas_pipeline.generic_record g ON g.record_key=s.record_key AND g.kind='observation_quality' WHERE g.dataset_key<>{key} OR (g.snapshot_id={snap} AND g.batch_id<>{bid}));")
    if invalid=='t':fail('quality_key_ownership_conflict')


def apply_batch(db,batch):
    d=batch['data'];key=literal(d['dataset_key']);snap=literal(d['snapshot_id']);bid=literal(d['batch_id']);at=literal(d['snapshot_at'])
    scope=d['scope'];start=scope['start_row'];end=scope['end_row_exclusive'];total=scope['total_input_rows']
    prior=db.query(f"SELECT row_to_json(b) FROM usa_atlas_pipeline.snapshot_batch b WHERE batch_id={bid};")
    if prior:
        old=json.loads(prior)
        if old['admission_sha256']!=batch['admission_sha256'] or old['status']!='pass':fail('batch_id_reused_with_different_content')
        return {'status':'already_pass','reason':'exact_committed_batch','ingest_id':old['ingest_id'],'loaded_rows':old['numeric_rows'],'quality_rows':old['quality_rows'],'record_rows':old['record_rows'],'snapshot_complete':db.query(f'SELECT latest_snapshot_id={snap} FROM usa_atlas_pipeline.dataset WHERE dataset_key={key};')=='t'}
    prior=db.query(f'SELECT row_to_json(d) FROM usa_atlas_pipeline.dataset d WHERE dataset_key={key} FOR UPDATE;')
    if prior:
        old=json.loads(prior)
        if (old['kind'],old['source'],old['source_release'])!=(d['kind'],d['source'],d['source_release']):fail('dataset_identity_changed')
        if timestamp(d['snapshot_at'])<timestamp(old['active_snapshot_at']):
            return {'status':'already_pass','reason':'superseded_snapshot','snapshot_complete':False,'loaded_rows':0,'quality_rows':0,'record_rows':0,'ingest_id':None}
        if timestamp(d['snapshot_at'])==timestamp(old['active_snapshot_at']) and old['active_snapshot_id']!=d['snapshot_id']:fail('ambiguous_equal_time_snapshot')
        if old['active_snapshot_id']==d['snapshot_id'] and old['total_input_rows']!=total:fail('snapshot_total_input_rows_changed')
        if old['active_snapshot_id']!=d['snapshot_id']:
            db.query(f"DELETE FROM usa_atlas_pipeline.generic_record g USING usa_atlas_pipeline.dataset d WHERE g.dataset_key=d.dataset_key AND d.dataset_key={key} AND g.kind='source_record' AND g.snapshot_id IS DISTINCT FROM d.latest_snapshot_id;")
            db.query(f"UPDATE usa_atlas_pipeline.dataset SET active_snapshot_id={snap},active_snapshot_at={at}::timestamptz,total_input_rows={total},scope={literal(canonical(scope))}::jsonb,updated_at=clock_timestamp() WHERE dataset_key={key};")
    else:
        db.query(f"INSERT INTO usa_atlas_pipeline.dataset(dataset_key,kind,source,source_release,scope,active_snapshot_id,active_snapshot_at,total_input_rows) VALUES ({key},{literal(d['kind'])},{literal(d['source'])},{literal(d['source_release'])},{literal(canonical(scope))}::jsonb,{snap},{at}::timestamptz,{total});")
    if db.query(f"SELECT EXISTS(SELECT 1 FROM usa_atlas_pipeline.snapshot_batch WHERE dataset_key={key} AND snapshot_id={snap} AND (start_row<{end} AND end_row_exclusive>{start} OR (start_row={start} AND end_row_exclusive={end}))); ")=='t':fail('snapshot_partition_overlap')
    previous=db.query(f"SELECT manifest FROM usa_atlas_pipeline.snapshot_batch WHERE dataset_key={key} AND snapshot_id={snap} LIMIT 1;")
    if previous:
        prior_manifest=json.loads(previous)
        def snapshot_binding(value):
            return (value['adapter']['sha256'],value['adapter_version'],
                    value.get('contract',{}).get('sha256') if value.get('contract') else None,
                    [item['sha256'] for item in value['inputs']])
        if snapshot_binding(prior_manifest)!=snapshot_binding(d):fail('snapshot_input_or_adapter_binding_changed')
    ingest_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'usa-atlas-auto-ingest:'+d['batch_id'])) if d['kind']=='observations' else None
    counts=stage(db,batch,ingest_id)
    if d['kind']=='observations':
        ensure_ownership(db,batch)
        # The contract content is bound per chunk; catalog metadata is never
        # replaced by an adapter. Only the existing reviewed 81 fields are used.
        if db.query('SELECT EXISTS(SELECT 1 FROM (SELECT DISTINCT catalog_field_id FROM auto_numeric_stage UNION SELECT DISTINCT catalog_field_id FROM auto_quality_stage) s LEFT JOIN usa_atlas.catalog_field c USING(catalog_field_id) WHERE c.catalog_field_id IS NULL);')=='t':fail('catalog_field_missing_in_database')
        db.query(f"INSERT INTO usa_atlas.ingest_run(ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,status) VALUES ({literal(ingest_id)}::uuid,{literal(d['source'])},{literal(str(batch['path'].relative_to(ROOT)))},{literal(batch['manifest_sha256'])},{literal(d['contract']['sha256'])},0,clock_timestamp(),'loading');")
    db.query(f"INSERT INTO usa_atlas_pipeline.snapshot_batch(batch_id,dataset_key,snapshot_id,snapshot_at,start_row,end_row_exclusive,total_input_rows,manifest_sha256,admission_sha256,manifest,ingest_id,numeric_rows,quality_rows,record_rows,status) VALUES ({bid},{key},{snap},{at}::timestamptz,{start},{end},{total},{literal(batch['manifest_sha256'])},{literal(batch['admission_sha256'])},{literal(canonical(d))}::jsonb,{literal(ingest_id)+'::uuid' if ingest_id else 'NULL'},{counts['observations']},{counts['quality']},{counts['records']},'loading');")
    updated=0;deleted=0
    if d['kind']=='observations':
        updated=int(db.query('SELECT count(*) FROM auto_numeric_stage n JOIN usa_atlas.observation_data e USING('+KEYS+');'))
        db.query('INSERT INTO usa_atlas.source_resource(source_url) SELECT DISTINCT source_url FROM auto_numeric_stage WHERE true ON CONFLICT(source_url) DO NOTHING; INSERT INTO usa_atlas.methodology(methodology_note) SELECT DISTINCT methodology_note FROM auto_numeric_stage WHERE true ON CONFLICT(methodology_note) DO NOTHING;')
        db.query(f"WITH s AS ({scoped_keys_sql()}) DELETE FROM usa_atlas_pipeline.generic_record g USING s WHERE g.dataset_key={key} AND g.kind='observation_quality' AND g.record_key=s.record_key;")
        deleted=int(db.query(f"WITH removed AS (DELETE FROM usa_atlas.observation_data e USING auto_quality_stage q WHERE (e.geo_id,e.period,e.field_id,e.source_release)=(q.geo_id,q.period,q.field_id,q.source_release) RETURNING 1) SELECT count(*) FROM removed;"))
        db.query("INSERT INTO usa_atlas.observation_data(geo_id,geo_type,period,field_id,catalog_field_id,value,unit,source,source_release,resource_id,methodology_id,retrieved_at,ingest_id) SELECT s.geo_id,s.geo_type,s.period,s.field_id,s.catalog_field_id,s.value,s.unit,s.source,s.source_release,r.resource_id,m.methodology_id,s.retrieved_at,s.ingest_id FROM auto_numeric_stage s JOIN usa_atlas.source_resource r USING(source_url) JOIN usa_atlas.methodology m USING(methodology_note) WHERE true ON CONFLICT(geo_id,period,field_id,source_release) DO UPDATE SET geo_type=EXCLUDED.geo_type,catalog_field_id=EXCLUDED.catalog_field_id,value=EXCLUDED.value,unit=EXCLUDED.unit,source=EXCLUDED.source,resource_id=EXCLUDED.resource_id,methodology_id=EXCLUDED.methodology_id,retrieved_at=EXCLUDED.retrieved_at,ingest_id=EXCLUDED.ingest_id;")
        db.query(f"INSERT INTO usa_atlas_pipeline.generic_record(dataset_key,snapshot_id,kind,record_key,payload,batch_id) SELECT {key},{snap},'observation_quality',record_key,payload,{bid} FROM auto_quality_stage;")
        db.query(f"UPDATE usa_atlas.ingest_run SET row_count={counts['observations']},completed_at=clock_timestamp(),status='pass' WHERE ingest_id={literal(ingest_id)}::uuid;")
    else:
        db.query(f"INSERT INTO usa_atlas_pipeline.generic_record(dataset_key,snapshot_id,kind,record_key,payload,batch_id) SELECT {key},{snap},kind,record_key,payload,{bid} FROM auto_record_stage;")
    db.query(f"UPDATE usa_atlas_pipeline.snapshot_batch SET status='pass',inserted_rows={counts['observations']-updated+counts['records']},updated_rows={updated},deleted_rows={deleted},loaded_at=clock_timestamp() WHERE batch_id={bid};")
    complete=db.query(f"SELECT COALESCE(min(start_row)=0 AND max(end_row_exclusive)={total} AND sum(end_row_exclusive-start_row)={total} AND bool_and(status='pass'),false) FROM usa_atlas_pipeline.snapshot_batch WHERE dataset_key={key} AND snapshot_id={snap};")=='t'
    stale_deleted=0
    if complete:
        stale_deleted=int(db.query(f"WITH removed AS (DELETE FROM usa_atlas.observation_data e USING usa_atlas_pipeline.snapshot_batch b WHERE e.ingest_id=b.ingest_id AND b.dataset_key={key} AND b.snapshot_id<>{snap} AND e.source={literal(d['source'])} AND e.source_release={literal(d['source_release'])} RETURNING 1) SELECT count(*) FROM removed;"))
        db.query(f"DELETE FROM usa_atlas_pipeline.generic_record WHERE dataset_key={key} AND snapshot_id<>{snap}; UPDATE usa_atlas_pipeline.dataset SET latest_snapshot_id={snap},latest_snapshot_at={at}::timestamptz,completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE dataset_key={key};")
        # Preserve current + two previous metadata snapshots. Payload history has
        # already been removed. Legacy ingest records are never selected here.
        db.query(f"CREATE TEMP TABLE auto_prune_ingests ON COMMIT DROP AS SELECT b.ingest_id FROM usa_atlas_pipeline.snapshot_batch b WHERE b.dataset_key={key} AND b.snapshot_id NOT IN (SELECT snapshot_id FROM usa_atlas_pipeline.snapshot_batch WHERE dataset_key={key} GROUP BY snapshot_id ORDER BY max(snapshot_at) DESC,snapshot_id DESC LIMIT 3) AND b.ingest_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM usa_atlas.observation_data o WHERE o.ingest_id=b.ingest_id); DELETE FROM usa_atlas_pipeline.snapshot_batch b WHERE b.dataset_key={key} AND b.snapshot_id NOT IN (SELECT snapshot_id FROM usa_atlas_pipeline.snapshot_batch WHERE dataset_key={key} GROUP BY snapshot_id ORDER BY max(snapshot_at) DESC,snapshot_id DESC LIMIT 3) AND NOT EXISTS(SELECT 1 FROM usa_atlas_pipeline.generic_record g WHERE g.batch_id=b.batch_id) AND (b.ingest_id IS NULL OR b.ingest_id IN (SELECT ingest_id FROM auto_prune_ingests)); DELETE FROM usa_atlas.ingest_run i USING auto_prune_ingests p WHERE i.ingest_id=p.ingest_id AND NOT EXISTS(SELECT 1 FROM usa_atlas.observation_data o WHERE o.ingest_id=i.ingest_id) AND NOT EXISTS(SELECT 1 FROM usa_atlas_pipeline.snapshot_batch b WHERE b.ingest_id=i.ingest_id);")
    return {'status':'pass','reason':'committed_batch','ingest_id':ingest_id,'loaded_rows':counts['observations'],
            'quality_rows':counts['quality'],'record_rows':counts['records'],'inserted_rows':counts['observations']-updated+counts['records'],
            'updated_rows':updated,'invalidated_numeric_rows':deleted,'stale_owned_rows_deleted':stale_deleted,'snapshot_complete':complete}


def run(batch,result_path):
    reserve=16*1024**3+max(512*1024**2,4*batch['uncompressed_bytes'])
    # The verified USA Atlas container's PostgreSQL bind mount may be on a
    # different filesystem from prepared artifacts; both need actual headroom.
    for volume in (ROOT,Path('/srv/usa-atlas/postgres')):
        if not volume.is_dir():maintenance('production_storage_path_unavailable')
        if shutil.disk_usage(volume).free<reserve:retry('insufficient_batch_disk_headroom')
    if not SCHEMA_MANIFEST.is_file():maintenance('pipeline_schema_not_deployed')
    with ExitStack() as stack:
        for path in (ROOT/'full/state/.usa-atlas-load.lock',PRODUCTION/'full/state/.usa-atlas-load.lock'):
            try:
                f=stack.enter_context(path.open('a+'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except (BlockingIOError,PermissionError):maintenance('loader_or_maintenance_lock_unavailable')
        with Session(result_path.parent/'.auto-ingest-errors') as db:
            verify_schema(db)
            db.query('LOCK TABLE usa_atlas.observation_data,usa_atlas.ingest_run,usa_atlas.catalog_field IN SHARE ROW EXCLUSIVE MODE;')
            result=apply_batch(db,batch)
            db.query('COMMIT;');db.committed=True
            return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args();base={'started_at':datetime.now(timezone.utc).isoformat(),'retry_after_seconds':0}
    def interrupted(*_):retry('process_interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        batch=preflight(args.manifest);d=batch['data']
        base.update(batch_id=d['batch_id'],dataset_key=d['dataset_key'],snapshot_id=d['snapshot_id'],
                    manifest_sha256=batch['manifest_sha256'],artifact_sha256=batch['admission_sha256'],row_count=batch['rows'])
        result=run(batch,args.result) if args.apply else {'status':'plan','reason':'manifest_preflight_no_database_write','loaded_rows':0,'quality_rows':0,'record_rows':0,'ingest_id':None,'snapshot_complete':False}
    except AdmissionError as exc:result={'status':exc.status,'reason':exc.reason,'retry_after_seconds':exc.retry}
    except (PermissionError,FileNotFoundError):result={'status':'deferred_maintenance','reason':'required_host_access_or_file_unavailable','retry_after_seconds':900}
    except (OSError,subprocess.SubprocessError):result={'status':'transient_failure','reason':'host_or_database_process_error','retry_after_seconds':900}
    except (ValueError,TypeError,KeyError,OverflowError):result={'status':'quarantine','reason':'invalid_manifest_or_payload_shape','retry_after_seconds':0}
    report={**base,**result,'completed_at':datetime.now(timezone.utc).isoformat()}
    save(args.result,report);print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status'] in ('pass','already_pass','plan') else 75 if report['status'] in ('transient_failure','deferred_maintenance') else 65


if __name__=='__main__':raise SystemExit(main())
