#!/usr/bin/env python3
"""Preserve official 2024 variable labels for collected nonfood Census tables."""
import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ElementTree
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'full'))
import collect_deep as deep


def main():
    out = ROOT / 'full/runtime/deep-20260928/metadata'
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'manifest.json'
    manifest = json.loads(path.read_text()) if path.exists() else {'release': '2024-acs-acs5', 'groups': {}}
    groups = sorted(set(deep.variables_by_table()) | {'B17021', 'B05012'})
    for group in groups:
        target = out / (group + '.json')
        prior = manifest['groups'].get(group)
        if prior and target.exists():
            if deep.digest(target) != prior['sha256']:
                raise ValueError('metadata_hash_mismatch')
            continue
        url = f'https://api.census.gov/data/2024/acs/acs5/groups/{group}.json'
        request = urllib.request.Request(url, headers={'User-Agent': 'USA-Atlas-deep-research/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(8 * 1024 ** 2)
        value = json.loads(raw)
        if 'variables' not in value or group + '_001E' not in value['variables']:
            raise ValueError('metadata_group_mismatch')
        target.write_bytes(raw)
        manifest['groups'][group] = {'path': target.name, 'url': url, 'bytes': len(raw),
                                     'sha256': hashlib.sha256(raw).hexdigest(),
                                     'retrieved_at': datetime.now(timezone.utc).isoformat()}
        deep.save(path, manifest)
        print(group, len(raw), flush=True)
        time.sleep(1)
    dictionary = {}
    for group in groups:
        value = json.loads((out / (group + '.json')).read_text())
        dictionary.update({name: {k: details[k] for k in ['label', 'concept', 'predicateType', 'attributes'] if k in details}
                           for name, details in value['variables'].items() if name.startswith(group + '_')})
    deep.save(out / 'variable-dictionary.json', dictionary)
    manifest['variable_dictionary'] = {'path': 'variable-dictionary.json', 'sha256': deep.digest(out / 'variable-dictionary.json'),
                                      'variables': len(dictionary)}
    table_path = out / '2024_DataProductList.xlsx'
    table_url = 'https://www2.census.gov/programs-surveys/acs/tech_docs/table_shells/table_lists/2024_DataProductList.xlsx'
    if not table_path.exists():
        with urllib.request.urlopen(table_url, timeout=30) as response:
            table_path.write_bytes(response.read(8 * 1024 ** 2))
    if manifest.get('table_list') and deep.digest(table_path) != manifest['table_list']['sha256']:
        raise ValueError('table_list_hash_mismatch')
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    table_details = {}
    with zipfile.ZipFile(table_path) as archive:
        strings = [''.join(cell.itertext()) for cell in ElementTree.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', ns)]
        sheet = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        for row in sheet.findall('.//m:sheetData/m:row', ns):
            cells = {}
            for cell in row.findall('m:c', ns):
                value = cell.find('m:v', ns)
                text = value.text if value is not None else ''
                if cell.get('t') == 's' and text:
                    text = strings[int(text)]
                cells[re.sub(r'\d', '', cell.get('r'))] = text
            if cells.get('A') in groups:
                table_details[cells['A']] = {'title': cells.get('B'), 'universe': cells.get('C'),
                    'product_type': cells.get('D'), 'releases': cells.get('E'),
                    'one_year_geography_restrictions': cells.get('F', ''),
                    'five_year_geography_restrictions': cells.get('G', ''), 'source_url': table_url}
    if set(table_details) != set(groups) or any(not item['universe'] for item in table_details.values()):
        raise ValueError('table_list_incomplete')
    deep.save(out / 'table-universes-and-restrictions.json', table_details)
    manifest['table_list'] = {'path': table_path.name, 'url': table_url, 'sha256': deep.digest(table_path),
                              'bytes': table_path.stat().st_size}
    manifest['table_universes_and_restrictions'] = {'path': 'table-universes-and-restrictions.json',
        'sha256': deep.digest(out / 'table-universes-and-restrictions.json'), 'tables': len(table_details)}
    deep.save(path, manifest)
    print(json.dumps({'groups': len(groups), 'variables': len(dictionary)}), flush=True)


if __name__ == '__main__':
    main()
