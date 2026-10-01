#!/usr/bin/env python3
"""Fetch public, non-food source tables without modifying production admission."""
import argparse
import csv
import fcntl
import gzip
import hashlib
import io
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'full/runtime/public-20260928'
JOBS = [
    {'id': 'susb-receipts-2022', 'url': 'https://www2.census.gov/programs-surveys/susb/tables/2022/us_6digitnaics_rcptsize_2022.xlsx', 'format': 'xlsx', 'geo': 'nation', 'period': '2022'},
    {'id': 'susb-large-receipts-2022', 'url': 'https://www2.census.gov/programs-surveys/susb/tables/2022/us_naicssector_large_rcptsize_2022.xlsx', 'format': 'xlsx', 'geo': 'nation', 'period': '2022'},
    {'id': 'irs-state-agi-2023', 'url': 'https://www.irs.gov/pub/irs-soi/23in55cmcsv.csv', 'format': 'csv', 'geo': 'state', 'period': '2023'},
    {'id': 'irs-county-agi-2023', 'url': 'https://www.irs.gov/pub/irs-soi/23incyallagi.csv', 'format': 'csv', 'geo': 'county', 'period': '2023'},
    {'id': 'bea-metro-rpp', 'url': 'https://apps.bea.gov/regional/zip/MARPP.zip', 'format': 'zip', 'geo': 'metro', 'period': 'provider_multi_year'},
    {'id': 'epa-monitors-2025', 'url': 'https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_2025.zip', 'format': 'zip', 'geo': 'monitor', 'period': '2025'},
]
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def artifact(path, out):
    return {'path': str(path.relative_to(out)), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def download(job, out):
    target = out / 'raw' / (job['id'] + '.' + job['format'])
    meta_path = target.with_suffix(target.suffix + '.json')
    if target.exists():
        meta = json.loads(meta_path.read_text())
        if meta['sha256'] != sha(target) or meta['url'] != job['url']:
            raise ValueError('cached_payload_mismatch')
        return target, meta
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + '.part')
    for attempt in range(3):
        try:
            req = urllib.request.Request(job['url'], headers={'User-Agent': 'USA-Atlas-public-collector/1.0'})
            with urllib.request.urlopen(req, timeout=90) as response, temp.open('wb') as stream:
                if 'html' in response.headers.get('Content-Type', '').lower():
                    raise ValueError('unexpected_html')
                size = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    size += len(chunk)
                    if size > 1024 ** 3 or shutil.disk_usage(out).free < 1024 ** 3:
                        raise ValueError('disk_or_payload_limit')
                    stream.write(chunk)
                expected = response.headers.get('Content-Length')
                if expected and size != int(expected):
                    raise ValueError('incomplete_response')
                headers = {k: response.headers.get(k) for k in ['ETag', 'Last-Modified', 'Content-Type']}
            temp.replace(target)
            meta = {**artifact(target, out), 'url': job['url'], 'retrieved_at': now(), 'http_headers': headers}
            save(meta_path, meta)
            return target, meta
        except (OSError, urllib.error.URLError, ValueError) as exc:
            temp.unlink(missing_ok=True)
            if isinstance(exc, ValueError) or isinstance(exc, urllib.error.HTTPError) and exc.code not in [408, 429, 500, 502, 503, 504]:
                raise
            if attempt == 2:
                raise
            delay = 5 * 2 ** attempt
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                try:
                    delay = max(delay, float(exc.headers.get('Retry-After', '60')))
                except ValueError:
                    delay = 60
            time.sleep(min(delay, 600))


