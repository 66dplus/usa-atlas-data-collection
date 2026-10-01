#!/usr/bin/env python3
"""Review/stage/deploy the NEW Atlas admission pipeline; no privilege escalation.

--plan reads files. --stage pins only new workspace configuration for preparation.
--apply requires actual Docker/systemd access, runs the explicit v3 migrator,
then installs units. --register-watchdog is a separate deployment opt-in.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'ops/auto-pipeline.json'
UNITS = ['usa-atlas-auto-pipeline.service', 'usa-atlas-auto-pipeline.timer']
UNIT_DIRECTORY = Path('/etc/systemd/system')
RUNTIME = ROOT / 'full/runtime/auto-pipeline'


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def read(file):
    return json.loads(file.read_text())


def write(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix(file.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(file)


def command(argv, check=True):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=30, check=False)
    if check and result.returncode:
        raise RuntimeError('command_failed:' + Path(argv[0]).name)
    return result


def run_migration(migrator, result_file, log):
    """Bound the explicit migration and reap only this installer's child group."""
    child = subprocess.Popen([sys.executable, str(migrator), '--apply', '--result', str(result_file)],
                             cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return child.wait(timeout=900)
    except BaseException:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=20)
        raise


def bind(config, require_all):
    result = copy.deepcopy(config)
    result['orchestrator_code_sha256'] = {name: sha(ROOT / name) for name in
                                        ['ops/auto_pipeline.py', 'ops/auto_pipeline_retention.py']}
    missing = []
    for item in [result['loader'], *result['adapters']]:
        pins = {}
        for name in item['reviewed_code_files']:
            file = (ROOT / name).resolve()
            if not file.is_relative_to(ROOT):
                raise RuntimeError('code_path_outside_repository')
            if not file.is_file():
                missing.append(name)
            else:
                pins[name] = sha(file)
        item['code_sha256'] = pins
    if require_all and missing:
        raise RuntimeError('reviewed_dependency_files_missing')
    return result, missing


def capabilities():
    systemd = command(['systemctl', 'show', '--property=Version'], check=False)
    docker = command(['docker', 'inspect', '--format={{.State.Running}}', 'usa-atlas-postgres'], check=False)
    return {'systemd_access': systemd.returncode == 0,
            'atlas_postgres_running': docker.returncode == 0 and docker.stdout.strip() == 'true',
            'host_unit_directory_writable_hint': os.access(UNIT_DIRECTORY, os.W_OK),
            'effective_uid': os.geteuid()}


