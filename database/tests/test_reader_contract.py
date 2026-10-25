import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import os
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / 'database/reader/export_reader.py'
spec = importlib.util.spec_from_file_location('reader_exporter', EXPORTER)
exporter = importlib.util.module_from_spec(spec); spec.loader.exec_module(exporter)

class ReaderContractTests(unittest.TestCase):
    def test_export_is_deterministic_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'reader'
            output.mkdir()
            (output / 'fixtures').mkdir()
            for name in ('reader-fixture.sql', 'reader-query.sql'):
                shutil.copyfile(exporter.OUT/'fixtures'/name, output/'fixtures'/name)
            original = exporter.OUT
            exporter.OUT = output
            try:
                exporter.export()
                contract = (output/'contract.json').read_bytes()
                decoded = json.loads(contract)
                for name, digest in decoded['artifact_sha256'].items():
                    self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(), digest)
                exporter.export()
                self.assertEqual(contract, (output/'contract.json').read_bytes())
            finally:
                exporter.OUT = original

    def test_required_schema_column_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); shutil.copytree(ROOT/'database',root/'database'); shutil.copytree(ROOT/'full',root/'full')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.ROOT=root
            schema=root/'database/schema.sql'; content=schema.read_text(); marker='CREATE TABLE IF NOT EXISTS usa_atlas.observation_data'
            before, after=content.split(marker,1)
            schema.write_text(before+marker+after.replace('value double precision NOT NULL','value numeric NOT NULL',1))
            with self.assertRaisesRegex(ValueError,'required_column_changed:observation.value'):
                module.validate()

    def test_all_reader_observation_columns_and_types_are_validated(self):
        mutations = (
            ('geo_type text NOT NULL', 'geography_type text NOT NULL', 'observation.geo_type'),
            ('retrieved_at timestamptz NOT NULL', 'retrieved_at timestamp NOT NULL',
             'observation.retrieved_at'),
            ('m.methodology_note, o.retrieved_at', 'm.methodology_note AS retrieval_note, o.retrieved_at',
             'observation.methodology_note'),
        )
        for before, after, expected in mutations:
            with self.subTest(mutation=after), tempfile.TemporaryDirectory() as td:
                root=Path(td); shutil.copytree(ROOT/'database',root/'database'); shutil.copytree(ROOT/'full',root/'full')
                module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.ROOT=root
                schema=root/'database/schema.sql'; content=schema.read_text()
                if expected.startswith('observation.') and before.startswith(('geo_type', 'retrieved_at')):
                    table_marker='CREATE TABLE IF NOT EXISTS usa_atlas.observation_data'
                    prefix, suffix=content.split(table_marker, 1)
                    table, remainder=suffix.split(');', 1)
                    self.assertIn(before, table)
                    content=prefix+table_marker+table.replace(before, after, 1)+');'+remainder
                else:
                    self.assertIn(before, content)
                    content=content.replace(before, after, 1)
                schema.write_text(content)
                with self.assertRaisesRegex(ValueError, f'required_column_changed:{expected}'):
                    module.validate()

    def test_unrelated_physical_column_addition_is_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); shutil.copytree(ROOT/'database',root/'database'); shutil.copytree(ROOT/'full',root/'full')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.ROOT=root
            schema=root/'database/schema.sql'; content=schema.read_text()
            marker='    retrieved_at timestamptz NOT NULL,\n    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run (ingest_id),'
            self.assertIn(marker, content)
            schema.write_text(content.replace(marker, marker.replace('    ingest_id', '    unrelated_reader_ignored text,\n    ingest_id'), 1))
            module.validate()

    def test_bootstrap_is_the_minimum_reader_api_shape(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'reader'; output.mkdir(); (output/'fixtures').mkdir()
            for name in ('reader-fixture.sql', 'reader-query.sql'):
                shutil.copyfile(exporter.OUT/'fixtures'/name, output/'fixtures'/name)
            original=exporter.OUT; exporter.OUT=output
            try:
                exporter.export()
                doc=json.loads((output/'contract.json').read_text())
                sql=(output/'schema.sql').read_text()
                self.assertEqual(set(doc['minimum_read_contract']['required_objects']), {
                    'usa_atlas.catalog_field', 'usa_atlas.observation', 'usa_atlas.ingest_run'})
                self.assertEqual(doc['adapter_reads']['observation'],
                                 doc['minimum_read_contract']['observation_columns'])
                for table, columns in doc['adapter_reads'].items():
                    body=re.search(rf'CREATE TABLE usa_atlas\.{table} \((.*?)\);', sql, re.S).group(1)
                    for column in columns:
                        self.assertRegex(body, rf'\b{column}\s+')
                self.assertEqual(len(re.findall(r'CREATE TABLE usa_atlas\.', sql)), 3)
                self.assertNotIn('observation_data', sql)
                self.assertNotIn('ALTER TABLE', sql)
            finally:
                exporter.OUT=original

    def test_missing_field_contract_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); shutil.copytree(ROOT/'database',root/'database'); shutil.copytree(ROOT/'full',root/'full')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.ROOT=root
            doc=json.loads((root/'full/field-contract.json').read_text()); doc.pop()
            (root/'full/field-contract.json').write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'contract_must_have_81_rows'):
                module.validate()

    def test_changed_geography_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); shutil.copytree(ROOT/'database',root/'database'); shutil.copytree(ROOT/'full',root/'full')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.ROOT=root
            path=root/'full/field-contract.json'; doc=json.loads(path.read_text()); doc[0]['target_geographies'][0]='invented'
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'field_or_geography_contract_changed'):
                module.validate()

    @unittest.skipUnless(
        os.environ.get('USA_ATLAS_REQUIRE_READER_POSTGRES') == '1'
        or all(shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql')),
        'PostgreSQL 16 binaries unavailable (optional local run)',
    )
    def test_temporary_postgres_reader_query(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); data=root/'data'; sock=root/'socket'; sock.mkdir(); log=root/'postgres.log'
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); port=probe.getsockname()[1]
            subprocess.run(['initdb','-D',str(data),'-A','trust','-U','postgres','--no-locale'],check=True,capture_output=True)
            env={**os.environ,'PGHOST':str(sock),'PGPORT':str(port),'PGUSER':'postgres','PGDATABASE':'postgres'}
            started = False
            try:
                subprocess.run(['pg_ctl','-D',str(data),'-l',str(log),'-o',f"-F -c listen_addresses='' -k {sock} -p {port}",'-w','start'],check=True,capture_output=True)
                started = True
                def psql(sql=None, file=None):
                    args=['psql','-X','-A','-t','-v','ON_ERROR_STOP=1']
                    if file: args += ['-f',str(file)]
                    if sql: args += ['-c',sql]
                    return subprocess.run(args,env=env,text=True,capture_output=True,check=True).stdout
                psql(file=exporter.OUT/'schema.sql')
                psql(file=exporter.OUT/'fixtures/reader-fixture.sql')
                rows=psql(file=exporter.OUT/'fixtures/reader-query.sql')
                self.assertIn('|0|USD|census_acs|2024-acs-acs5|',rows)
                self.assertIn('|100|USD|census_acs|2024-acs-acs5|',rows)
                self.assertNotIn('unadmitted-release',rows)
                self.assertIn('Fixture zero is a real value.',rows)
            finally:
                if started:
                    subprocess.run(['pg_ctl','-D',str(data),'-m','immediate','-w','stop'],
                                   check=False,capture_output=True,timeout=30)

if __name__ == '__main__': unittest.main()
