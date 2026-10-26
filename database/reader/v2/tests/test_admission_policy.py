import hashlib
import json
import pathlib
import tempfile
import unittest
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch

from database.reader.v2 import admission


class AdmissionPolicyTests(unittest.TestCase):
    def test_formal_contract_identity_and_filters_are_separate_and_exact(self):
        contract=json.loads(admission.CONTRACT.read_text())
        self.assertEqual(contract["format"],"usa_atlas_reader_contract")
        self.assertEqual(contract["contract_id"],"usa_atlas.application_reader")
        self.assertEqual(contract["version"],"2.0.0")
        self.assertTrue(contract["read_only"])
        self.assertEqual(contract["admission_filter"],"usa_atlas.ingest_run.status = 'pass'")
        self.assertEqual(contract["additional_reader_filter"],"usa_atlas.reader_batch.candidate_status = 'admitted'")
        fingerprint=hashlib.sha256(json.dumps(contract["objects"],sort_keys=True,separators=(",",":")).encode()).hexdigest()
        self.assertEqual(contract["schema_fingerprint"],fingerprint)
        self.assertEqual(set(contract["objects"]),set(contract["object_metadata"]))
        for relative,digest in contract["artifact_sha256"].items():
            path=admission.ROOT/relative
            self.assertTrue(path.is_file(),relative)
            self.assertEqual(admission.sha256(path),digest,relative)

    def test_catalog_writer_never_touches_immutable_v1_catalog(self):
        from database.reader.v2.catalog import save_v2_catalog_field
        class Cursor:
            def __init__(self): self.statements=[]
            def execute(self, statement, params): self.statements.append(statement)
        cur=Cursor()
        save_v2_catalog_field(cur,"12.01",{"label":"President","release":"dataverse-VOQCHQ-v20","dataset_id":"president_election","source_code":"MEDSL"},{},"2.0.0")
        self.assertEqual(len(cur.statements),1)
        self.assertIn("reader_v2_catalog_field",cur.statements[0])
        self.assertNotIn("INSERT INTO usa_atlas.catalog_field",cur.statements[0])

    def test_portable_paths_reject_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory(dir=admission.GUARD_ROOT) as temp:
            root=pathlib.Path(temp); (root/"assets").mkdir(); target=root/"outside"; target.write_text("x")
            (root/"assets"/"link").symlink_to(target)
            with self.assertRaises(ValueError): admission._bundle_path(root,"../outside")
            with self.assertRaises(ValueError): admission._bundle_path(root,"assets/link")

    def test_portable_manifest_detects_same_count_payload_tamper(self):
        with tempfile.TemporaryDirectory(dir=admission.GUARD_ROOT) as temp:
            root=pathlib.Path(temp); (root/"tables").mkdir(); (root/"schema.sql").write_bytes((admission.ROOT/"database/reader/v2/schema.sql").read_bytes())
            table=root/"tables/reader_batch.copy"; table.write_bytes(b"a\tb\n")
            evidence=root/"receipt.json"; evidence.write_text("{}")
            def ref(p): return {"path":p.relative_to(root).as_posix(),"sha256":admission.sha256(p),"bytes":p.stat().st_size}
            raw=root/"raw.bin"; raw.write_bytes(b"raw"); meta=root/"metadata.json"; meta.write_text("{}")
            portable=[{"role":"source","path":"raw.bin","sha256":admission.sha256(raw),"bytes":raw.stat().st_size},{"role":"metadata","path":"metadata.json","sha256":admission.sha256(meta),"bytes":meta.stat().st_size}]
            source_doc={"blockers":[],"production_eligible":True,"verified_artifacts":[],"source_receipts":[{"sha256":admission.sha256(raw)},{"sha256":admission.sha256(meta)}],"code_artifacts":[],"house_source_identity":{"raw_source_sha256":admission.sha256(raw),"official_metadata_sha256":admission.sha256(meta),"reconstructed_sha256":"expected"}}
            evidence.write_text(json.dumps(source_doc))
            codes=[]
            for rel in admission.CODE_FILE_PATHS:
                src=admission.ROOT/rel; digest=admission.sha256(src); target_path=root/"producer"/digest/src.name; target_path.parent.mkdir(parents=True,exist_ok=True); target_path.write_bytes(src.read_bytes()); codes.append({"source_path":rel,"path":target_path.relative_to(root).as_posix(),"sha256":digest,"bytes":target_path.stat().st_size})
            data={"format":"usa_atlas_reader_v2_portable_stage_bundle","bundle_version":1,"contract_version":"2.0.0","contract_sha256":admission.sha256(admission.CONTRACT),"schema_fingerprint":json.loads(admission.CONTRACT.read_text())["schema_fingerprint"],"schema":{**ref(root/"schema.sql")},"evidence_manifest":ref(evidence),"portable_evidence":portable,"producer_code":codes,"tables":{"reader_batch":{**ref(table),"row_count":1,"columns":["a","b"],"primary_key":["a"]}},"ingests":[]}
            data["manifest_sha256"]=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            (root/"bundle.json").write_text(json.dumps(data))
            with patch.object(admission,"verify_house_identity",return_value={"original_sha256":"expected","status":"official_original_identity_verified"}):
                admission._read_portable_bundle(root)
            table.write_bytes(b"c\td\n")
            with self.assertRaisesRegex(ValueError,"COPY payload"):
                with patch.object(admission,"verify_house_identity",return_value={"original_sha256":"expected","status":"official_original_identity_verified"}): admission._read_portable_bundle(root)

    def test_target_whitelist_requires_exact_declared_db_and_reader(self):
        with tempfile.TemporaryDirectory(dir=admission.GUARD_ROOT) as temp:
            path=pathlib.Path(temp)/"target.json"
            cfg={"target_id":"reader_v2_worker_integration_20261026","target_class":"disposable_test",
                "dbname":"reader_v2_worker_integration_20261026","reader_role":"atlas_reader",
                "host":"/tmp/usa-maps-data-flow-20261026/pgsocket","port":55446,"user":"atlas"}
            path.write_text(json.dumps(cfg))
            self.assertEqual(admission.connect_target(path)["dbname"],cfg["dbname"])
            cfg["dbname"]="usa_atlas"; path.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError,"not declared"):
                admission.connect_target(path)

    def test_target_whitelisted_unique_stage_databases_remain_socket_guarded(self):
        with tempfile.TemporaryDirectory(dir=admission.GUARD_ROOT) as temp:
            path=pathlib.Path(temp)/"target.json"
            cfg={"target_id":"reader_v2_stage_test","target_class":"disposable_test",
                "dbname":"reader_v2_stage_test_3f82b1","reader_role":"atlas_reader",
                "host":"/tmp/usa-maps-data-flow-20261026/pgsocket","port":55446,"user":"atlas"}
            path.write_text(json.dumps(cfg)); self.assertEqual(admission.connect_target(path)["dbname"],cfg["dbname"])
            cfg["host"]="localhost"; path.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError,"approved task socket"):
                admission.connect_target(path)

    def test_admission_cli_default_is_nonmutating_dry_run(self):
        with tempfile.TemporaryDirectory(dir=admission.GUARD_ROOT) as temp:
            root=pathlib.Path(temp)
            raw=root/"source.bin"; raw.write_bytes(b"fixture raw")
            metadata=root/"metadata.json"; metadata.write_text("{}")
            output_refs=[]
            for role in ("politics","refresh","bls"):
                artifact=root/(role+".json"); artifact.write_text("{}")
                output_refs.append({"role":role,"path":str(artifact),"sha256":admission.sha256(artifact)})
            config=root/"target.json"
            config.write_text(json.dumps({"target_id":"reader_v2_worker_integration_20261026",
                "target_class":"disposable_test","dbname":"reader_v2_worker_integration_20261026",
                "reader_role":"atlas_reader","host":"/tmp/usa-maps-data-flow-20261026/pgsocket",
                "port":55446,"user":"atlas"}))
            contract=json.loads(admission.CONTRACT.read_text())
            code_refs=[{"path":str((admission.ROOT/rel).resolve()),"sha256":admission.sha256(admission.ROOT/rel)} for rel in admission.CODE_FILE_PATHS]
            bundle={"format":"usa_atlas_reader_v2_admission_bundle","contract_id":contract["contract_id"],
                "contract_version":"2.0.0","schema_fingerprint":contract["schema_fingerprint"],
                "production_eligible":True,"candidate_status":"local_review_not_admitted",
                "blockers":[],"verified_artifacts":[],"source_receipts":[],
                "verified_artifacts":output_refs,"code_artifacts":code_refs,
                "source_quality":{"house_source_identity_verified":True},
                "house_source_identity":{"raw_source_path":str(raw),"raw_source_sha256":admission.sha256(raw),
                    "official_metadata_path":str(metadata),"official_metadata_sha256":admission.sha256(metadata),
                    "reconstructed_sha256":"fixture-reconstructed"},
                "contract_sha256":admission.sha256(admission.CONTRACT),"ingests":[]}
            bundle_path=root/"bundle.json"; bundle_path.write_text(json.dumps(bundle))
            args=SimpleNamespace(target_config=config,bundle=bundle_path,review_receipt=None,apply=False,actor="",reason="")
            out=io.StringIO()
            with patch.object(admission,"verify_house_identity",return_value={"original_sha256":"fixture-reconstructed"}), contextlib.redirect_stdout(out):
                admission.apply_action(args,"admit")
            result=json.loads(out.getvalue())
            self.assertEqual(result["status"],"dry_run")
            self.assertFalse(result["mutated"])

if __name__ == "__main__":
    unittest.main()
