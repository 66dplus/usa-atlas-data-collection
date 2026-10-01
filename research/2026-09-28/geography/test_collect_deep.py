"""Small synthetic checks of failure modes; no network or production writes."""
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / 'full/collect_deep.py'
SPEC = importlib.util.spec_from_file_location('collect_deep', MODULE_PATH)
deep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deep)


class DeepCollectionTests(unittest.TestCase):
    def test_sentinels_are_never_negative_observations_or_zero(self):
        for token in ['-999999999', '-666666666', '-555555555', '-222222222', '-333333333', '-888888888']:
            value, status, code = deep.cell(token)
            self.assertEqual(value, '')
            self.assertNotEqual(status, 'observed')
            self.assertEqual(code, token)
        self.assertEqual(deep.cell('0'), ('0', 'observed', ''))
        self.assertEqual(deep.cell(None), ('', 'missing', ''))

    def test_missing_moe_is_different_from_provider_missing(self):
        row = deep.observation('tract', '11001000100', 'B01001_025', {'B01001_025E': '13'})
        self.assertEqual(row[6], 'not_collected')
        self.assertEqual(row[11], 'not_collected')
        row = deep.observation('tract', '11001000100', 'B01001_025', {'B01001_025E': '13', 'B01001_025M': None})
        self.assertEqual(row[6], 'missing')

    def test_typed_geoid_and_parent_parts(self):
        values = {'state': '11', 'county': '001', 'tract': '000100', 'block group': '2', 'place': '50000'}
        self.assertEqual(deep.geo_id(values, 'block_group'), '110010001002')
        self.assertEqual(deep.geo_id(values, 'place'), '1150000')
        with self.assertRaises(ValueError):
            deep.geo_id({**values, 'tract': '100'}, 'tract')

    def summary_fixture(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'summary.gz'
        with gzip.open(path, 'wt') as f:
            f.write(text)
        return path

    def test_summary_keeps_native_geo_and_estimate_moe(self):
        path = self.summary_fixture('GEO_ID|B01003_E001|B01003_M001\n0500000US11001|100|-555555555\n1400000US11001000100|40|5\n1500000US110010001001|12|3\n')
        rows = list(deep.summary_rows(path, ['B01003_001'], {'county', 'tract', 'block_group'}))
        self.assertEqual([r[:2] for r in rows], [['county', '11001'], ['tract', '11001000100'], ['block_group', '110010001001']])
        self.assertEqual(rows[0][6], 'moe_controlled_estimate')
        self.assertEqual(rows[2][3:5], ['12', '3'])
        self.assertEqual(len(list(deep.summary_rows(path, ['B01003_001'], {'block_group'}))), 1)

    def test_county_is_never_filled_into_absent_block_group(self):
        path = self.summary_fixture('GEO_ID|B01003_E001|B01003_M001\n0500000US11001|100|4\n')
        self.assertEqual(list(deep.summary_rows(path, ['B01003_001'], {'block_group'})), [])

    def test_only_whole_population_nation_is_selected(self):
        path = self.summary_fixture('GEO_ID|B01003_E001|B01003_M001\n0100000US|100|4\n0100089US|20|2\n')
        rows = list(deep.summary_rows(path, ['B01003_001'], {'nation'}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:2], ['nation', 'US'])

    def test_normalization_records_real_geo_counts(self):
        path = self.summary_fixture('GEO_ID|B01003_E001|B01003_M001\n1500000US110010001001|12|3\n1500000US110010001002|14|4\n')
        with tempfile.TemporaryDirectory() as directory:
            job = next(j for j in deep.plan() if j.get('table') == 'B01003')
            result = deep.normalize_job(job, path, Path(directory), {'county', 'tract', 'block_group'})
            self.assertEqual(result['geography_counts'], {'block_group': 2})
            self.assertEqual(result['rows_by_geography'], {'block_group': 2})

    def test_duplicate_geo_and_missing_contract_column_fail(self):
        path = self.summary_fixture('GEO_ID|B01003_E001|B01003_M001\n0500000US11001|100|4\n0500000US11001|100|4\n')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            list(deep.summary_rows(path, ['B01003_001'], {'county'}))
        with self.assertRaisesRegex(ValueError, 'contract_variables_missing'):
            list(deep.summary_rows(path, ['B19013_001'], {'county'}))

    def test_summary_duplicate_headers_and_bad_row_width_fail(self):
        cases = [
            ('GEO_ID|B01003_E001|B01003_M001|B01003_E001\n', 'duplicate_summary_header'),
            ('GEO_ID|B01003_E001|B01003_M001\n0500000US11001|100\n', 'invalid_summary_row_width'),
            ('GEO_ID|B01003_E001|B01003_M001\n0500000US11001|100|4|extra\n', 'invalid_summary_row_width'),
        ]
        for text, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason):
                    list(deep.summary_rows(self.summary_fixture(text), ['B01003_001'], {'county'}))

    def test_places_duplicate_headers_and_truncated_rows_fail(self):
        header = 'tractfips,countyfips,obesity_crudeprev,obesity_crude95ci,diabetes_crudeprev,diabetes_crude95ci,lpa_crudeprev,lpa_crude95ci'
        cases = [(header + ',tractfips\n', 'duplicate_places_header'),
                 (header + '\n11001000100,11001,30\n', 'invalid_places_row_width')]
        for text, reason in cases:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, reason):
                    deep.normalize_job(deep.plan()[-1], self.summary_fixture(text), Path(directory), {'tract'})

    def test_places_rejects_request_for_block_groups_only(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'requires_tract'):
                deep.collect(Path(directory), 'cdc-places', 1, 1, {'block_group'})

    def test_cached_raw_corruption_fails_without_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / 'raw').mkdir()
            job = deep.plan()[0]
            path = out / 'raw' / (job['id'] + '.gz')
            path.write_bytes(b'corrupt')
            path.with_name(path.name + '.json').write_text(json.dumps({'job_sha256': 'x', 'sha256': 'x'}))
            with self.assertRaisesRegex(ValueError, 'raw_binding_or_hash_mismatch'):
                deep.download(job, out, 1, 100)

    def test_plan_contains_only_existing_nonfood_series(self):
        plan = deep.plan()
        self.assertEqual(len(plan), 20)
        self.assertEqual(sum(x['provider'] == 'acs-summary' for x in plan), 19)
        cdc = plan[-1]
        self.assertEqual(cdc['variant'], 'crude_prevalence')
        self.assertNotIn('food', cdc['url'])


if __name__ == '__main__':
    unittest.main()
