#!/usr/bin/env python3
"""Read-only inventory of local artifacts; optional read-only PostgreSQL inventory.

Uses the standard library, never changes source files, and prints no row values,
source URLs, connection strings, environment values or database error messages.
JSON goes to stdout; redirect it to a new audit artifact if required.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('geo_id', 'geo_type', 'year', 'field_id', 'catalog_field_id', 'unit',
          'source', 'source_release', 'source_url', 'methodology_note', 'retrieved_at')
BINDINGS = ('plan_sha256', 'contract_sha256', 'config_sha256', 'collector_sha256')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    p = (root / relative).resolve()
    p.relative_to(root.resolve())
    return p


def inventory(root: Path, relative: str) -> dict:
    folder = root / relative
    total = allocated = count = 0
    largest = []
    suffixes = Counter()
    if folder.is_dir():
        for p in folder.rglob('*'):
            if not p.is_file() or p.is_symlink():
                continue
            stat = p.stat()
            total += stat.st_size
            allocated += getattr(stat, 'st_blocks', 0) * 512
            count += 1
            suffixes[p.suffix or '(none)'] += stat.st_size
            largest.append((stat.st_size, str(p.relative_to(root))))
    return {'path': relative, 'file_count': count, 'logical_file_bytes': total,
            'allocated_file_bytes': allocated, 'bytes_by_suffix': dict(suffixes),
            'largest_files': [{'path': p, 'bytes': n} for n, p in sorted(largest, reverse=True)[:8]]}


def normalized_audit(path: Path, root: Path, limit: int) -> dict:
    fields = {k: {'utf8_value_bytes': 0, 'values': set(), 'distinct_exact': True} for k in FIELDS}
    rows = original_bytes = compressed_bytes = 0
    compressor = zlib.compressobj(level=6, wbits=31)
    geographies = Counter()
    # Streaming compression measures a candidate gzip encoding only, never rewrites fixtures.
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        for line in stream:
            original_bytes += len(line)
            compressed_bytes += len(compressor.compress(line))
            row = json.loads(line)
            rows += 1
            geographies[row['geo_type']] += 1
            for key, stats in fields.items():
                value = row[key]
                if not isinstance(value, str):
                    raise ValueError('non_text_metadata')
                stats['utf8_value_bytes'] += len(value.encode('utf-8'))
                if len(stats['values']) < limit:
                    stats['values'].add(value)
                elif value not in stats['values']:
                    stats['distinct_exact'] = False
    compressed_bytes += len(compressor.flush())
    for stats in fields.values():
        values = stats.pop('values')
        stats['distinct_values_or_lower_bound'] = len(values)
        distinct_bytes = sum(len(v.encode('utf-8')) for v in values)
        stats['distinct_utf8_value_bytes'] = distinct_bytes if stats['distinct_exact'] else None
        stats['repeated_utf8_value_bytes'] = stats['utf8_value_bytes'] - distinct_bytes if stats['distinct_exact'] else None
    return {'path': str(path.relative_to(root)), 'sha256': digest(path),
            'stored_bytes': path.stat().st_size, 'decompressed_jsonl_bytes': original_bytes,
            'rows': rows, 'geo_type_counts': dict(geographies), 'field_stats': fields,
            'candidate_gzip_level6_bytes': compressed_bytes,
            'candidate_gzip_scope': 'entire decompressed file; in-memory compression; not PostgreSQL storage'}


def manifest_audit(root: Path) -> dict:
    path = root / 'full/state/run-manifest.json'
    if not path.exists():
        return {'status': 'missing'}
    manifest = json.loads(path.read_text())
    result = []
    for source, state in sorted(manifest.get('sources', {}).items()):
        item = {'source': source, 'status': state.get('status'),
                'declared_normalized_rows': state.get('normalized_rows')}
        artifact = state.get('normalized_artifact')
        if artifact:
            target = safe_path(root / 'full', artifact['path'])
            present = target.is_file()
            item.update(artifact_path=artifact['path'], manifest_bytes=artifact.get('bytes'),
                        manifest_rows=artifact.get('rows'), file_present=present,
                        sha256_matches_manifest=digest(target) == artifact.get('sha256') if present else None)
        raw = state.get('artifacts', [])
        item['declared_raw_artifact_count'] = len(raw)
        item['present_raw_artifact_count'] = sum(safe_path(root / 'full', r['path']).is_file() for r in raw)
        result.append(item)
    return {'status': manifest.get('status'), 'manifest_sha256': digest(path),
            'manifest_updated_at': manifest.get('updated_at'), 'sources': result,
            'note': 'Manifest declarations are historical metadata, not evidence of a running database.'}


def raw_cache_audit(root: Path) -> dict:
    folder = root / 'full/raw'
    hashes = bindings = hash_bytes = binding_bytes = verified = 0
    errors = Counter()
    pairs = []
    if folder.is_dir():
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or p.is_symlink():
                continue
            if p.name.endswith('.sha256'):
                hashes += 1
                hash_bytes += p.stat().st_size
            elif p.name.endswith('.binding.json'):
                bindings += 1
                binding_bytes += p.stat().st_size
            else:
                sha_path = p.with_name(p.name + '.sha256')
                binding_path = p.with_name(p.name + '.binding.json')
                if not sha_path.exists() or not binding_path.exists():
                    errors['missing_sidecar'] += 1
                    continue
                sha = digest(p)
                expected = sha_path.read_text().strip()
                binding = json.loads(binding_path.read_text())
                if sha != expected or sha != binding.get('payload_sha256'):
                    errors['payload_hash_mismatch'] += 1
                elif any(not binding.get(k) for k in BINDINGS):
                    errors['binding_key_missing'] += 1
                else:
                    verified += 1
                # Byte-identical content is not enough to authorize removal: cache names/bindings matter.
                if p.suffix == '.gz' and p.with_suffix('').is_file():
                    plain = p.with_suffix('')
                    expanded_digest = hashlib.sha256()
                    expanded_bytes = 0
                    with gzip.open(p, 'rb') as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                            expanded_digest.update(chunk)
                            expanded_bytes += len(chunk)
                    pairs.append({'plain_path': str(plain.relative_to(root)),
                                  'plain_bytes': plain.stat().st_size, 'gzip_bytes': p.stat().st_size,
                                  'expanded_gzip_bytes': expanded_bytes,
                                  'uncompressed_bytes_equal': expanded_digest.hexdigest() == digest(plain)})
    return {'sha256_sidecar_count': hashes, 'sha256_sidecar_bytes': hash_bytes,
            'binding_sidecar_count': bindings, 'binding_sidecar_bytes': binding_bytes,
            'payload_hash_and_binding_payload_verified': verified, 'errors': dict(errors),
            'binding_limit': 'Only payload hashes and binding key presence checked; compatibility with current code/config is not admitted.',
            'plain_gzip_pairs': pairs}


def postgres_audit(enabled: bool, container: bool = False) -> dict:
    available = shutil.which('docker' if container else 'psql') is not None
    if not enabled or not available:
        return {'status': 'not_measured', 'reason': 'client_missing' if container and not available else 'psql_missing' if not available else 'not_requested',
                'psql_available': available, 'connection_values_disclosed': False}
    env = dict(os.environ, PGCONNECT_TIMEOUT='5', PGAPPNAME='usa_atlas_storage_audit',
               PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=2000')
    args = (['docker', 'exec', '-i', '-u', 'postgres', '-e', 'PGAPPNAME=usa_atlas_storage_audit',
             'usa-atlas-postgres', 'sh', '-c',
             'exec psql -X -w -qAt --username "$POSTGRES_USER" --dbname usa_atlas --set ON_ERROR_STOP=1']
            if container else ['psql', '-X', '-w', '-qAt', '--dbname', 'usa_atlas', '--set', 'ON_ERROR_STOP=1'])
    try:
        result = subprocess.run(args, input=Path(__file__).with_suffix('.sql').read_text(),
                                capture_output=True, text=True, env=env, timeout=70)
        if result.returncode:
            return {'status': 'not_measured', 'reason': 'connection_or_query_failed',
                    'details': 'Database stderr intentionally omitted; inspect connection/permissions locally.'}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {'status': 'not_measured', 'reason': 'timeout'}
    except (OSError, json.JSONDecodeError):
        return {'status': 'not_measured', 'reason': 'client_or_output_error'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--postgres', action='store_true', help='Attempt a read-only PostgreSQL measurement via libpq environment.')
    parser.add_argument('--postgres-container', action='store_true', help='Read-only audit of the existing usa-atlas-postgres Docker container; no new database.')
    parser.add_argument('--distinct-limit', type=int, default=200000,
                        help='Maximum retained unique values per field; higher cardinality is explicitly marked inexact.')
    args = parser.parse_args()
    if args.distinct_limit < 1:
        parser.error('--distinct-limit must be positive')
    root = args.root.resolve()
    try:
        paths = sorted((root / 'full/normalized').glob('*.jsonl')) + sorted((root / 'full/normalized').glob('*.jsonl.gz'))
        report = {'audit_version': 1, 'measured_at': datetime.now(timezone.utc).isoformat(),
                  'scope': 'Local checkout file sizes; PostgreSQL sizes only if postgres.status=measured_read_only.',
                  'file_sizes_note': 'Overlapping directory inventories must not be summed; allocated bytes omit directory metadata.',
                  'directories': [inventory(root, p) for p in ('.git', 'full', 'full/raw', 'full/normalized', 'full/state', 'database', 'pilot')],
                  'manifest': manifest_audit(root),
                  'normalized_files': [normalized_audit(p, root, args.distinct_limit) for p in paths],
                  'raw_cache': raw_cache_audit(root), 'postgres': postgres_audit(args.postgres or args.postgres_container, args.postgres_container)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'fail', 'reason': type(exc).__name__, 'details': 'No input data or secrets printed.'}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