def xlsx_rows(path):
    """Read values from simple Census workbooks, retaining rows and empty cells."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            tree = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(n.itertext()) for n in tree.findall('s:si', NS)]
        sheets = sorted(n for n in archive.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))
        for sheet in sheets:
            with archive.open(sheet) as stream:
                for _, row in ET.iterparse(stream, events=('end',)):
                    if row.tag != '{' + NS['s'] + '}row':
                        continue
                    values = []
                    for cell in row.findall('s:c', NS):
                        col = ''.join(c for c in cell.attrib['r'] if c.isalpha())
                        index = 0
                        for char in col:
                            index = index * 26 + ord(char) - ord('A') + 1
                        while len(values) < index:
                            values.append('')
                        v = cell.find('s:v', NS)
                        raw = '' if v is None else (v.text or '')
                        typ = cell.attrib.get('t')
                        if typ == 's':
                            raw = strings[int(raw)]
                        elif typ == 'inlineStr':
                            inline = cell.find('s:is', NS)
                            raw = ''.join(inline.itertext()) if inline is not None else ''
                        values[index - 1] = raw
                    yield sheet, row.attrib['r'], values
                    row.clear()


def normalize(job, raw, out):
    target = out / 'tables' / (job['id'] + '.csv.gz')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + '.part')
    count = 0
    try:
        with temp.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as gz, io.TextIOWrapper(gz, encoding='utf-8', newline='') as text:
            writer = csv.writer(text)
            if job['format'] == 'xlsx':
                writer.writerow(['source_sheet', 'source_row', 'cells_json'])
                for sheet, row, values in xlsx_rows(raw):
                    writer.writerow([sheet, row, json.dumps(values, ensure_ascii=False)])
                    count += 1
            elif job['format'] == 'csv':
                with raw.open(encoding='utf-8-sig', newline='') as source:
                    reader = csv.reader(source)
                    header = next(reader)
                    if len(header) != len(set(header)):
                        raise ValueError('duplicate_csv_header')
                    if not {'STATE', 'AGI_STUB'} <= {h.upper() for h in header}:
                        raise ValueError('unexpected_irs_schema')
                    writer.writerow(header)
                    for row in reader:
                        if not row:
                            continue
                        if len(row) != len(header):
                            raise ValueError('malformed_csv_width')
                        writer.writerow(row)
                        count += 1
            else:
                writer.writerow(['source_member', 'source_row', 'cells_json'])
                with zipfile.ZipFile(raw) as archive:
                    members = [n for n in archive.namelist() if n.lower().endswith('.csv')]
                    if not members:
                        raise ValueError('no_csv_in_archive')
                    for member in members:
                        with archive.open(member) as binary, io.TextIOWrapper(binary, encoding='utf-8-sig', newline='') as source:
                            reader = csv.reader(source)
                            for idx, row in enumerate(reader, 1):
                                if job['id'] == 'epa-monitors-2025':
                                    if idx == 1:
                                        parameter = row.index('Parameter Code')
                                    elif len(row) <= parameter:
                                        raise ValueError('malformed_epa_row')
                                    elif row[parameter] not in ['88101', '44201']:
                                        continue
                                writer.writerow([member, idx, json.dumps(row, ensure_ascii=False)])
                                count += 1
        if not count:
            raise ValueError('empty_source_table')
        temp.replace(target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return {**artifact(target, out), 'table_rows_including_preserved_headers_when_nested': count,
            'representation': 'lossless_source_table_cells_not_production_observations',
            'suppression_policy': 'retain every original token; no suppressed or missing token converted to zero'}


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / 'manifest.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'jobs': {}}
    bindings = {'collector_sha256': sha(Path(__file__)), 'plan_sha256': hashlib.sha256(json.dumps(JOBS, sort_keys=True).encode()).hexdigest()}
    if state.get('bindings', bindings) != bindings:
        raise ValueError('changed_run_bindings_use_new_output_directory')
    state.update(bindings=bindings, status='running', updated_at=now(), production_admission=False)
    save(state_path, state)
    for job in JOBS:
        old = state['jobs'].get(job['id'], {})
        if old.get('status') == 'source_tables_collected':
            for item in [old['raw'], old['table']]:
                if sha(out / item['path']) != item['sha256']:
                    raise ValueError('completed_artifact_hash_mismatch')
            continue
        state['active_job'] = job['id']
        state['updated_at'] = now()
        save(state_path, state)
        print(json.dumps({'job': job['id'], 'status': 'started'}), flush=True)
        try:
            raw, meta = download(job, out)
            table = normalize(job, raw, out)
            state['jobs'][job['id']] = {**job, 'status': 'source_tables_collected', 'raw': meta, 'table': table}
        except (OSError, ValueError, urllib.error.URLError, zipfile.BadZipFile, ET.ParseError) as exc:
            state['jobs'][job['id']] = {**job, 'status': 'blocked_or_failed', 'error_class': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}
        state['updated_at'] = now()
        save(state_path, state)
        print(json.dumps({'job': job['id'], 'status': state['jobs'][job['id']]['status']}), flush=True)
        time.sleep(1)
    state['status'] = 'complete_source_tables' if all(x['status'] == 'source_tables_collected' for x in state['jobs'].values()) else 'partial'
    state.pop('active_job', None)
    save(state_path, state)
    return 0 if state['status'] == 'complete_source_tables' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / 'collector.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        return run(args.out)


if __name__ == '__main__':
    sys.exit(main())
