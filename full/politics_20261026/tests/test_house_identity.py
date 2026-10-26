import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from full.politics_20261026 import house_identity as identity


class HouseIdentityTests(unittest.TestCase):
    def constants_for(self, raw, original, rows):
        return mock.patch.multiple(identity, SOURCE_SHA256=hashlib.sha256(raw).hexdigest(),
            ORIGINAL_BYTES=len(original), ORIGINAL_MD5=hashlib.md5(original).hexdigest(),
            ORIGINAL_SHA256=hashlib.sha256(original).hexdigest(), ROWS=rows,
            ORIGINAL_UNF="UNF:6:test")

    def test_reconstructs_exact_single_column_serialization(self):
        raw=b"header\n\"a,b,\\\"quoted\\\"\"\n\"c,d\"\n"
        original=b"header\na,b,\"quoted\"\nc,d\n"
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/"source.tab"; source.write_bytes(raw)
            with self.constants_for(raw,original,2):
                self.assertEqual(identity.reconstruct(source),original)

    def test_rejects_changed_row_order_and_quoting(self):
        raw=b"header\n\"a,b\"\n\"c,d\"\n"
        original=b"header\na,b\nc,d\n"
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/"source.tab"
            with self.constants_for(raw,original,2):
                source.write_bytes(b"header\n\"c,d\"\n\"a,b\"\n")
                with self.assertRaisesRegex(ValueError,"mirror SHA-256"):
                    identity.reconstruct(source)
                source.write_bytes(b"header\n\"a,b\n\"c,d\"\n")
                with mock.patch.object(identity,"SOURCE_SHA256",hashlib.sha256(source.read_bytes()).hexdigest()):
                    with self.assertRaisesRegex(ValueError,"single-string serialization"):
                        identity.reconstruct(source)

    def test_metadata_identity_requires_exact_official_descriptor(self):
        with tempfile.TemporaryDirectory() as temp:
            metadata=pathlib.Path(temp)/"metadata.json"
            obj={"status":"OK","data":{"latestVersion":{"versionNumber":15,"UNF":identity.ORIGINAL_UNF,
                "files":[{"dataFile":{"id":13592823,"filename":"1976-2024-house.tab",
                    "originalFileSize":identity.ORIGINAL_BYTES,"checksum":{"type":"MD5","value":identity.ORIGINAL_MD5}}}]}}}
            metadata.write_text(json.dumps(obj))
            with mock.patch.object(identity,"METADATA_SHA256",identity.digest(metadata.read_bytes(),"sha256")):
                self.assertEqual(identity._released_file(metadata)["id"],13592823)
                obj["data"]["latestVersion"]["files"][0]["dataFile"]["checksum"]["value"]="00000000000000000000000000000000"
                metadata.write_text(json.dumps(obj))
                with self.assertRaisesRegex(ValueError,"size or checksum metadata differs"):
                    identity._released_file(metadata)
                obj["data"]["latestVersion"]["files"][0]["dataFile"]["checksum"]["value"]=identity.ORIGINAL_MD5
                obj["data"]["latestVersion"]["versionNumber"]=14
                metadata.write_text(json.dumps(obj))
                with self.assertRaisesRegex(ValueError,"pinned released House v15"):
                    identity._released_file(metadata)


if __name__ == "__main__":
    unittest.main()
