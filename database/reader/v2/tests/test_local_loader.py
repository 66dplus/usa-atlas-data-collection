import hashlib
import json
import pathlib
import tempfile
import unittest

from database.reader.v2.load_local_review import GUARD_ROOT, checked_manifest, guard


class LocalLoaderGuardTests(unittest.TestCase):
    def setUp(self):
        GUARD_ROOT.mkdir(parents=True, exist_ok=True)

    def test_unsafe_target_names_and_wrong_socket_are_refused(self):
        with tempfile.TemporaryDirectory(dir=str(GUARD_ROOT)) as temp:
            config=pathlib.Path(temp)/'guard.json'
            config.write_text(json.dumps({'host':'/tmp/other','port':55446,'user':'atlas','dbname':'reader_v2_worker_abcdef12'}))
            with self.assertRaisesRegex(ValueError,'approved temporary'):
                guard(config)
            config.write_text(json.dumps({'host':str(GUARD_ROOT/'pgsocket'),'port':55446,'user':'atlas','dbname':'usa_atlas'}))
            with self.assertRaisesRegex(ValueError,'unique reader_v2_worker'):
                guard(config)

    def test_corrupt_prepared_output_is_refused_before_database_connect(self):
        with tempfile.TemporaryDirectory(dir=str(GUARD_ROOT)) as temp:
            root=pathlib.Path(temp)
            (root/'data.jsonl').write_text('{"candidate_status":"local_review"}\n')
            (root/'boundary.geojson').write_text('{}')
            (root/'features.jsonl').write_text('{}\n')
            manifest={
              'candidate_status':'local_review_not_admitted',
              'outputs':{'sample':{'path':str(root/'data.jsonl'),'sha256':'0'*64}},
              'boundary':{'path':str(root/'boundary.geojson'),'sha256':hashlib.sha256(b'{}').hexdigest(),'features_jsonl_path':str(root/'features.jsonl'),'features_jsonl_sha256':hashlib.sha256(b'{}\n').hexdigest()}
            }
            (root/'reader-results.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'corrupt prepared output'):
                checked_manifest(root)


if __name__=='__main__':
    unittest.main()
