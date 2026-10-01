#!/usr/bin/env python3
"""Explicit, guarded USA Atlas maintenance. Never targets another database/container.

Run --help. Large backup/build state belongs under /srv/usa-atlas/maintenance,
not Git. Compaction preserves every original observation column through a view.
The staging manifest coordinates schema/loader deployment; --apply requires
the user's authorization for maintenance of this project.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = 'usa-atlas-postgres'
PRODUCTION = Path('/opt/usa-atlas-production/admission-20260922')
STATE = Path('/srv/usa-atlas/maintenance/20260928-compact')
STAGED = Path('/srv/usa-atlas/compact-20260928-staged-code')
FLOOR = 12 * 1024**3
OWNS_MAINTENANCE = False
FIELDS = 'geo_id,geo_type,period,field_id,catalog_field_id,value,unit,source,source_release,source_url,methodology_note,retrieved_at,ingest_id'
STORED = FIELDS.replace('source_url', 'resource_id').replace('methodology_note', 'methodology_id')
EXACT_BOUNDARIES = [None] + [f'{n:02d}' for n in range(100)] + [None]

# Only lightweight catalog evidence: no data scan and no DDL. The old runner's
# FK constraints are uncommitted and intentionally excluded from this packet.
RESUME_CATALOG_SQL = """SELECT json_build_object(
 'relations',(SELECT json_agg(t ORDER BY name) FROM (
   SELECT c.relname name,c.oid::bigint oid,c.relkind kind,
     CASE WHEN c.relkind='v' THEN pg_get_viewdef(c.oid,true) END view_definition
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='usa_atlas' AND c.relname IN
     ('observation','observation_data','source_resource','methodology','observation_compact_check')
 ) t),
 'indexes',(SELECT json_agg(t ORDER BY name) FROM (
   SELECT c.relname name,c.oid::bigint oid,i.indisvalid valid,i.indisready ready,
     i.indisunique is_unique,i.indisprimary is_primary,pg_get_indexdef(c.oid) definition
   FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
   WHERE i.indrelid='usa_atlas.observation_data'::regclass
 ) t),
 'primary_key',(SELECT json_agg(t ORDER BY name) FROM (
   SELECT conname name,convalidated validated,pg_get_constraintdef(oid,true) definition
   FROM pg_constraint WHERE conrelid='usa_atlas.observation_data'::regclass AND contype='p'
 ) t)
);"""


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    os.chmod(temp, 0o600)
    temp.replace(path)


def progress(phase, **kwargs):
    report = {'phase': phase, 'updated_at': datetime.now(timezone.utc).isoformat(),
              'pid': os.getpid(), 'free_bytes': shutil.disk_usage(STATE).free, **kwargs}
    save(STATE / 'progress.json', report)
    print(json.dumps(report), flush=True)


def command(client='psql'):
    if client == 'psql':
        tail = 'exec psql -X -w -qAt --username "$POSTGRES_USER" --dbname usa_atlas --set ON_ERROR_STOP=1'
    elif client == 'pg_dump':
        tail = 'exec pg_dump --username "$POSTGRES_USER" --dbname usa_atlas --schema=usa_atlas --format=custom --compress=6'
    elif client == 'pg_restore':
        tail = 'exec pg_restore --exit-on-error --file=/dev/null'
    else: raise ValueError('unsupported_client')
    return ['docker', 'exec', '-i', '-u', 'postgres', '-e', 'PGAPPNAME=usa_atlas_storage_cleanup', CONTAINER, 'sh', '-c', tail]


def sql(query, timeout=None):
    result = subprocess.run(command(), input="SET lock_timeout='3s';\n"+query, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        STATE.mkdir(parents=True,exist_ok=True)
        error=STATE/'statement-error.private.log'
        error.write_text(result.stderr)
        os.chmod(error,0o600)
        raise RuntimeError('postgres_statement_failed_details_private')
    return result.stdout.strip()


class LockedSession:
    def __enter__(self):
        self.error = open(STATE / 'session-errors.private.log', 'w')
        os.chmod(STATE / 'session-errors.private.log', 0o600)
        self.p = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.error, text=True, bufsize=1)
        self.query("SET lock_timeout='3s'; BEGIN; SELECT pg_advisory_xact_lock(66280928); "
                   'LOCK TABLE usa_atlas.observation,usa_atlas.catalog_field,usa_atlas.ingest_run,'
                   'usa_atlas.observation_stage,usa_atlas.catalog_field_stage,usa_atlas.schema_metadata IN SHARE MODE;')
        return self

    def query(self, text):
        marker = 'END_' + uuid.uuid4().hex
        # Loader catalog SQL is a complete SELECT without a trailing semicolon.
        # Always terminate the caller's statement before our protocol marker;
        # a separate newline also closes any trailing SQL line comment.
        self.p.stdin.write(text + "\n;\nSELECT '" + marker + "';\n")
        self.p.stdin.flush()
        lines = []
        while True:
            line = self.p.stdout.readline()
            if not line: raise RuntimeError('locked_session_failed_details_private')
            if line.strip() == marker: return '\n'.join(lines).strip()
            lines.append(line.rstrip('\n'))

    def __exit__(self, *exc):
        if self.p.poll() is None:
            try: self.query('ROLLBACK;')
            except (RuntimeError, BrokenPipeError): pass
        if not self.p.stdin.closed: self.p.stdin.close()
        self.p.wait(timeout=20)
        self.p.stdout.close()
        self.error.close()


def fingerprint(relation):
    # Include the complete v1 record, including canonical key and provenance.
    # Two 64-bit halves of MD5 are summed as exact numeric, separately per source.
    query = f"""SET statement_timeout=0; SET work_mem='64MB';
    SET max_parallel_workers_per_gather=3; SET enable_parallel_hash=off;
    SELECT json_agg(t ORDER BY source) FROM (
      SELECT source,count(*) rows,
        sum(('x'||substr(digest,1,16))::bit(64)::bigint) digest_hi_sum,
        sum(('x'||substr(digest,17,16))::bit(64)::bigint) digest_lo_sum
      FROM (SELECT source,md5(ROW({FIELDS})::text) digest FROM {relation}) r GROUP BY source
    ) t;"""
    return json.loads(sql(query))


CREATE_SHADOW = """
CREATE TABLE IF NOT EXISTS usa_atlas.source_resource (
 resource_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_url text NOT NULL UNIQUE CHECK(source_url ~ '^https://')
);
CREATE TABLE IF NOT EXISTS usa_atlas.methodology (
 methodology_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 methodology_note text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS usa_atlas.observation_data (
 geo_id text NOT NULL,geo_type text NOT NULL,period text NOT NULL,field_id text NOT NULL,
 catalog_field_id text NOT NULL,value double precision NOT NULL CHECK(value > '-Infinity'::double precision AND value < 'Infinity'::double precision),
 unit text NOT NULL,source text NOT NULL,source_release text NOT NULL,
 resource_id bigint NOT NULL,methodology_id bigint NOT NULL,retrieved_at timestamptz NOT NULL,ingest_id uuid NOT NULL
);
"""


VIEW_SELECT = """SELECT o.geo_id,o.geo_type,o.period,o.field_id,o.catalog_field_id,o.value,
 o.unit,o.source,o.source_release,r.source_url,m.methodology_note,o.retrieved_at,o.ingest_id
 FROM usa_atlas.observation_data o
 JOIN usa_atlas.source_resource r USING(resource_id)
 JOIN usa_atlas.methodology m USING(methodology_id)"""


def backup(renew_unbound=False):
    path = STATE / 'usa-atlas-before-compact.dump'
    metadata = STATE / 'backup.json'
    if metadata.exists():
        info = json.loads(metadata.read_text())
        baseline = STATE / 'source-fingerprint.json'
        bound = (baseline.exists()
                 and info.get('source_fingerprint_sha256') == sha(baseline))
        if bound:
            if path.exists() and sha(path) == info['sha256']: return info
            raise RuntimeError('prior_backup_hash_mismatch')
        if not renew_unbound:
            raise RuntimeError('backup_reuse_requires_bound_source_fingerprint')
        # Called only while the maintenance and source-table locks are held.
        # Never add a binding to an old archive retrospectively. Preserve the
        # entire old checkpoint and dump the current locked source again.
        if not OWNS_MAINTENANCE:
            raise RuntimeError('backup_renewal_requires_maintenance_locks')
        archive = STATE / ('unbound-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        archive.mkdir(mode=0o700)
        progress('archiving_unbound_backup', archived_checkpoint=str(archive))
        for old in (path, metadata, baseline):
            if old.exists(): old.rename(archive / old.name)
    if path.exists(): raise RuntimeError('incomplete_backup_present_restore_or_review_manually')
    progress('backup_running')
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        proc = subprocess.run(command('pg_dump'), stdout=output, stderr=subprocess.PIPE)
    if proc.returncode: raise RuntimeError('backup_failed')
    progress('backup_verify_running', backup_bytes=path.stat().st_size)
    with path.open('rb') as stream:
        proc = subprocess.run(command('pg_restore'), stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode: raise RuntimeError('backup_archive_readback_failed')
    info = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path),
            'verified': 'pg_restore read entire archive to /dev/null; no restore into live database',
            'scope': 'full usa_atlas schema and all data before compaction'}
    save(metadata, info)
    return info


def extract_constant(path, name):
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError('required_loader_constant_missing')


def validate_resume_packet(path):
    packet = json.loads(Path(path).read_text())
    if packet.get('format') != 'usa_atlas_locked_exact_checkpoint_v1':
        raise RuntimeError('unsupported_exact_checkpoint')
    if packet.get('container') != CONTAINER or packet.get('database') != 'usa_atlas':
        raise RuntimeError('exact_checkpoint_wrong_database')
    source = packet.get('source_fingerprint')
    compact = packet.get('compact_fingerprint')
    if not source or source != compact:
        raise RuntimeError('exact_checkpoint_fingerprints_mismatch')
    expected = sum(r['rows'] for r in source)
    evidence = packet.get('exact_validation', {})
    if evidence.get('expected_rows') != expected or evidence.get('actual_rows') != expected:
        raise RuntimeError('exact_checkpoint_counts_mismatch')
    # The guard captures the old process immediately before its duplicated tail.
    old_boundaries = [None] + [f'{n:02d}' for n in range(100)] + [':']
    old_ranges = [{'lower_inclusive': a, 'upper_exclusive': b, 'mismatches': 0}
                  for a,b in zip(old_boundaries,old_boundaries[1:])]
    if evidence.get('ranges') != old_ranges or evidence.get('complete') is not False:
        raise RuntimeError('exact_checkpoint_not_complete_numeric_prefix')
    # Discard [99, ':'); it is empty in this database's collation. Recheck the
    # corrected [99, +infinity) tail, never reuse the old full-table tail.
    packet['reusable_ranges'] = old_ranges[:-1]
    return packet


def validate_complete_shadow(catalog):
    kinds = {r['name']:r['kind'] for r in catalog.get('relations') or []}
    if kinds != {'observation':'r','observation_data':'r','source_resource':'r',
                 'methodology':'r','observation_compact_check':'v'}:
        raise RuntimeError('resume_requires_existing_complete_shadow')
    indexes = {r['name']:r for r in catalog.get('indexes') or []}
    if set(indexes) != {'observation_data_pkey','observation_data_lookup_idx','observation_data_ingest_idx'}:
        raise RuntimeError('resume_requires_all_existing_indexes')
    if any(not r['valid'] or not r['ready'] for r in indexes.values()):
        raise RuntimeError('resume_index_not_ready')
    pk = indexes['observation_data_pkey']
    if not pk['is_unique'] or not pk['is_primary']:
        raise RuntimeError('resume_unique_primary_key_required')
    if catalog.get('primary_key') != [{'name':'observation_data_pkey','validated':True,
                                     'definition':'PRIMARY KEY (geo_id, period, field_id, source_release)'}]:
        raise RuntimeError('resume_primary_key_definition_mismatch')


def exact_validation(expected_rows, resume=None):
    """Every old primary key must reconstruct its exact 13-column record.

    Unique new PK + equal complete counts + every old key present/equal implies
    no new-only rows. Range predicates limit join/sort scratch without sampling.
    """
    actual_rows = int(sql('SELECT count(*) FROM usa_atlas.observation_data;'))
    if actual_rows != expected_rows: raise RuntimeError('exact_count_mismatch')
    boundaries = EXACT_BOUNDARIES
    results = list(resume['reusable_ranges']) if resume else []
    expected_prefix = [{'lower_inclusive': a, 'upper_exclusive': b, 'mismatches': 0}
                       for a,b in zip(boundaries,boundaries[1:])][:len(results)]
    if results != expected_prefix: raise RuntimeError('exact_checkpoint_ranges_not_contiguous')
    for index,(lower,upper) in enumerate(zip(boundaries,boundaries[1:])):
        if index < len(results): continue
        predicates=[]
        if lower is not None:predicates.append(f"geo_id >= '{lower}'")
        if upper is not None:predicates.append(f"geo_id < '{upper}'")
        where=' AND '.join(predicates)
        # Large parallel hash joins exceeded the container's shared-memory limit
        # while checking California. A serial join uses backend-local memory and
        # can spill within the existing temp-file limit. Keep the exact comparison.
        query=f"""SET statement_timeout=0; SET work_mem='128MB'; SET temp_file_limit='16GB';
        SET max_parallel_workers_per_gather=0; SET enable_parallel_hash=off;
        SELECT count(*) FROM
          (SELECT * FROM usa_atlas.observation WHERE {where}) o
        LEFT JOIN (SELECT * FROM usa_atlas.observation_data WHERE {where}) n
          USING(geo_id,period,field_id,source_release)
        LEFT JOIN usa_atlas.source_resource r ON r.resource_id=n.resource_id
        LEFT JOIN usa_atlas.methodology m ON m.methodology_id=n.methodology_id
        WHERE ROW(o.geo_type,o.catalog_field_id,o.value,o.unit,o.source,o.source_url,o.methodology_note,o.retrieved_at,o.ingest_id)
          IS DISTINCT FROM ROW(n.geo_type,n.catalog_field_id,n.value,n.unit,n.source,r.source_url,m.methodology_note,n.retrieved_at,n.ingest_id);"""
        progress('exact_range_validation_running',range_index=index,ranges=len(boundaries)-1,lower=lower,upper=upper,
                 reused_ranges=len(resume['reusable_ranges']) if resume else 0)
        mismatches=int(sql(query))
        results.append({'lower_inclusive':lower,'upper_exclusive':upper,'mismatches':mismatches})
        save(STATE/'exact-validation.json',{'expected_rows':expected_rows,'actual_rows':actual_rows,'ranges':results,
                                          'complete':index==len(boundaries)-2,
                                          'resumed_checkpoint_sha256':resume.get('packet_sha256') if resume else None})
        if mismatches:raise RuntimeError('exact_record_mismatch')
    return {'rows':actual_rows,'ranges':len(results),'mismatches':0}


def deploy_code(version, manifest, require_version):
    for name in ('schema.sql','load.py'):
        current=PRODUCTION/'database'/name
        if sha(current)!=manifest['files'][f'{name}.{require_version}']:
            raise RuntimeError('deployment_changed_externally')
    for name in ('schema.sql','load.py'):
        current=PRODUCTION/'database'/name
        temp=current.with_suffix(current.suffix+'.compact.tmp')
        temp.write_bytes((STAGED/f'{name}.{version}').read_bytes())
        os.chmod(temp,current.stat().st_mode & 0o777)
        temp.replace(current)


def compact(apply, renew_unbound_backup=False, resume_exact_checkpoint=None):
    global OWNS_MAINTENANCE
    STATE.mkdir(parents=True, exist_ok=True)
    kind = sql("BEGIN READ ONLY; SELECT relkind FROM pg_class WHERE oid=to_regclass('usa_atlas.observation'); ROLLBACK;", 15)
    if kind == 'v':
        print(json.dumps({'status': 'already_compact_no_changes'})); return
    if kind != 'r': raise RuntimeError('expected_existing_observation_table_not_found')
    required_free = (30 if resume_exact_checkpoint else 74) * 1024**3
    if not apply:
        print(json.dumps({'status': 'plan_only', 'container': CONTAINER, 'database': 'usa_atlas',
                          'required_free_bytes': required_free, 'free_bytes': shutil.disk_usage(STATE).free})); return
    if shutil.disk_usage(STATE).free < required_free: raise RuntimeError('insufficient_initial_headroom')
    resume = validate_resume_packet(resume_exact_checkpoint) if resume_exact_checkpoint else None
    if resume: resume['packet_sha256'] = sha(resume_exact_checkpoint)
    with ExitStack() as stack:
        for path in (STATE / 'process.lock', ROOT / 'full/state/.usa-atlas-load.lock', PRODUCTION / 'full/state/.usa-atlas-load.lock'):
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open('a+'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        OWNS_MAINTENANCE = True
        with LockedSession() as locker:
            if resume:
                # No table/index/dictionary creation, new backup or recopy is
                # permitted in this mode. These locks also bind the resumed
                # compact fingerprint and exact checks to one stable shadow.
                locker.query('LOCK TABLE usa_atlas.observation_data,usa_atlas.source_resource,usa_atlas.methodology IN SHARE MODE;')
                catalog = json.loads(locker.query(RESUME_CATALOG_SQL))
                validate_complete_shadow(catalog)
                if catalog != resume['catalog']:
                    raise RuntimeError('exact_checkpoint_relation_identity_changed')
                for name in ('backup.json','usa-atlas-before-compact.dump','source-fingerprint.json','compact-fingerprint.json'):
                    if not (STATE/name).is_file(): raise RuntimeError('resume_requires_complete_bound_backup_and_fingerprints')
                info = json.loads((STATE/'backup.json').read_text())
                if (info.get('source_fingerprint_sha256') != sha(STATE/'source-fingerprint.json')
                    or info.get('sha256') != resume['backup_sha256']
                    or sha(STATE/'source-fingerprint.json') != resume['source_fingerprint_sha256']
                    or sha(STATE/'compact-fingerprint.json') != resume['compact_fingerprint_sha256']):
                    raise RuntimeError('exact_checkpoint_backup_binding_changed')
            loading = locker.query("SELECT count(*) FROM usa_atlas.ingest_run WHERE status='loading';")
            if loading != '0': raise RuntimeError('active_ingest_found')
            progress('locked_source')
            original_bytes = int(locker.query("SELECT pg_total_relation_size('usa_atlas.observation');"))
            baseline_schema = locker.query("SELECT schema_sha256 FROM usa_atlas.schema_metadata;")
            if resume and baseline_schema != resume['schema_sha256']:
                raise RuntimeError('exact_checkpoint_schema_changed')
            if resume:
                # Strict resume can never fall through to pg_dump, even if a
                # checkpoint file changes between the preconditions and reuse.
                if sha(STATE/'usa-atlas-before-compact.dump') != info['sha256']:
                    raise RuntimeError('resume_backup_archive_hash_mismatch')
                backup_info = info
            else:
                backup_info = backup(renew_unbound=renew_unbound_backup)
            progress('source_fingerprint_running')
            baseline = fingerprint('usa_atlas.observation')
            prior = STATE / 'source-fingerprint.json'
            if prior.exists() and json.loads(prior.read_text()) != baseline:
                raise RuntimeError('source_changed_since_prior_attempt')
            if resume and baseline != resume['source_fingerprint']:
                raise RuntimeError('exact_checkpoint_source_fingerprint_changed')
            save(prior, baseline)
            backup_info['source_fingerprint_sha256'] = sha(prior)
            save(STATE / 'backup.json', backup_info)
            expected_rows = sum(r['rows'] for r in baseline)
            if resume:
                progress('resume_complete_shadow_validation_running', expected_rows=expected_rows,
                         checkpoint_sha256=resume['packet_sha256'], reused_ranges=len(resume['reusable_ranges']))
            else:
                progress('dictionary_build_running', expected_rows=expected_rows)
                sql(CREATE_SHADOW)
                sql("SET statement_timeout=0; SET work_mem='128MB'; INSERT INTO usa_atlas.source_resource(source_url) SELECT DISTINCT source_url FROM usa_atlas.observation ON CONFLICT(source_url) DO NOTHING;")
                sql("SET statement_timeout=0; SET work_mem='128MB'; INSERT INTO usa_atlas.methodology(methodology_note) SELECT DISTINCT methodology_note FROM usa_atlas.observation ON CONFLICT(methodology_note) DO NOTHING;")
            runs = json.loads(locker.query("SELECT json_agg(i ORDER BY source) FROM (SELECT source,ingest_id,row_count FROM usa_atlas.ingest_run WHERE status='pass') i;"))
            completed = 0
            for run in runs:
                if not re.fullmatch('[0-9a-f-]{36}',run['ingest_id']): raise RuntimeError('invalid_ingest_uuid')
                ingest = run['ingest_id']; expected = int(run['row_count'])
                present = int(sql(f"SELECT count(*) FROM usa_atlas.observation_data WHERE ingest_id='{ingest}'::uuid;"))
                if present not in (0, expected): raise RuntimeError('partial_shadow_source_review_required')
                if resume and present != expected: raise RuntimeError('resume_shadow_ingest_incomplete_no_copy_allowed')
                if not present:
                    if resume: raise RuntimeError('resume_copy_forbidden')
                    if shutil.disk_usage(STATE).free < FLOOR + 30 * 1024**3: raise RuntimeError('insufficient_copy_headroom')
                    progress('copy_source_running', source=run['source'], source_expected_rows=expected, completed_rows=completed, expected_rows=expected_rows)
                    query = f"""SET statement_timeout=0; SET work_mem='128MB';
                    DO $$ DECLARE n bigint; BEGIN
                    INSERT INTO usa_atlas.observation_data ({STORED})
                    SELECT o.geo_id,o.geo_type,o.period,o.field_id,o.catalog_field_id,o.value,o.unit,o.source,o.source_release,
                      r.resource_id,m.methodology_id,o.retrieved_at,o.ingest_id
                    FROM usa_atlas.observation o JOIN usa_atlas.source_resource r USING(source_url)
                    JOIN usa_atlas.methodology m USING(methodology_note) WHERE o.ingest_id='{ingest}'::uuid;
                    GET DIAGNOSTICS n=ROW_COUNT; IF n<>{expected} THEN RAISE EXCEPTION 'row_count_mismatch'; END IF;
                    END $$;"""
                    sql(query)
                completed += expected
                save(STATE / 'copied-sources.json', {'last_source':run['source'],'completed_rows':completed,'expected_rows':expected_rows})
            if completed != expected_rows: raise RuntimeError('passed_ingest_total_mismatch')
            if not resume:
                progress('indexes_running', expected_rows=expected_rows)
                sql("SET statement_timeout=0; SET maintenance_work_mem='256MB'; CREATE UNIQUE INDEX IF NOT EXISTS observation_data_pkey ON usa_atlas.observation_data(geo_id,period,field_id,source_release);")
                sql("SET statement_timeout=0; SET maintenance_work_mem='256MB'; CREATE INDEX IF NOT EXISTS observation_data_lookup_idx ON usa_atlas.observation_data(catalog_field_id,geo_type,geo_id,period DESC) INCLUDE(value,unit,field_id,source_release);")
                sql("SET statement_timeout=0; SET maintenance_work_mem='256MB'; CREATE INDEX IF NOT EXISTS observation_data_ingest_idx ON usa_atlas.observation_data(ingest_id);")
                sql('ANALYZE usa_atlas.observation_data; ANALYZE usa_atlas.source_resource; ANALYZE usa_atlas.methodology;')
            constraints = [
                ('observation_data_pkey','PRIMARY KEY USING INDEX observation_data_pkey'),
                ('observation_data_catalog_field_id_fkey','FOREIGN KEY(catalog_field_id) REFERENCES usa_atlas.catalog_field(catalog_field_id)'),
                ('observation_data_ingest_id_fkey','FOREIGN KEY(ingest_id) REFERENCES usa_atlas.ingest_run(ingest_id)'),
                ('observation_data_resource_id_fkey','FOREIGN KEY(resource_id) REFERENCES usa_atlas.source_resource(resource_id)'),
                ('observation_data_methodology_id_fkey','FOREIGN KEY(methodology_id) REFERENCES usa_atlas.methodology(methodology_id)'),
            ]
            for name, definition in constraints:
                if resume and name=='observation_data_pkey': continue
                progress('constraint_validation_running', constraint=name)
                query=f"SET statement_timeout=0; DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='usa_atlas.observation_data'::regclass AND conname='{name}') THEN ALTER TABLE usa_atlas.observation_data ADD CONSTRAINT {name} {definition}; END IF; END $$;"
                # FK parent locks must be upgraded by their existing owner session.
                # PK is committed separately so its ACCESS EXCLUSIVE lock ends now.
                (sql if name=='observation_data_pkey' else locker.query)(query)
            # Transient view removed before final catalog pin is evaluated.
            if not resume: sql('CREATE OR REPLACE VIEW usa_atlas.observation_compact_check AS ' + VIEW_SELECT + ';')
            progress('full_fingerprint_validation_running', expected_rows=expected_rows)
            observed = fingerprint('usa_atlas.observation_compact_check')
            if resume and observed != resume['compact_fingerprint']:
                raise RuntimeError('exact_checkpoint_compact_fingerprint_changed')
            save(STATE / 'compact-fingerprint.json', observed)
            if observed != baseline: raise RuntimeError('full_record_fingerprint_mismatch')
            exact=exact_validation(expected_rows, resume)
            new_bytes = int(sql("SELECT pg_total_relation_size('usa_atlas.observation_data')+pg_total_relation_size('usa_atlas.source_resource')+pg_total_relation_size('usa_atlas.methodology');"))
            progress('validating_staged_deployment', expected_rows=expected_rows, original_relation_bytes=original_bytes, compact_relation_bytes=new_bytes,
                     estimated_net_relation_saving_bytes=original_bytes-new_bytes)
            marker=json.loads((STAGED/'staging-manifest.json').read_text())
            for name,digest in marker['files'].items():
                if sha(STAGED/name)!=digest:raise RuntimeError('staged_file_hash_mismatch')
            schema = ROOT/'database/schema.sql'
            schema_digest = sha(schema)
            if marker.get('schema_sha256') != schema_digest:
                raise RuntimeError('staged_schema_hash_mismatch')
            expected_catalog = extract_constant(ROOT/'database/load.py','EXPECTED_SCHEMA_CATALOG_SHA256')
            if marker.get('catalog_sha256') != expected_catalog or extract_constant(STAGED/'load.py.v2','EXPECTED_SCHEMA_CATALOG_SHA256') != expected_catalog:
                raise RuntimeError('staged_catalog_pin_mismatch')
            function=re.search(r'CREATE OR REPLACE FUNCTION usa_atlas\.finish_ingest\(.*?\n\$\$;',schema.read_text(),re.S)
            if not function: raise RuntimeError('writer_function_missing')
            progress('cutover_running', expected_rows=expected_rows)
            cutover="""
            DROP VIEW usa_atlas.observation_compact_check;
            ALTER TABLE usa_atlas.observation RENAME TO observation_legacy;
            ALTER TABLE usa_atlas.observation_legacy RENAME CONSTRAINT observation_pkey TO observation_legacy_pkey;
            ALTER INDEX usa_atlas.observation_lookup_idx RENAME TO observation_legacy_lookup_idx;
            ALTER INDEX usa_atlas.observation_ingest_idx RENAME TO observation_legacy_ingest_idx;
            ALTER TABLE usa_atlas.observation_data RENAME CONSTRAINT observation_data_pkey TO observation_pkey;
            ALTER INDEX usa_atlas.observation_data_lookup_idx RENAME TO observation_lookup_idx;
            ALTER INDEX usa_atlas.observation_data_ingest_idx RENAME TO observation_ingest_idx;
            CREATE VIEW usa_atlas.observation AS """ + VIEW_SELECT + ";\n" + function.group(0) + """
            GRANT SELECT ON usa_atlas.observation TO usa_atlas_reader;
            DROP TABLE usa_atlas.observation_legacy;
            """ + f"UPDATE usa_atlas.schema_metadata SET schema_sha256='{schema_digest}';"
            deploy_code('v2',marker,'v1')
            committed=False
            try:
                locker.query(cutover)
                catalog_sql=extract_constant(ROOT/'database/load.py','CATALOG_DOCUMENT_SQL')
                catalog_text=locker.query(catalog_sql)
                actual_catalog=hashlib.sha256(catalog_text.encode()).hexdigest()
                if actual_catalog != expected_catalog:
                    save(STATE/'catalog-mismatch.json',{'actual_sha256':actual_catalog,'expected_sha256':expected_catalog,'catalog':json.loads(catalog_text)})
                    raise RuntimeError('cutover_catalog_hash_mismatch_transaction_rolled_back')
                locker.query('COMMIT;')
                committed=True
            finally:
                if not committed:
                    deploy_code('v1',marker,'v2')
            after = json.loads(sql((ROOT/'database/audit_storage.sql').read_text()))
            save(STATE/'postgres-after-cleanup.json',after)
            result={'status':'complete','rows_preserved':expected_rows,'original_relation_bytes':original_bytes,
                    'compact_relation_bytes':new_bytes,'relation_bytes_freed':original_bytes-new_bytes,
                    'backup':backup_info,'old_schema_sha256':baseline_schema,'schema_sha256':schema_digest,
                    'catalog_sha256':actual_catalog,'validation':'exact keyed comparison of all 13 fields across every row; complete counts; full fingerprints; all PK/FK validated',
                    'exact_validation':exact,
                    'free_bytes_after':shutil.disk_usage(STATE).free}
            save(STATE/'result.json',result)
            save(ROOT/'research/2026-09-28/storage/postgres-cleanup-result.json',result)
            save(ROOT/'research/2026-09-28/storage/postgres-after-cleanup.json',after)
            progress('complete',**result)


def cleanup_files(apply):
    names = ('B01001','B03002','B05001','B05002','B05005','B05006','B25070')
    manifest_paths = list((ROOT/'full/state').glob('*.json'))
    code = (ROOT/'full/collect.py').read_text()
    if 'path = base.with_suffix(base.suffix + ".gz") if source == "census_acs" else base' not in code:
        raise RuntimeError('collector_cache_selection_changed')
    candidates=[]
    for name in names:
        plain=ROOT/f'full/raw/full/census_acs/group-{name}.json'
        zipped=plain.with_suffix('.json.gz')
        if not plain.exists(): continue
        expanded=hashlib.sha256()
        with gzip.open(zipped,'rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):expanded.update(chunk)
        if expanded.hexdigest()!=sha(plain):raise RuntimeError('plain_gzip_mismatch')
        for p in (plain,zipped):
            actual=sha(p)
            if p.with_name(p.name+'.sha256').read_text().strip()!=actual:raise RuntimeError('sidecar_mismatch')
            binding=json.loads(p.with_name(p.name+'.binding.json').read_text())
            if binding.get('payload_sha256')!=actual:raise RuntimeError('binding_mismatch')
        relative=str(plain.relative_to(ROOT/'full'))
        for path in manifest_paths:
            if relative+'"' in path.read_text():raise RuntimeError('plain_payload_still_referenced')
        candidates.append({'path':str(plain.relative_to(ROOT)),'bytes':plain.stat().st_size,'sha256':sha(plain),
                           'retained_gzip':str(zipped.relative_to(ROOT)),'retained_gzip_sha256':sha(zipped)})
    # Retain the tiny old sidecars as a deletion audit; retained gzip sidecars untouched.
    prior_report=ROOT/'research/2026-09-28/storage/plain-duplicate-cleanup.json'
    if apply and not candidates and prior_report.exists():
        print(json.dumps({'status':'already_clean_no_changes','prior_report':str(prior_report)}))
        return
    for item in candidates:
        if apply:(ROOT/item['path']).unlink()
    report={'status':'deleted_verified_plain_duplicates' if apply else 'plan_only',
            'files':candidates,'logical_payload_bytes_removed':sum(i['bytes'] for i in candidates) if apply else 0,
            'retained':'canonical gzip payloads and all sidecars; no active runtime artifacts touched'}
    save(ROOT/'research/2026-09-28/storage'/('plain-duplicate-cleanup.json' if apply else 'plain-duplicate-cleanup-plan.json'),report)
    print(json.dumps(report,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('compact','files'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--renew-unbound-backup', action='store_true',
                        help='Under maintenance locks, archive an unbound prior checkpoint and create a fresh backup.')
    parser.add_argument('--resume-exact-checkpoint', type=Path,
                        help='Reuse a guard-captured exact prefix after locked full fingerprint verification; existing complete shadow and bound backup only.')
    args=parser.parse_args()
    if args.renew_unbound_backup and (args.command != 'compact' or not args.apply):
        parser.error('--renew-unbound-backup requires compact --apply')
    if args.resume_exact_checkpoint and (args.command != 'compact' or not args.apply or args.renew_unbound_backup):
        parser.error('--resume-exact-checkpoint requires compact --apply and cannot renew a backup')
    try:
        if args.command=='compact':compact(args.apply, args.renew_unbound_backup, args.resume_exact_checkpoint)
        else:cleanup_files(args.apply)
        return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        if OWNS_MAINTENANCE:progress('failed',reason=reason)
        print(json.dumps({'status':'failed','reason':reason}),flush=True)
        return 1


if __name__=='__main__':raise SystemExit(main())