def register_watchdog(config):
    file = ROOT / 'ops/scraper-watchdog.json'
    watchdog = read(file)
    pins = {name: sha(ROOT / name) for name in ['ops/auto_pipeline.py', 'ops/auto-pipeline.json']}
    for unit in UNITS:
        pins[str(UNIT_DIRECTORY / unit)] = sha(UNIT_DIRECTORY / unit)
    job = {'id': 'auto-pipeline', 'kind': 'scheduled', 'enabled': True,
           'service': UNITS[0], 'timer': UNITS[1],
           'unit_file': str(UNIT_DIRECTORY / UNITS[0]), 'timer_file': str(UNIT_DIRECTORY / UNITS[1]),
           'manifest': str((RUNTIME / 'state.json').relative_to(ROOT)),
           'processes': [{'script': 'ops/auto_pipeline.py', 'required': ['--once', '--apply']}],
           'success_statuses': ['complete', 'idle', 'partial', 'retry_wait', 'deferred_maintenance', 'prepared'],
           'run_deadline_seconds': 2800, 'freshness_seconds': 7200, 'code_sha256': pins}
    watchdog['jobs'] = [item for item in watchdog['jobs'] if item['id'] != job['id']] + [job]
    write(file, watchdog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--stage', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--register-watchdog', action='store_true',
                        help='Only with --apply and explicit approval to update the deployed watchdog registration.')
    args = parser.parse_args()
    if args.register_watchdog and not args.apply:
        parser.error('--register-watchdog requires --apply')
    config = read(CONFIG)
    staged, missing = bind(config, require_all=False)
    if args.plan:
        print(json.dumps({'status': 'plan_only', 'configuration_enabled': config['enabled'],
                          'missing_dependencies': missing, 'proposed_configuration': staged,
                          'migration': 'database/migrate_pipeline.py --apply --result <private installation receipt>',
                          'units': UNITS, 'schedule': 'Every15minutes UTC; persistent catchup and boot120s.',
                          'server_changes_performed': False}, indent=2))
        return 0
    if args.stage:
        # Staging must not indirectly replace code pins consumed by an already
        # installed privileged daemon. Future updates go through --apply.
        if config.get('enabled') or any((UNIT_DIRECTORY / unit).exists() for unit in UNITS):
            raise RuntimeError('stage_refused_for_deployed_or_enabled_configuration')
        required_adapter_files = [name for item in staged['adapters'] if item.get('enabled')
                                  for name in item['reviewed_code_files']]
        absent_adapters = sorted(set(missing) & set(required_adapter_files))
        if absent_adapters:
            raise RuntimeError('adapter_code_not_ready_for_staging')
        staged['enabled'] = False
        write(CONFIG, staged)
        print(json.dumps({'status': 'workspace_staged', 'database_changes': False, 'server_changes': False,
                          'missing_loader_dependencies': missing,
                          'next': 'python3 ops/auto_pipeline.py --once --prepare-only'}, indent=2))
        return 0
    cap = capabilities()
    if not cap['systemd_access'] or not cap['atlas_postgres_running'] or not cap['host_unit_directory_writable_hint']:
        print(json.dumps({'status': 'blocked_server_access', 'capabilities': cap,
                          'reason': 'Requires actual host systemd, Docker and unit-directory access. No escalation or bypass attempted.'}, indent=2))
        return 75
    active = command(['systemctl', 'show', UNITS[0], '--property=ActiveState', '--value'], check=False).stdout.strip()
    if active in ('active', 'activating', 'deactivating'):
        raise RuntimeError('pipeline_running_stop_explicitly_before_deployment')
    previous_timer_active = command(['systemctl', 'is-active', UNITS[1]], check=False).returncode == 0
    previous_timer_enabled = command(['systemctl', 'is-enabled', UNITS[1]], check=False).returncode == 0
    if shutil.disk_usage(ROOT).free < config['disk_floor_bytes']:
        raise RuntimeError('disk_headroom_below_installation_floor')
    migrator = ROOT / 'database/migrate_pipeline.py'
    if not migrator.is_file():
        raise RuntimeError('explicit_v3_migrator_not_ready')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    installation = RUNTIME / 'installations' / stamp
    installation.mkdir(parents=True)
    os.chmod(installation, 0o700)
    shutil.copyfile(CONFIG, installation / 'auto-pipeline.previous.json')
    if args.register_watchdog:
        shutil.copyfile(ROOT / 'ops/scraper-watchdog.json', installation / 'scraper-watchdog.previous.json')
    for unit in UNITS:
        existing = UNIT_DIRECTORY / unit
        if existing.exists():
            shutil.copyfile(existing, installation / (unit + '.previous'))
    command(['systemctl', 'stop', UNITS[1]], check=False)
    result_file = installation / 'migration-result.json'
    migration_confirmed = False
    try:
        with (installation / 'migration.log').open('wb') as log:
            migration_exit = run_migration(migrator, result_file, log)
        result = read(result_file) if result_file.exists() else {}
        migration_confirmed = migration_exit == 0 and result.get('status') in ('pass', 'already_pass')
        if not migration_confirmed:
            write(installation / 'result.json', {'status': 'migration_not_confirmed', 'exit_code': migration_exit,
                                               'migration_status': result.get('status'), 'units_enabled': False})
            print(json.dumps({'status': 'migration_not_confirmed', 'installation': str(installation.relative_to(ROOT))}))
            return migration_exit or 65
    except BaseException as exc:
        write(installation / 'result.json', {'status': 'migration_not_confirmed', 'error_class': type(exc).__name__,
                                           'units_enabled': False})
        raise
    finally:
        # Timeouts, malformed receipts and operator interruption must not leave
        # the previously installed timer stopped. A missing success receipt is
        # never evidence that a DB transaction was rolled back.
        if not migration_confirmed and previous_timer_active:
            command(['systemctl', 'start', UNITS[1]], check=False)
    # The migrator owns atomic DB/schema/catalog-pin deployment. Capture final
    # code and schema hashes only after its successful receipt.
    deployed = []
    try:
        staged, _ = bind(read(CONFIG), require_all=True)
        staged['enabled'] = True
        for unit in UNITS:
            target = UNIT_DIRECTORY / unit
            temporary = target.with_suffix(target.suffix + '.tmp')
            shutil.copyfile(ROOT / 'ops' / unit, temporary)
            os.chmod(temporary, 0o644)
            temporary.replace(target)
            deployed.append(unit)
        write(CONFIG, staged)
        command(['systemctl', 'daemon-reload'])
        if args.register_watchdog:
            register_watchdog(staged)
        command(['systemctl', 'enable', '--now', UNITS[1]])
        command(['systemctl', '--no-block', 'start', UNITS[0]])
    except BaseException:
        # No destructive DB rollback: the additive migration may already be in
        # use. Restore only config/unit deployment and leave its receipt intact.
        command(['systemctl', 'disable', '--now', UNITS[1]], check=False)
        command(['systemctl', 'stop', UNITS[0]], check=False)
        write(CONFIG, read(installation / 'auto-pipeline.previous.json'))
        if args.register_watchdog:
            write(ROOT / 'ops/scraper-watchdog.json', read(installation / 'scraper-watchdog.previous.json'))
        for unit in deployed:
            backup = installation / (unit + '.previous')
            if backup.exists():
                shutil.copyfile(backup, UNIT_DIRECTORY / unit)
            else:
                (UNIT_DIRECTORY / unit).unlink(missing_ok=True)
        command(['systemctl', 'daemon-reload'], check=False)
        if previous_timer_enabled:
            command(['systemctl', 'enable', UNITS[1]], check=False)
        if previous_timer_active:
            command(['systemctl', 'start', UNITS[1]], check=False)
        raise
    write(installation / 'result.json', {'status': 'installed', 'installed_at': datetime.now(timezone.utc).isoformat(),
                                       'units': UNITS, 'watchdog_registered': args.register_watchdog,
                                       'migration_result': str(result_file.relative_to(ROOT)),
                                       'configuration_sha256': sha(CONFIG)})
    print(json.dumps({'status': 'installed', 'installation': str(installation.relative_to(ROOT)),
                      'units': UNITS, 'watchdog_registered': args.register_watchdog}, indent=2))
    return 0


if __name__ == '__main__':
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except Exception as exc:
        # Host logs remain private. No command output, DSNs or secret environment
        # are copied into a public installation result.
        print(json.dumps({'status': 'installation_failed', 'error_class': type(exc).__name__}))
        sys.exit(1)
