"""Bound admission cache growth without deleting source artifacts or DB receipts."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time


def sha(file):
    value = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 ** 2), b''):
            value.update(chunk)
    return value.hexdigest()


def read(file):
    return json.loads(file.read_text())


def save(file, value):
    temp = file.with_suffix(file.suffix + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(file)


def cleanup(config, runtime, state, current_keys, deadline):
    policy = config['retention']
    clock = time.time()
    now = datetime.now(timezone.utc)
    removed, released, errors, archived = 0, 0, [], 0
    root = runtime / 'batches'
    for receipt_file in root.glob('*/*/ingest-result.json') if root.exists() else ():
        if removed >= policy['max_batches_per_cycle'] or time.monotonic() + 10 >= deadline:
            break
        folder = receipt_file.parent.resolve()
        key, batch = folder.parent.name, folder.name
        job = state['jobs'].get(key, {})
        if job.get('current_batch') == batch and job.get('status') != 'complete':
            continue
        if clock - receipt_file.stat().st_mtime < policy['accepted_payload_days'] * 86400:
            continue
        marker = folder / 'retention.json'
        try:
            if marker.exists():
                if read(marker).get('status') != 'accepted_payloads_pruned':
                    raise ValueError('previous_retention_cleanup_interrupted')
                continue
            receipt = read(receipt_file)
            manifest_file = folder / 'admission-manifest.json'
            if receipt.get('status') not in ('pass', 'already_pass') or not manifest_file.exists():
                continue
            if sha(manifest_file) != receipt.get('manifest_sha256'):
                raise ValueError('receipt_manifest_binding_mismatch')
            manifest = read(manifest_file)
            payloads = []
            for kind in ('observations', 'quality', 'records'):
                item = manifest.get(kind)
                if not item:
                    continue
                file = (folder / item['path']).resolve()
                if not file.is_relative_to(folder) or file.name in ('candidate.json', 'prepare-result.json', 'admission-manifest.json', 'ingest-result.json'):
                    raise ValueError('payload_outside_batch_or_metadata_target')
                if not file.is_file() or file.stat().st_size != item['bytes'] or sha(file) != item['sha256']:
                    raise ValueError('accepted_payload_hash_mismatch')
                payloads.append((file, item))
            proof = {'status': 'pruning_accepted_payloads', 'at': now.isoformat(),
                     'receipt_sha256': sha(receipt_file), 'manifest_sha256': receipt['manifest_sha256'],
                     'payloads': [{'path': str(file.relative_to(folder)), 'sha256': item['sha256'], 'bytes': item['bytes']}
                                  for file, item in payloads]}
            # Persist the reason before unlink. Inputs are never considered for
            # deletion: only the three known generated payload fields above.
            save(marker, proof)
            for file, item in payloads:
                file.unlink()
                released += item['bytes']
            proof['status'] = 'accepted_payloads_pruned'
            save(marker, proof)
            removed += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'batch': str(folder.relative_to(runtime)), 'error_class': type(exc).__name__})
    archive = runtime / 'ledger-archive'
    for key, job in list(state['jobs'].items()):
        if key in current_keys or job.get('status') != 'complete':
            continue
        try:
            updated = datetime.fromisoformat(job['updated_at']).timestamp()
        except (KeyError, ValueError, TypeError):
            continue
        if clock - updated < policy['completed_ledger_days'] * 86400:
            continue
        archive.mkdir(exist_ok=True)
        with (archive / (now.strftime('%Y-%m') + '.jsonl.gz')).open('ab') as stream:
            stream.write(gzip.compress((json.dumps({'key': key, 'job': job}, sort_keys=True) + '\n').encode(), mtime=0))
            stream.flush()
            os.fsync(stream.fileno())
        del state['jobs'][key]
        archived += 1
    current_month = now.year * 12 + now.month
    for file in archive.glob('*.jsonl.gz') if archive.exists() else ():
        match = re.fullmatch(r'(\d{4})-(\d{2})\.jsonl\.gz', file.name)
        if match and current_month - (int(match[1]) * 12 + int(match[2])) > policy['archive_months']:
            file.unlink()
    return {'checked_at': now.isoformat(), 'accepted_batches_pruned': removed, 'bytes_released': released,
            'completed_ledger_entries_archived': archived, 'errors': errors,
            'source_artifacts_deleted': False, 'receipts_and_manifests_preserved': True}
