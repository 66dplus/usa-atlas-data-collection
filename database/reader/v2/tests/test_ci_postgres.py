"""Portable PostgreSQL integration for the additive reader-v2 fixture path."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import psycopg2
from psycopg2 import sql

from database.reader.v2 import admission


ROOT = Path(__file__).resolve().parents[4]
V1_SCHEMA = ROOT / "database/reader/v1/schema.sql"
V2_SCHEMA = ROOT / "database/reader/v2/schema.sql"
V2_FIXTURE = ROOT / "database/reader/v2/fixtures/reader-fixture.sql"
V2_INVARIANTS = ROOT / "database/reader/v2/tests/invariants.sql"


class ReaderV2PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="reader-v2-ci-pg-")
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "data"
        cls.sock = cls.root / "socket"
        cls.sock.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        subprocess.run(
            ["initdb", "-D", str(cls.data), "-A", "trust", "-U", "postgres", "--no-locale"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "postgres.log"),
             "-o", f"-F -c listen_addresses='' -k {cls.sock} -p {cls.port}", "-w", "start"],
            check=True, capture_output=True, text=True,
        )
        admin = psycopg2.connect(host=str(cls.sock), port=cls.port, user="postgres", dbname="postgres")
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute("CREATE DATABASE reader_v2_ci_fixture")
        admin.close()
        cls.conn = psycopg2.connect(host=str(cls.sock), port=cls.port, user="postgres", dbname="reader_v2_ci_fixture")
        cls.conn.autocommit = True
        with cls.conn.cursor() as cur:
            cur.execute("CREATE ROLE atlas_reader NOLOGIN")
            cur.execute(V1_SCHEMA.read_text(encoding="utf-8"))
            cur.execute("""INSERT INTO usa_atlas.catalog_field
                (catalog_field_id,catalog_label,planned_state,rate_limit_profile,source_release,contract,contract_sha256)
                VALUES ('11.01','Legacy cancer field','run_now','uscs','legacy-release','{}',repeat('a',64))""")
            cur.execute("""INSERT INTO usa_atlas.ingest_run
                (ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,completed_at,status,error_code)
                VALUES ('00000000-0000-4000-8000-000000009999','legacy','legacy-fixture',repeat('b',64),repeat('c',64),1,
                '2026-10-26T00:00:00Z','2026-10-26T00:01:00Z','pass',NULL)""")
            cur.execute("""INSERT INTO usa_atlas.observation
                (geo_id,geo_type,period,field_id,catalog_field_id,value,unit,source,source_release,source_url,methodology_note,retrieved_at,ingest_id)
                VALUES ('06001','county','2023','11.01','11.01',1,'count','legacy','legacy-release','https://example.test',
                'legacy fixture row','2026-10-26T00:00:00Z','00000000-0000-4000-8000-000000009999')""")
        cls.legacy_catalog = cls._fetch("SELECT * FROM usa_atlas.catalog_field ORDER BY catalog_field_id")
        cls.legacy_observation = cls._fetch("SELECT * FROM usa_atlas.observation ORDER BY geo_id,period,catalog_field_id")
        with cls.conn.cursor() as cur:
            cur.execute(V2_SCHEMA.read_text(encoding="utf-8"))
            cur.execute(V2_FIXTURE.read_text(encoding="utf-8"))
            cur.execute(V2_INVARIANTS.read_text(encoding="utf-8"))
            contract_hash = admission.sha256(admission.CONTRACT)
            cur.execute("UPDATE usa_atlas.ingest_run SET contract_sha256=%s WHERE ingest_id='00000000-0000-4000-8000-000000000101'", (contract_hash,))
            cur.execute("""INSERT INTO usa_atlas.reader_batch
                (ingest_id,contract_version,collector_version,observation_release,candidate_status,input_manifest_sha256)
                VALUES ('00000000-0000-4000-8000-000000000101','2.0.0','fixture-collector',
                'multi-source-local-review','local_review',%s)""", ("a" * 64,))
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "stage_conn"):
            cls.stage_conn.close()
        if hasattr(cls, "conn"):
            cls.conn.close()
        if hasattr(cls, "data"):
            subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "fast", "-w", "stop"],
                           check=True, capture_output=True, text=True)
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    @classmethod
    def _fetch(cls, query, params=None):
        with cls.conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    @staticmethod
    def _fetch_from(connection, query, params=None):
        with connection.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def _stage_fixture_bundle(self):
        """Export the repository fixture in canonical COPY format and run the real stage action."""
        dbname = "reader_v2_ci_stage_fixture"
        admin = psycopg2.connect(host=str(self.sock), port=self.port, user="postgres", dbname="postgres")
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        admin.close()
        self.stage_conn = psycopg2.connect(host=str(self.sock), port=self.port, user="postgres", dbname=dbname)
        self.stage_conn.autocommit = True
        with self.stage_conn.cursor() as cur:
            cur.execute(V1_SCHEMA.read_text(encoding="utf-8"))
            cur.execute("""INSERT INTO usa_atlas.catalog_field
                (catalog_field_id,catalog_label,planned_state,rate_limit_profile,source_release,contract,contract_sha256)
                VALUES ('11.01','Legacy cancer field','run_now','uscs','legacy-release','{}',repeat('a',64))""")
            cur.execute("""INSERT INTO usa_atlas.ingest_run
                (ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,completed_at,status,error_code)
                VALUES ('00000000-0000-4000-8000-000000009999','legacy','legacy-fixture',repeat('b',64),repeat('c',64),1,
                '2026-10-26T00:00:00Z','2026-10-26T00:01:00Z','pass',NULL)""")
            cur.execute("""INSERT INTO usa_atlas.observation
                (geo_id,geo_type,period,field_id,catalog_field_id,value,unit,source,source_release,source_url,methodology_note,retrieved_at,ingest_id)
                VALUES ('06001','county','2023','11.01','11.01',1,'count','legacy','legacy-release','https://example.test',
                'legacy fixture row','2026-10-26T00:00:00Z','00000000-0000-4000-8000-000000009999')""")
        self.stage_conn.commit()

        bundle_root = self.root / "portable-fixture"
        (bundle_root / "tables").mkdir(parents=True)
        shutil.copyfile(V2_SCHEMA, bundle_root / "schema.sql")
        ingest_id = "00000000-0000-4000-8000-000000000101"
        manifest_hash = "a" * 64
        tables = {}
        ingests = []
        with self.conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'; SET DateStyle TO ISO, YMD; SET IntervalStyle TO iso_8601; SET client_encoding TO 'UTF8'")
            cur.execute("""SELECT ingest_id::text,source,artifact_path,artifact_sha256,contract_sha256,row_count,
                started_at,completed_at,status,error_code FROM usa_atlas.ingest_run WHERE ingest_id=%s::uuid""", (ingest_id,))
            ledger = list(cur.fetchone())
            ledger[2] = "reader-v2-bundle://" + ledger[3]
            ledger[6] = ledger[6].astimezone(timezone.utc).isoformat()
            ledger[7] = ledger[7].astimezone(timezone.utc).isoformat() if ledger[7] else None
            counts = {}
            digests = {}
            for relation in admission.RELATIONS:
                columns, keys = admission._stable_columns(cur, relation)
                path = bundle_root / "tables" / f"{relation}.copy"
                if relation == "reader_v2_catalog_field":
                    cur.execute("SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=%s::uuid UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=%s::uuid", (ingest_id, ingest_id))
                    releases = [row[0] for row in cur.fetchall()]
                    where = sql.SQL("source_release = ANY(ARRAY[{}]::text[])").format(sql.SQL(",").join(sql.Literal(x) for x in releases))
                else:
                    where = sql.SQL("ingest_id={}::uuid").format(sql.Literal(ingest_id))
                if relation == "reader_v2_catalog_field":
                    query = sql.SQL("COPY (SELECT {} FROM usa_atlas.{} WHERE {} ORDER BY {}) TO STDOUT WITH (FORMAT text, ENCODING 'UTF8')").format(
                        sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(relation), where,
                        sql.SQL(",").join(map(sql.Identifier, keys)))
                    with path.open("wb") as stream:
                        cur.copy_expert(query.as_string(self.conn), stream)
                    cur.execute("SELECT count(*) FROM usa_atlas.reader_v2_catalog_field WHERE source_release=ANY(%s)", (releases,))
                else:
                    query = sql.SQL("COPY (SELECT {} FROM usa_atlas.{} WHERE {} ORDER BY {}) TO STDOUT WITH (FORMAT text, ENCODING 'UTF8')").format(
                        sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(relation), where,
                        sql.SQL(",").join(map(sql.Identifier, keys)))
                    with path.open("wb") as stream:
                        cur.copy_expert(query.as_string(self.conn), stream)
                    cur.execute(sql.SQL("SELECT count(*) FROM usa_atlas.{} WHERE ingest_id=%s::uuid").format(sql.Identifier(relation)), (ingest_id,))
                counts[relation] = cur.fetchone()[0]
                raw = path.read_bytes()
                tables[relation] = {"path": path.relative_to(bundle_root).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                    "row_count": raw.count(b"\n"), "columns": columns, "primary_key": keys}
                digests[relation] = admission._relation_digest(cur, relation, ingest_id)
            ingests.append({"ledger": ledger, "input_manifest_sha256": manifest_hash,
                            "table_counts": counts, "table_digests": digests})
        bundle = {"format": "usa_atlas_reader_v2_portable_stage_bundle", "bundle_version": 1,
            "candidate_status": "local_review", "contract_version": "2.0.0",
            "contract_sha256": admission.sha256(admission.CONTRACT),
            "schema_fingerprint": json.loads(admission.CONTRACT.read_text())["schema_fingerprint"],
            "manifest_sha256": "e" * 64, "schema": {"path": "schema.sql"},
            "tables": tables, "ingests": ingests}
        stage_target = {"target_id": "reader_v2_ci_stage_fixture", "target_class": "disposable_test",
            "dbname": dbname, "reader_role": "atlas_reader", "host": str(self.sock),
            "port": self.port, "user": "postgres", "write_enabled": True}
        receipt = self.root / "stage-receipt.json"
        receipt.write_text(json.dumps({"decision": "stage", "bundle_sha256": bundle["manifest_sha256"],
            "contract_sha256": bundle["contract_sha256"], "target_id": stage_target["target_id"],
            "reviewer": "CI disposable fixture", "expires_at":
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}), encoding="utf-8")
        args = type("StageArgs", (), {"bundle_dir": bundle_root, "target_config": "unused",
            "review_receipt": receipt, "apply": True})()
        with patch.object(admission, "GUARD_ROOT", self.root.resolve()), \
             patch.object(admission, "connect_target", return_value=stage_target), \
             patch.object(admission, "_read_portable_bundle", return_value=(bundle_root, bundle)):
            admission.stage_bundle(args)
        return stage_target, ingest_id, manifest_hash

    def test_admission_gates_legacy_immutability_and_same_count_tamper(self):
        target, ingest, manifest_hash = self._stage_fixture_bundle()
        contract_hash = admission.sha256(admission.CONTRACT)

        def admitted_rows():
            return self._fetch_from(self.stage_conn, """SELECT count(*) FROM usa_atlas.reader_observation o
                JOIN usa_atlas.ingest_run i USING (ingest_id)
                JOIN usa_atlas.reader_batch b USING (ingest_id)
                WHERE i.status='pass' AND b.candidate_status='admitted'""")[0][0]

        self.assertEqual(admitted_rows(), 0)
        snapshot = admission.count_ingests(target, [manifest_hash], contract_hash)
        self.assertEqual([row["ingest_id"] for row in snapshot], [ingest])
        bundle = {
            "format": "usa_atlas_reader_v2_admission_bundle",
            "contract_sha256": contract_hash,
            "expected_input_manifest_sha256s": [manifest_hash],
            "ingests": snapshot,
        }
        digest = "d" * 64

        def invoke(action, decision):
            with tempfile.TemporaryDirectory(prefix="reader-v2-ci-receipt-") as temp:
                receipt = Path(temp) / "review.json"
                receipt.write_text(json.dumps({
                    "decision": decision, "bundle_sha256": digest,
                    "contract_sha256": contract_hash, "target_id": target["target_id"],
                    "reviewer": "CI disposable fixture", "reason": "exercise reader gate",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                }), encoding="utf-8")
                args = type("Args", (), {"target_config": "unused", "bundle": "unused",
                    "review_receipt": receipt, "apply": True, "actor": "", "reason": ""})()
                with patch.object(admission, "GUARD_ROOT", Path(temp).resolve()), \
                     patch.object(admission, "connect_target", return_value=target), \
                     patch.object(admission, "validate_bundle", return_value=(bundle, digest)):
                    admission.apply_action(args, action)

        invoke("admit", "approved")
        self.assertGreater(admitted_rows(), 0)
        privileges = self._fetch_from(self.stage_conn, """SELECT
            has_table_privilege('atlas_reader','usa_atlas.reader_observation','SELECT'),
            has_table_privilege('atlas_reader','usa_atlas.reader_observation','INSERT')""")[0]
        self.assertEqual(privileges, (True, False))
        with self.stage_conn.cursor() as cur:
            cur.execute("SET ROLE atlas_reader")
            cur.execute("""SELECT count(*) FROM usa_atlas.reader_observation o
                JOIN usa_atlas.ingest_run i USING (ingest_id)
                JOIN usa_atlas.reader_batch b USING (ingest_id)
                WHERE i.status='pass' AND b.candidate_status='admitted'""")
            self.assertGreater(cur.fetchone()[0], 0)
            cur.execute("RESET ROLE")
        self.assertEqual(self._fetch_from(self.stage_conn, "SELECT action FROM usa_atlas.reader_v2_admission_event ORDER BY event_id"), [("admitted",)])
        original_value = self._fetch_from(self.stage_conn, "SELECT value FROM usa_atlas.reader_observation WHERE observation_id='unemp-ca-annual-2025'")[0][0]
        before_count = self._fetch_from(self.stage_conn, "SELECT count(*) FROM usa_atlas.reader_observation WHERE ingest_id=%s", (ingest,))[0][0]
        with self.stage_conn.cursor() as cur:
            cur.execute("UPDATE usa_atlas.reader_observation SET value=value+0.125 WHERE observation_id='unemp-ca-annual-2025'")
        with self.assertRaisesRegex(ValueError, "canonical digest"):
            invoke("revoke", "revoke")
        self.assertEqual(self._fetch_from(self.stage_conn,
            "SELECT action FROM usa_atlas.reader_v2_admission_event ORDER BY event_id"), [("admitted",)])
        self.assertEqual(self._fetch_from(self.stage_conn, "SELECT count(*) FROM usa_atlas.reader_observation WHERE ingest_id=%s", (ingest,))[0][0], before_count)
        self.assertEqual(admitted_rows(), before_count)
        with self.stage_conn.cursor() as cur:
            cur.execute("UPDATE usa_atlas.reader_observation SET value=%s WHERE observation_id='unemp-ca-annual-2025'", (original_value,))
        invoke("revoke", "revoke")
        self.assertEqual(admitted_rows(), 0)
        with self.stage_conn.cursor() as cur:
            cur.execute("SET ROLE atlas_reader")
            cur.execute("""SELECT count(*) FROM usa_atlas.reader_observation o
                JOIN usa_atlas.ingest_run i USING (ingest_id)
                JOIN usa_atlas.reader_batch b USING (ingest_id)
                WHERE i.status='pass' AND b.candidate_status='admitted'""")
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute("RESET ROLE")
        self.assertEqual(self._fetch_from(self.stage_conn, "SELECT action FROM usa_atlas.reader_v2_admission_event ORDER BY event_id"), [("admitted",), ("revoked",)])
        self.assertEqual(self._fetch_from(self.stage_conn, "SELECT * FROM usa_atlas.catalog_field ORDER BY catalog_field_id"), self.legacy_catalog)
        self.assertEqual(self._fetch_from(self.stage_conn, "SELECT * FROM usa_atlas.observation ORDER BY geo_id,period,catalog_field_id"), self.legacy_observation)


if __name__ == "__main__":
    unittest.main()
