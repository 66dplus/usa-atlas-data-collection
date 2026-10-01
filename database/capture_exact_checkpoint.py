#!/usr/bin/env python3
"""Capture the authorized old runner's locked prefix and cancel only its duplicate tail.

This one-shot helper never loads, updates, drops or copies data. It waits for the
known old process's final range, saves bound evidence, then requests cancellation
of that one PostgreSQL statement. It does not launch the replacement process.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import cleanup_storage as maintenance

STATE = maintenance.STATE
OUTPUT = STATE / 'exact-resume-checkpoint.json'
APP = 'usa_atlas_storage_checkpoint_guard'
LOCKED_RELATIONS = ('observation','catalog_field','ingest_run','observation_stage',
                   'catalog_field_stage','schema_metadata','observation_data',
                   'source_resource','methodology')
LOCKS_CTE = """WITH owners AS (
 SELECT a.pid,a.backend_start,a.xact_start,a.state,
   count(DISTINCT c.relname) locked_relations
 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid
 JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE a.application_name='usa_atlas_storage_cleanup' AND a.datname=current_database()
   AND n.nspname='usa_atlas' AND c.relname IN
   ('observation','catalog_field','ingest_run','observation_stage','catalog_field_stage',
    'schema_metadata','observation_data','source_resource','methodology')
   AND l.granted AND l.mode IN ('ShareLock','ShareRowExclusiveLock','ExclusiveLock','AccessExclusiveLock')
   AND EXISTS(SELECT 1 FROM pg_locks ad WHERE ad.pid=a.pid AND ad.locktype='advisory'
              AND ad.classid=0 AND ad.objid=66280928 AND ad.granted)
 GROUP BY a.pid,a.backend_start,a.xact_start,a.state
) """


def db(query):
    args = maintenance.command()
    args[args.index('PGAPPNAME=usa_atlas_storage_cleanup')] = 'PGAPPNAME=' + APP
    result = subprocess.run(args, input="SET statement_timeout='15s'; SET lock_timeout='3s';\n" + query,
                            text=True, capture_output=True, timeout=25)
    if result.returncode:
        path = STATE/'checkpoint-guard-error.private.log'
        path.write_text(result.stderr)
        os.chmod(path,0o600)
        raise RuntimeError('guard_database_read_or_cancel_failed_details_private')
    return result.stdout.strip()


def host_identity(pid):
    base = Path('/proc')/str(pid)
    args = (base/'cmdline').read_bytes().split(b'\0')
    if not any(x.endswith(b'/cleanup_storage.py') or x==b'cleanup_storage.py' for x in args):
        raise RuntimeError('old_pid_not_cleanup_runner')
    if b'compact' not in args or b'--apply' not in args or b'--resume-exact-checkpoint' in args:
        raise RuntimeError('old_pid_not_expected_original_compaction')
    start_ticks = (base/'stat').read_text().rpartition(') ')[2].split()[19]
    held_paths = set()
    for fd in (base/'fd').iterdir():
        try: held_paths.add(os.readlink(fd))
        except FileNotFoundError: pass
    required = {str(STATE/'process.lock'),str(maintenance.ROOT/'full/state/.usa-atlas-load.lock'),
                str(maintenance.PRODUCTION/'full/state/.usa-atlas-load.lock')}
    if not required <= held_paths: raise RuntimeError('old_process_lock_handles_missing')
    return {'pid':pid,'start_ticks':start_ticks}


def note(phase, **fields):
    report = {'phase':phase,'updated_at':datetime.now(timezone.utc).isoformat(),**fields}
    maintenance.save(STATE/'exact-checkpoint-guard-progress.json',report)
    print(json.dumps(report),flush=True)


def state():
    return json.loads((STATE/'progress.json').read_text())


def is_tail(progress,pid):
    return (progress.get('pid')==pid and progress.get('phase')=='exact_range_validation_running'
            and progress.get('range_index')==101 and progress.get('lower')==':'
            and progress.get('upper') is None and progress.get('ranges')==102)


def evidence():
    return json.loads(db(LOCKS_CTE + """SELECT json_build_object(
      'owners',(SELECT coalesce(json_agg(o),'[]'::json) FROM owners o WHERE locked_relations=9),
      'active',(SELECT coalesce(json_agg(t),'[]'::json) FROM (
        SELECT pid,backend_start,query_start,query,md5(query) query_md5
        FROM pg_stat_activity WHERE datname=current_database()
          AND application_name='usa_atlas_storage_cleanup' AND state='active'
      ) t),
      'catalog',(""" + maintenance.RESUME_CATALOG_SQL.removeprefix('SELECT ').rstrip(';') + """),
      'schema_sha256',(SELECT schema_sha256 FROM usa_atlas.schema_metadata)
    );"""))


def capture_and_cancel(pid,identity):
    source_path=STATE/'source-fingerprint.json'
    compact_path=STATE/'compact-fingerprint.json'
    exact=json.loads((STATE/'exact-validation.json').read_text())
    backup=json.loads((STATE/'backup.json').read_text())
    source=json.loads(source_path.read_text())
    compact=json.loads(compact_path.read_text())
    source_sha=maintenance.sha(source_path)
    compact_sha=maintenance.sha(compact_path)
    if source != compact or backup.get('source_fingerprint_sha256') != source_sha:
        raise RuntimeError('guard_backup_fingerprint_binding_mismatch')
    dump=STATE/'usa-atlas-before-compact.dump'
    if maintenance.sha(dump) != backup.get('sha256'):
        raise RuntimeError('guard_backup_hash_mismatch')
    data=evidence()
    if len(data['owners']) != 1: raise RuntimeError('guard_expected_one_locked_maintenance_session')
    owners=data['owners'][0]
    pattern="(SELECT * FROM usa_atlas.observation WHERE geo_id >= ':') o LEFT JOIN (SELECT * FROM usa_atlas.observation_data WHERE geo_id >= ':') n USING(geo_id,period,field_id,source_release)"
    matches=[a for a in data['active'] if pattern in ' '.join(a['query'].split())]
    if not matches: return False  # progress was written before the backend opened
    if len(matches)!=1: raise RuntimeError('guard_ambiguous_duplicate_tail_backend')
    active=matches[0]
    maintenance.validate_complete_shadow(data['catalog'])
    if host_identity(pid)!=identity or not is_tail(state(),pid):
        raise RuntimeError('guard_old_process_or_phase_changed')
    packet={'format':'usa_atlas_locked_exact_checkpoint_v1','captured_at':datetime.now(timezone.utc).isoformat(),
            'container':maintenance.CONTAINER,'database':'usa_atlas','host_process':identity,
            'lock_owner':owners,'cancel_target':{k:v for k,v in active.items() if k!='query'},
            'source_fingerprint':source,'compact_fingerprint':compact,
            'source_fingerprint_sha256':source_sha,'compact_fingerprint_sha256':compact_sha,
            'backup_sha256':backup['sha256'],'backup_bytes':dump.stat().st_size,
            'exact_validation':exact,'catalog':data['catalog'],'schema_sha256':data['schema_sha256'],
            'reason':'Stop duplicate full-table tail caused by en_US.utf8 punctuation ordering; preserve all completed numeric ranges.'}
    if OUTPUT.exists(): raise RuntimeError('guard_checkpoint_already_exists_review_before_retry')
    maintenance.save(OUTPUT,packet)
    maintenance.validate_resume_packet(OUTPUT)
    note('checkpoint_captured_under_locks',path=str(OUTPUT),sha256=maintenance.sha(OUTPUT),
         old_pid=pid,backend_pid=active['pid'],completed_ranges=len(exact['ranges']))
    # Recheck the live query identity and complete source/shadow lock owner in
    # the same command that signals. No other application or backend is eligible.
    target=int(active['pid']); owner=int(owners['pid'])
    digest=active['query_md5']
    if len(digest)!=32 or any(c not in '0123456789abcdef' for c in digest):
        raise RuntimeError('guard_invalid_query_digest')
    answer=db(LOCKS_CTE + f"""SELECT pg_cancel_backend(a.pid)
      FROM pg_stat_activity a WHERE a.pid={target} AND a.datname=current_database()
        AND a.application_name='usa_atlas_storage_cleanup' AND a.state='active'
        AND md5(a.query)='{digest}'
        AND EXISTS(SELECT 1 FROM owners WHERE pid={owner} AND locked_relations=9);""")
    if answer != 't': raise RuntimeError('guard_tail_not_cancelled_state_changed')
    note('duplicate_tail_cancel_requested',old_pid=pid,backend_pid=target,checkpoint=str(OUTPUT))
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-pid',type=int,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--wait-seconds',type=int,default=9000)
    args=parser.parse_args()
    if not args.apply:
        print(json.dumps({'status':'plan_only','old_pid':args.old_pid,'checkpoint':str(OUTPUT)}));return 0
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'exact-checkpoint-guard.lock').open('a+') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        identity=host_identity(args.old_pid)
        deadline=time.monotonic()+args.wait_seconds
        note('waiting_for_duplicate_tail',old_pid=args.old_pid)
        while time.monotonic()<deadline:
            if host_identity(args.old_pid)!=identity: raise RuntimeError('old_process_identity_changed')
            current=state()
            if current.get('pid')!=args.old_pid: raise RuntimeError('maintenance_owner_changed')
            if current.get('phase') in ('failed','complete','cutover_running'):
                raise RuntimeError('old_process_finished_before_guard_capture')
            if is_tail(current,args.old_pid) and capture_and_cancel(args.old_pid,identity): return 0
            time.sleep(2)
        raise RuntimeError('guard_wait_timeout_no_action')


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        reason=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        note('failed',reason=reason)
        raise SystemExit(1)
