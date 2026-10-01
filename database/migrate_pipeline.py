#!/usr/bin/env python3
"""Prepare/apply the additive USA Atlas v2 -> v3 pipeline migration.

No --apply: prepare reviewable code copies only, without opening PostgreSQL.
--apply: exact v2 baseline, coordinated loader locks, transactional extension,
unchanged core catalog, audited namespace shape, v3 pins and atomic code switch.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import auto_ingest as ingest

ROOT=ingest.ROOT
STAGE=ROOT/'full/state/pipeline-migration-v3'
OLD_SCHEMA='6cf64be22ec298c4b99eadb862bb9759b4c0dd44195ef58bffe8b10a9216042d'
OLD_CATALOG='2aeb4cff27010265581b0c1a200963b8eb88e3f1a9d60e2e586f041f31cb117d'
NAMESPACE='usa_atlas_pipeline'
PATHS={'local_schema':ROOT/'database/schema.sql','local_loader':ROOT/'database/load.py',
       'production_schema':ingest.PRODUCTION/'database/schema.sql',
       'production_loader':ingest.PRODUCTION/'database/load.py'}
TABLE_COLUMNS={
 'dataset':['dataset_key','kind','source','source_release','scope','active_snapshot_id','active_snapshot_at','total_input_rows','latest_snapshot_id','latest_snapshot_at','completed_at','updated_at'],
 'snapshot_batch':['batch_id','dataset_key','snapshot_id','snapshot_at','start_row','end_row_exclusive','total_input_rows','manifest_sha256','admission_sha256','manifest','ingest_id','numeric_rows','quality_rows','record_rows','inserted_rows','updated_rows','deleted_rows','status','loaded_at'],
 'generic_record':['dataset_key','snapshot_id','kind','record_key','payload','batch_id'],
}
INDEXES={'dataset_pkey','snapshot_batch_pkey','snapshot_batch_dataset_key_snapshot_id_start_row_key',
         'pipeline_snapshot_lookup_idx','pipeline_snapshot_ingest_idx','generic_record_pkey',
         'pipeline_record_batch_idx','pipeline_quality_key_idx'}


GUARD='''def reject_pipeline_managed_target() -> None:
    """Historic exact-manifest commands cannot refresh pipeline-owned facts."""
    _, owner = target_identity()
    if not owner:
        return
    exists = psql(["--tuples-only", "--no-align", "--command",
                   "SELECT to_regclass('usa_atlas_pipeline.dataset') IS NOT NULL"], capture=True)
    if exists == "t":
        managed = psql(["--tuples-only", "--no-align", "--command",
                        "SELECT EXISTS(SELECT 1 FROM usa_atlas_pipeline.dataset)"], capture=True)
        if managed == "t":
            raise AdmissionError("pipeline_managed_target_use_auto_ingest")


'''


def patch_loader(text,pin):
    if 'def reject_pipeline_managed_target(' in text:raise RuntimeError('loader_already_patched_unexpected_baseline')
    needle='def _load_database_locked(sources: list[str], full_dir: Path) -> LoadOutcome:\n'
    if text.count(needle)!=1:raise RuntimeError('loader_load_entrypoint_changed')
    text=text.replace(needle,GUARD+needle+'    reject_pipeline_managed_target()\n')
    needle='def _append_database_locked(source: str, full_dir: Path) -> LoadOutcome:\n'
    if needle in text:text=text.replace(needle,needle+'    reject_pipeline_managed_target()\n')
    needle='def verify_database(sources: list[str], full_dir: Path = FULL) -> dict[str, object]:\n'
    if needle in text:
        # Preserve its existing docstring as a docstring; guard immediately
        # after acquiring its original loader lock.
        start=text.index(needle);end=text.find('\ndef ',start+len(needle))
        if end<0:end=len(text)
        block=text[start:end]
        lock='    with loader_lock(full_dir):\n'
        if block.count(lock)!=1:raise RuntimeError('loader_verify_lock_changed')
        text=text[:start]+block.replace(lock,lock+'        reject_pipeline_managed_target()\n')+text[end:]
    text,count=re.subn(r'EXPECTED_SCHEMA_CATALOG_SHA256 = "[0-9a-f]{64}"',
                      'EXPECTED_SCHEMA_CATALOG_SHA256 = "'+pin+'"',text)
    if count!=1:raise RuntimeError('loader_catalog_pin_location_changed')
    ast.parse(text)
    return text


def stage_path(name,version):return STAGE/(name+'.'+version)


def write_stage(path,text):
    path.write_text(text);os.chmod(path,0o600)


def verify_preparation(preparation):
    """Re-derive every immutable staged byte from bound v2 backups and DDL."""
    extension_path=ROOT/'database/pipeline_schema.sql'
    extension=extension_path.read_text()
    if hashlib.sha256(extension.encode()).hexdigest()!=preparation['pipeline_schema_sha256']:
        raise RuntimeError('prepared_pipeline_schema_changed')
    for name,digest in preparation['baseline_hashes'].items():
        if ingest.sha(stage_path(name,'v2'))!=digest:raise RuntimeError('prepared_v2_backup_changed')
    old_schema=stage_path('local_schema','v2').read_text()
    expected_schema=old_schema.rstrip()[:-len('COMMIT;')]+'\n-- Automatic source pipeline, v3 additive extension.\n'+extension+'\nCOMMIT;\n'
    if hashlib.sha256(expected_schema.encode()).hexdigest()!=preparation['schema_sha256']:
        raise RuntimeError('prepared_v3_schema_binding_changed')
    expected={name+'.v3':expected_schema for name in ('local_schema','production_schema')}
    guards={}
    for name in ('local_loader','production_loader'):
        original=stage_path(name,'v2').read_text()
        expected[name+'.v3-template']=patch_loader(original,'V3_CATALOG_PIN_PENDING')
        guards[name]={'load':True,'append':'def _append_database_locked(' in original,
                      'verify':'def verify_database(' in original}
    hashes={}
    for filename,content in expected.items():
        digest=hashlib.sha256(content.encode()).hexdigest()
        if ingest.sha(STAGE/filename)!=digest:raise RuntimeError('prepared_v3_copy_changed')
        hashes[filename]=digest
    if preparation.get('prepared_v3_hashes',hashes)!=hashes:
        raise RuntimeError('prepared_v3_hash_bindings_changed')
    preparation['prepared_v3_hashes']=hashes
    preparation['legacy_guard_entrypoints']=guards
    return extension


def verify_materialized(preparation,pin):
    verify_preparation(preparation)
    for name in ('local_loader','production_loader'):
        expected=stage_path(name,'v3-template').read_text().replace('V3_CATALOG_PIN_PENDING',pin)
        if ingest.sha(stage_path(name,'v3'))!=hashlib.sha256(expected.encode()).hexdigest():
            raise RuntimeError('prepared_materialized_loader_changed')


def prepare():
    STAGE.mkdir(parents=True,exist_ok=True)
    extension_path=ROOT/'database/pipeline_schema.sql'
    extension=extension_path.read_text()
    preparation=STAGE/'preparation.json'
    if preparation.exists():
        prior=ingest.read_json(preparation)
        verify_preparation(prior)
        ingest.save(preparation,prior)
        return prior
    originals={name:path.read_text() for name,path in PATHS.items()}
    if any(hashlib.sha256(originals[name].encode()).hexdigest()!=OLD_SCHEMA for name in ('local_schema','production_schema')):
        raise RuntimeError('expected_known_v2_schema_baseline_missing')
    for name in ('local_loader','production_loader'):
        if ingest.extract_constant(PATHS[name],'EXPECTED_SCHEMA_CATALOG_SHA256')!=OLD_CATALOG:
            raise RuntimeError('expected_known_v2_loader_pin_missing')
    schema=originals['local_schema']
    if not schema.rstrip().endswith('COMMIT;'):raise RuntimeError('v2_schema_transaction_boundary_changed')
    v3=schema.rstrip()[:-len('COMMIT;')]+'\n-- Automatic source pipeline, v3 additive extension.\n'+extension+'\nCOMMIT;\n'
    for name,text in originals.items():write_stage(stage_path(name,'v2'),text)
    for name in ('local_schema','production_schema'):write_stage(stage_path(name,'v3'),v3)
    for name in ('local_loader','production_loader'):
        write_stage(stage_path(name,'v3-template'),patch_loader(originals[name],'V3_CATALOG_PIN_PENDING'))
    report={'status':'prepared_not_deployed','prepared_at':datetime.now(timezone.utc).isoformat(),
            'baseline_schema_sha256':OLD_SCHEMA,'baseline_catalog_sha256':OLD_CATALOG,
            'baseline_hashes':{name:ingest.sha(stage_path(name,'v2')) for name in PATHS},
            'baseline_modes':{name:path.stat().st_mode&0o777 for name,path in PATHS.items()},
            'pipeline_schema_sha256':ingest.sha(extension_path),'schema_sha256':ingest.sha(stage_path('local_schema','v3')),
            'extension_objects':{'namespace':NAMESPACE,'tables':TABLE_COLUMNS,'indexes':sorted(INDEXES)},
            'catalog_pin_strategy':'Exact verified v2 baseline; controlled additive DDL; unchanged full core catalog and strict new-namespace object accounting; record canonical v3 hash before commit.'}
    verify_preparation(report)
    ingest.save(preparation,report);return report


def catalog(db,query):
    text=db.query(query);return hashlib.sha256(text.encode()).hexdigest(),json.loads(text)


def check_extension(before,after):
    filtered={key:[row for row in rows if row.get('schema')!=NAMESPACE and not (key=='schemas' and row.get('name')==NAMESPACE)] for key,rows in after.items()}
    if filtered!=before:raise RuntimeError('migration_changed_existing_core_catalog')
    schemas=[r for r in after['schemas'] if r['name']==NAMESPACE]
    if schemas!=[{'name':NAMESPACE,'owner':'$CURRENT_ROLE'}]:raise RuntimeError('pipeline_namespace_owner_mismatch')
    relations=[r for r in after['relations'] if r['schema']==NAMESPACE]
    if {r['name'] for r in relations if r['kind']=='r'}!=set(TABLE_COLUMNS):raise RuntimeError('pipeline_table_inventory_mismatch')
    if {r['name'] for r in relations if r['kind']=='i'}!=INDEXES or len(relations)!=len(TABLE_COLUMNS)+len(INDEXES):raise RuntimeError('pipeline_relation_inventory_mismatch')
    if any(r['owner']!='$CURRENT_ROLE' or r['options'] or r['row_security'] or r['force_row_security'] or r['persistence']!='p' for r in relations):raise RuntimeError('pipeline_relation_options_mismatch')
    for table,names in TABLE_COLUMNS.items():
        columns=[r for r in after['columns'] if r['schema']==NAMESPACE and r['relation']==table]
        if [r['name'] for r in columns]!=names:raise RuntimeError('pipeline_column_inventory_mismatch')
    expected_types={name for table in TABLE_COLUMNS for name in (table,'_'+table)}
    if {r['name'] for r in after['types'] if r['schema']==NAMESPACE}!=expected_types:raise RuntimeError('pipeline_type_inventory_mismatch')
    if len([r for r in after['constraints'] if r['schema']==NAMESPACE])!=29:raise RuntimeError('pipeline_constraint_inventory_mismatch')
    for key in ('routines','triggers','rules','policies','operators','collations','conversions','enum_labels'):
        if any(r.get('schema')==NAMESPACE for r in after[key]):raise RuntimeError('unexpected_pipeline_executable_or_policy_object')


def deploy(version,preparation):
    for name,path in PATHS.items():
        content=stage_path(name,version).read_bytes()
        tmp=path.with_name(path.name+'.pipeline-'+uuid.uuid4().hex+'.tmp')
        tmp.write_bytes(content);os.chmod(tmp,preparation['baseline_modes'][name]);tmp.replace(path)


def apply(preparation):
    query=ingest.extract_constant(stage_path('local_loader','v2'),'CATALOG_DOCUMENT_SQL')
    journal_path=STAGE/'deployment.json'
    with ExitStack() as stack:
        for path in (STAGE/'migration.lock',ROOT/'full/state/.usa-atlas-load.lock',ingest.PRODUCTION/'full/state/.usa-atlas-load.lock'):
            f=stack.enter_context(path.open('a+'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify_preparation(preparation)
        with ingest.Session(STAGE/'private-errors') as db:
            observed,before=catalog(db,query)
            if observed!=OLD_CATALOG:
                # Recovery after COMMIT but before the success receipt. Never
                # roll back a committed v3 DB by merely restoring old files.
                if ingest.SCHEMA_MANIFEST.exists():
                    meta=ingest.read_json(ingest.SCHEMA_MANIFEST)
                    if (meta.get('format')=='usa_atlas_pipeline_schema_v3'
                        and observed==meta.get('catalog_sha256')
                        and meta.get('schema_sha256')==preparation['schema_sha256']
                        and meta.get('pipeline_schema_sha256')==preparation['pipeline_schema_sha256']):
                        verify_materialized(preparation,observed)
                        if db.query('SELECT schema_sha256 FROM usa_atlas.schema_metadata WHERE singleton;')!=preparation['schema_sha256']:
                            raise RuntimeError('committed_v3_schema_metadata_mismatch')
                        for name,path in PATHS.items():
                            digest=ingest.sha(stage_path(name,'v3'))
                            if meta.get('deployed_files',{}).get(name)!=digest or ingest.sha(path)!=digest:
                                raise RuntimeError('committed_v3_code_requires_recovery')
                        return {'status':'already_pass','reason':'verified_existing_v3','catalog_sha256':observed,'schema_sha256':meta['schema_sha256']}
                raise RuntimeError('database_not_at_known_v2_or_committed_v3')
            # A crash before COMMIT may have left some/all v3 code files in place.
            for name,path in PATHS.items():
                allowed={preparation['baseline_hashes'][name]}
                if stage_path(name,'v3').exists():allowed.add(ingest.sha(stage_path(name,'v3')))
                if ingest.sha(path) not in allowed:raise RuntimeError('deployment_changed_outside_migration')
            deploy('v2',preparation)
            ingest.SCHEMA_MANIFEST.unlink(missing_ok=True)
            if db.query('SELECT schema_sha256 FROM usa_atlas.schema_metadata WHERE singleton;')!=OLD_SCHEMA:
                raise RuntimeError('database_v2_schema_metadata_mismatch')
            db.query('LOCK TABLE usa_atlas.observation_data,usa_atlas.ingest_run,usa_atlas.catalog_field,usa_atlas.schema_metadata IN SHARE ROW EXCLUSIVE MODE;')
            # Execute exactly the just-verified bytes, avoiding a second file read.
            db.query(verify_preparation(preparation))
            actual,after=catalog(db,query)
            check_extension(before,after)
            if db.query('SELECT (SELECT count(*) FROM usa_atlas_pipeline.dataset)+(SELECT count(*) FROM usa_atlas_pipeline.snapshot_batch)+(SELECT count(*) FROM usa_atlas_pipeline.generic_record);')!='0':
                raise RuntimeError('new_pipeline_namespace_not_empty')
            for name in ('local_loader','production_loader'):
                text=stage_path(name,'v3-template').read_text().replace('V3_CATALOG_PIN_PENDING',actual)
                ast.parse(text);write_stage(stage_path(name,'v3'),text)
            verify_materialized(preparation,actual)
            meta={'format':'usa_atlas_pipeline_schema_v3','schema_sha256':preparation['schema_sha256'],
                  'catalog_sha256':actual,'pipeline_schema_sha256':preparation['pipeline_schema_sha256'],
                  'previous_schema_sha256':OLD_SCHEMA,'previous_catalog_sha256':OLD_CATALOG,
                  'generated_from':'Controlled transactional extension with unchanged v2 core catalog and strict namespace object accounting',
                  'deployed_files':{name:ingest.sha(stage_path(name,'v3')) for name in PATHS}}
            ingest.save(STAGE/'catalog-v3.json',after)
            ingest.save(journal_path,{'phase':'validated_before_deployment',**meta})
            commit_started=False
            try:
                deploy('v3',preparation)
                ingest.save(ingest.SCHEMA_MANIFEST,meta)
                for name,path in PATHS.items():
                    if ingest.sha(path)!=meta['deployed_files'][name]:raise RuntimeError('deployed_v3_copy_changed')
                db.query('UPDATE usa_atlas.schema_metadata SET schema_sha256='+ingest.literal(preparation['schema_sha256'])+' WHERE singleton;')
                ingest.save(journal_path,{'phase':'files_deployed_pending_commit',**meta})
                commit_started=True
                db.query('COMMIT;');db.committed=True
            except BaseException:
                if not commit_started:
                    deploy('v2',preparation);ingest.SCHEMA_MANIFEST.unlink(missing_ok=True)
                else:
                    # Another connection may still see v2 while this backend is
                    # committing. Keep v3 files, close this session, and resolve
                    # only on the next run after reacquiring the advisory lock.
                    ingest.save(journal_path,{'phase':'ambiguous_commit_retry_with_locks',**meta})
                    raise RuntimeError('ambiguous_commit_outcome_retry_migration')
                raise
            ingest.save(journal_path,{'phase':'complete',**meta})
            return {'status':'pass','reason':'pipeline_v3_committed','catalog_sha256':actual,'schema_sha256':preparation['schema_sha256'],'previous_catalog_sha256':OLD_CATALOG,'extension_schema':NAMESPACE}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    try:
        preparation=prepare()
        result=apply(preparation) if args.apply else {'status':'prepared','reason':'reviewable_files_only_database_not_contacted','preparation':str(STAGE/'preparation.json'),'schema_sha256':preparation['schema_sha256']}
    except ingest.AdmissionError as exc:result={'status':exc.status,'reason':exc.reason}
    except (PermissionError,BlockingIOError,FileNotFoundError):result={'status':'deferred_maintenance','reason':'required_host_access_or_lock_unavailable'}
    except (RuntimeError,ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:
        result={'status':'deferred_maintenance','reason':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__}
    result.update(recorded_at=datetime.now(timezone.utc).isoformat(),database='usa_atlas',container=ingest.CONTAINER)
    ingest.save(args.result,result);print(json.dumps(result),flush=True)
    return 0 if result['status'] in ('pass','already_pass','prepared') else 75


if __name__=='__main__':raise SystemExit(main())
