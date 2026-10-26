"""Prepare and transactionally admit hash-bound reader-v2 bundles; dry-run is the default."""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2 import sql

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from database.reader.v2.load_local_review import GUARD_ROOT, sha256
from full.politics_20261026.house_identity import verify as verify_house_identity

ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "database/reader/v2/contract.json"
TARGET_POLICY = ROOT / "database/reader/v2/production-target-policy.json"
ADVISORY_LOCK = 842091770
RELATIONS = (
    "reader_batch", "reader_v2_catalog_field", "reader_observation", "geography_boundary",
    "election_contest", "election_candidate", "election_party_result", "election_availability",
)
CODE_FILE_PATHS = (
    "database/reader/v2/schema.sql","database/reader/v2/prepare_refresh.py",
    "database/reader/v2/load_refresh_local_review.py","database/reader/v2/load_local_review.py",
    "database/reader/v2/catalog.py","database/reader/v2/loader_input_mapping.json",
    "database/reader/v2/fixtures/reader-fixture.sql","database/reader/v2/tests/invariants.sql",
    "database/reader/v2/tests/run_disposable_integration.py",
    "database/reader/v2/admission.py","full/politics_20261026/prepare.py",
    "full/politics_20261026/prepare_bls.py","full/politics_20261026/house_identity.py",
    "database/reader/v2/contract.json","database/reader/v2/production-target-policy.json",
    "database/reader/v2/consumer-protocol.md","database/reader/v2/ADMISSION.md",
    "full/politics_20261026/tests/test_house_identity.py",
    "database/reader/v2/tests/test_admission_policy.py",
    "database/reader/v2/tests/test_prepare_fbi_annual.py",
    "database/reader/v2/tests/test_actual_app_adapter.py",
)


def file_ref(path, expected_hash=None):
    path = pathlib.Path(path).resolve()
    if not path.is_file():
        raise ValueError("required admission artifact is missing")
    digest = sha256(path)
    if expected_hash and digest != expected_hash:
        raise ValueError("admission artifact does not match declared SHA-256")
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def _bundle_path(root, relative):
    rel = pathlib.PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("bundle path must be a contained relative path")
    root = pathlib.Path(root).resolve()
    path = root.joinpath(*rel.parts)
    cursor=root
    symlink=False
    for part in rel.parts:
        cursor=cursor/part
        symlink=symlink or cursor.is_symlink()
    if root not in path.resolve().parents or symlink:
        raise ValueError("bundle path escapes its root or uses a symlink")
    return path


def _stable_columns(cur, relation):
    cur.execute("""SELECT column_name FROM information_schema.columns
        WHERE table_schema='usa_atlas' AND table_name=%s ORDER BY ordinal_position""", (relation,))
    columns = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT a.attname FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(i.indkey)
        WHERE n.nspname='usa_atlas' AND t.relname=%s AND i.indisprimary ORDER BY array_position(i.indkey,a.attnum)""", (relation,))
    keys = [r[0] for r in cur.fetchall()]
    if not columns or not keys:
        raise ValueError("bundle relation is missing or has no stable primary key")
    return columns, keys


def _relation_digest(cur, relation, ingest_id):
    import io
    columns, keys = _stable_columns(cur, relation)
    stable = [c for c in columns if c not in ("candidate_status", "created_at")]
    if relation == "reader_v2_catalog_field":
        cur.execute("SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=%s::uuid UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=%s::uuid",(ingest_id,ingest_id))
        releases=[r[0] for r in cur.fetchall()]
        if not releases: return hashlib.sha256(b"").hexdigest()
        filt=sql.SQL("source_release = ANY(ARRAY[{}]::text[])").format(sql.SQL(",").join(sql.Literal(x) for x in releases))
    else:
        filt=sql.SQL("ingest_id={}::uuid").format(sql.Literal(ingest_id))
    query=sql.SQL("COPY (SELECT {} FROM usa_atlas.{} WHERE {} ORDER BY {}) TO STDOUT WITH (FORMAT text, ENCODING 'UTF8')").format(
        sql.SQL(",").join(map(sql.Identifier,stable)),sql.Identifier(relation),filt,sql.SQL(",").join(map(sql.Identifier,keys)))
    stream=io.BytesIO()
    cur.copy_expert(query.as_string(cur.connection),stream)
    return hashlib.sha256(stream.getvalue()).hexdigest()


def export_bundle(args):
    target = connect_target(args.target_config)
    if target.get("target_class") != "disposable_test":
        raise ValueError("bundle export is permitted only from a disposable local-review database")
    out = pathlib.Path(args.output_dir).resolve()
    if GUARD_ROOT not in out.parents or out.exists() and any(out.iterdir()):
        raise ValueError("bundle output must be a new/empty directory under the task runtime")
    out.mkdir(parents=True, exist_ok=True)
    evidence_path=pathlib.Path(args.evidence_manifest).resolve()
    if GUARD_ROOT not in evidence_path.parents or not evidence_path.is_file():
        raise ValueError("evidence manifest must be an existing task-runtime admission manifest")
    evidence=json.loads(evidence_path.read_text())
    evidence_copy=out/"receipts"/"source-admission-bundle.json"
    evidence_copy.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(evidence_path,evidence_copy)
    portable_evidence=[]
    for section in ("verified_artifacts","source_receipts","code_artifacts"):
        for ref in evidence.get(section,[]):
            source=pathlib.Path(ref["path"])
            if sha256(source)!=ref["sha256"]: raise ValueError("source evidence changed before portable export")
            rel=f"assets/{ref['sha256']}/{source.name}"
            dest=_bundle_path(out,rel); dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists(): shutil.copyfile(source,dest)
            if sha256(dest)!=ref["sha256"]: raise ValueError("portable evidence copy hash mismatch")
            portable_evidence.append({"role":ref.get("role","code"),"path":rel,"sha256":ref["sha256"],"bytes":dest.stat().st_size})
    producer_code=[]
    for rel in CODE_FILE_PATHS:
        source=ROOT/rel; digest=sha256(source); portable=f"producer/{digest}/{pathlib.Path(rel).name}"
        dest=_bundle_path(out,portable); dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
        producer_code.append({"source_path":rel,"path":portable,"sha256":digest,"bytes":dest.stat().st_size})
    db = psycopg2.connect(host=target["host"],port=target["port"],user=target["user"],dbname=target["dbname"],connect_timeout=4)
    try:
        with db.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'; SET DateStyle TO ISO, YMD; SET IntervalStyle TO iso_8601; SET client_encoding TO 'UTF8'")
            cur.execute("""SELECT DISTINCT ON (b.input_manifest_sha256) b.ingest_id::text,b.input_manifest_sha256,b.observation_release
                FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING(ingest_id)
                WHERE b.contract_version='2.0.0' AND b.candidate_status='local_review' AND i.status='pass' AND i.contract_sha256=%s
                ORDER BY b.input_manifest_sha256,b.created_at DESC,b.ingest_id DESC""",(sha256(CONTRACT),))
            batch_meta = cur.fetchall(); ids = [r[0] for r in batch_meta]
            if not ids:
                raise ValueError("no local-review batches to export")
            if {r[2] for r in batch_meta}!={"multi-source-local-review","multi-source-refresh-local-review"}:
                raise ValueError("export requires the exact current politics/BLS and refresh batch releases")
            relations = ("reader_v2_catalog_field", "reader_batch", "reader_observation", "geography_boundary", "election_contest", "election_candidate", "election_party_result", "election_availability")
            tables = {}
            for relation in relations:
                columns, keys = _stable_columns(cur, relation)
                path = out / "tables" / (relation + ".copy")
                path.parent.mkdir(parents=True, exist_ok=True)
                literals = sql.SQL(",").join(sql.Literal(x) for x in ids)
                ingest_filter = sql.SQL("ingest_id = ANY(ARRAY[{}]::uuid[])").format(literals)
                if relation == "reader_v2_catalog_field":
                    where = sql.SQL("WHERE source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE {} UNION SELECT source_release FROM usa_atlas.election_contest WHERE {})").format(ingest_filter,ingest_filter)
                else:
                    where = sql.SQL("WHERE {}").format(ingest_filter)
                query = sql.SQL("COPY (SELECT {} FROM usa_atlas.{} {} ORDER BY {}) TO STDOUT WITH (FORMAT text, ENCODING 'UTF8')").format(
                    sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(relation), where, sql.SQL(",").join(map(sql.Identifier, keys)))
                with path.open("wb") as stream:
                    cur.copy_expert(query.as_string(db), stream)
                raw = path.read_bytes()
                tables[relation] = {"path": path.relative_to(out).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "columns": columns, "primary_key": keys, "row_count": raw.count(b"\n")}
            # The selected v1 ledger rows are the only permitted legacy-table import.
            cur.execute("SELECT i.ingest_id::text,i.source,i.artifact_path,i.artifact_sha256,i.contract_sha256,i.row_count,i.started_at,i.completed_at,i.status,i.error_code FROM usa_atlas.ingest_run i WHERE i.ingest_id=ANY(%s::uuid[]) ORDER BY i.ingest_id", (ids,))
            ledger_rows = [list(row) for row in cur.fetchall()]
            meta_by_id={r[0]:r[1] for r in batch_meta}
            ledger=[]
            for row in ledger_rows:
                ingest_id=row[0]
                if row[4]!=sha256(CONTRACT) or row[8]!="pass": raise ValueError("local-review ingest ledger is not bound to the current passing contract")
                row[6]=row[6].astimezone(timezone.utc).isoformat()
                row[7]=row[7].astimezone(timezone.utc).isoformat() if row[7] else None
                counts={}; digests={}
                for relation in RELATIONS:
                    cur.execute(sql.SQL("SELECT count(*) FROM usa_atlas.{} WHERE ingest_id=%s::uuid").format(sql.Identifier(relation)),(ingest_id,)) if relation!="reader_v2_catalog_field" else None
                    if relation=="reader_v2_catalog_field":
                        cur.execute("SELECT count(*) FROM usa_atlas.reader_v2_catalog_field WHERE source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=%s::uuid UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=%s::uuid)",(ingest_id,ingest_id))
                    counts[relation]=cur.fetchone()[0]
                    digests[relation]=_relation_digest(cur,relation,ingest_id)
                row[2]="reader-v2-bundle://"+row[3]
                ledger.append({"ledger":row,"input_manifest_sha256":meta_by_id[ingest_id],"table_counts":counts,"table_digests":digests})
        if not ledger:
            raise ValueError("local-review ingest ledger is not bound to the current passing contract")
        manifest = {"format":"usa_atlas_reader_v2_portable_stage_bundle", "bundle_version":1,
                    "candidate_status":"local_review", "contract_sha256":sha256(CONTRACT),
                    "contract_version":"2.0.0", "schema_fingerprint":json.loads(CONTRACT.read_text())["schema_fingerprint"],
                    "source_target_id":target["target_id"], "ingests":ledger, "tables":tables,
                    "evidence_manifest":{"path":"receipts/source-admission-bundle.json","sha256":sha256(evidence_copy)},
                    "portable_evidence":portable_evidence,
                    "producer_code":producer_code,
                    "schema":{"path":"schema.sql","sha256":sha256(ROOT/"database/reader/v2/schema.sql")}}
        shutil.copyfile(ROOT/"database/reader/v2/schema.sql",out/"schema.sql")
        manifest["manifest_sha256"] = hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        (out/"bundle.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
        print(json.dumps({"status":"exported","bundle":str(out),"ingests":len(ids),"relations":len(tables),"manifest_sha256":manifest["manifest_sha256"]},indent=2))
    finally:
        db.close()


def _read_portable_bundle(bundle_dir):
    root = pathlib.Path(bundle_dir).resolve()
    manifest_path = _bundle_path(root,"bundle.json")
    data=json.loads(manifest_path.read_text())
    claimed=data.pop("manifest_sha256",None)
    computed=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    data["manifest_sha256"]=claimed
    if claimed!=computed or data.get("format")!="usa_atlas_reader_v2_portable_stage_bundle" or data.get("contract_version")!="2.0.0":
        raise ValueError("portable bundle identity or manifest digest is invalid")
    contract=json.loads(CONTRACT.read_text())
    if data.get("contract_sha256")!=sha256(CONTRACT) or data.get("schema_fingerprint")!=contract.get("schema_fingerprint"):
        raise ValueError("portable bundle is bound to another reader contract")
    schema=_bundle_path(root,data["schema"]["path"])
    if sha256(schema)!=data["schema"]["sha256"]:
        raise ValueError("portable additive schema bytes do not match the bundle")
    for relation,ref in data["tables"].items():
        path=_bundle_path(root,ref["path"])
        if sha256(path)!=ref["sha256"] or path.stat().st_size!=ref["bytes"] or path.read_bytes().count(b"\n")!=ref["row_count"]:
            raise ValueError("portable COPY payload does not match its bound hash/count")
    evidence=_bundle_path(root,data["evidence_manifest"]["path"])
    if sha256(evidence)!=data["evidence_manifest"]["sha256"]:
        raise ValueError("opaque source evidence manifest changed")
    for ref in data.get("portable_evidence",[]):
        path=_bundle_path(root,ref["path"])
        if sha256(path)!=ref["sha256"] or path.stat().st_size!=ref["bytes"]:
            raise ValueError("portable source/prepared/code receipt failed byte identity")
    evidence_data=json.loads(evidence.read_text())
    expected_hashes={ref.get("sha256") for section in ("verified_artifacts","source_receipts","code_artifacts") for ref in evidence_data.get(section,[])}
    if expected_hashes != {ref.get("sha256") for ref in data.get("portable_evidence",[])}:
        raise ValueError("portable bundle is missing one or more source/prepared/code evidence bytes")
    if evidence_data.get("blockers") or not evidence_data.get("production_eligible"):
        raise ValueError("source-review evidence is not production eligible")
    house=evidence_data.get("house_source_identity",{})
    raw_ref=next((ref for ref in data.get("portable_evidence",[]) if ref.get("sha256")==house.get("raw_source_sha256")),None)
    metadata_ref=next((ref for ref in data.get("portable_evidence",[]) if ref.get("sha256")==house.get("official_metadata_sha256")),None)
    if not raw_ref or not metadata_ref:
        raise ValueError("portable House raw source or official metadata is absent")
    house_proof=verify_house_identity(_bundle_path(root,raw_ref["path"]),_bundle_path(root,metadata_ref["path"]))
    if house_proof.get("original_sha256")!=house.get("reconstructed_sha256") or house_proof.get("status")!="official_original_identity_verified":
        raise ValueError("portable House identity proof failed")
    if {ref.get("source_path") for ref in data.get("producer_code",[])} != set(CODE_FILE_PATHS):
        raise ValueError("bundle does not contain the complete versioned producer code set")
    for ref in data.get("producer_code",[]):
        path=_bundle_path(root,ref["path"])
        if sha256(path)!=ref["sha256"] or path.stat().st_size!=ref["bytes"]:
            raise ValueError("portable producer source file failed byte identity")
        if ref["source_path"] in ("database/reader/v2/admission.py","database/reader/v2/contract.json","database/reader/v2/schema.sql") and sha256(ROOT/ref["source_path"])!=ref["sha256"]:
            raise ValueError("stage runtime differs from the frozen portable bundle implementation")
    return root,data


def stage_bundle(args):
    root,bundle=_read_portable_bundle(args.bundle_dir)
    target=connect_target(args.target_config)
    receipt_path=pathlib.Path(args.review_receipt).resolve() if args.review_receipt else None
    if args.apply:
        if not target.get("write_enabled") or target.get("target_class") not in ("disposable_test","production"):
            raise ValueError("stage apply requires an explicitly write-enabled target")
        if not receipt_path or GUARD_ROOT not in receipt_path.parents:
            raise ValueError("stage --apply requires a bundle-bound review receipt")
        receipt=json.loads(receipt_path.read_text())
        if (receipt.get("decision")!="stage" or receipt.get("bundle_sha256")!=bundle["manifest_sha256"] or receipt.get("target_id")!=target["target_id"] or receipt.get("contract_sha256")!=bundle["contract_sha256"] or not receipt.get("reviewer")):
            raise ValueError("stage receipt does not authorize this exact bundle, contract, and target")
        try: expiry=datetime.fromisoformat(receipt["expires_at"].replace("Z","+00:00"))
        except (KeyError,ValueError) as error: raise ValueError("stage receipt expiry is malformed") from error
        if expiry<=datetime.now(timezone.utc): raise ValueError("stage receipt has expired")
    else:
        print(json.dumps({"status":"dry_run","action":"stage","target":target["target_id"],"bundle_sha256":bundle["manifest_sha256"],"mutated":False},indent=2)); return
    if target.get("target_class")=="production" and target.get("database")!="usa_atlas":
        raise ValueError("production target does not match the declared production database")
    db=psycopg2.connect(host=target["host"],port=target["port"],user=target["user"],dbname=target["dbname"],connect_timeout=4)
    try:
        with db.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='180s'; SET LOCAL TIME ZONE 'UTC'; SET LOCAL DateStyle TO ISO, YMD; SET LOCAL IntervalStyle TO iso_8601; SET LOCAL client_encoding TO 'UTF8'")
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)",(ADVISORY_LOCK,))
            if not cur.fetchone()[0]: raise ValueError("reader-v2 stage advisory lock is busy")
            cur.execute(_bundle_path(root,bundle["schema"]["path"]).read_text())
            for batch in bundle["ingests"]:
                row=batch["ledger"]
                if row[8]!="pass": raise ValueError("portable bundle ingest ledger is not passing")
                cur.execute("INSERT INTO usa_atlas.ingest_run (ingest_id,source,artifact_path,artifact_sha256,contract_sha256,row_count,started_at,completed_at,status,error_code) VALUES (%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s)",row)
            order=("reader_v2_catalog_field","reader_batch","reader_observation","geography_boundary","election_contest","election_candidate","election_party_result","election_availability")
            ingest_ids=[batch["ledger"][0] for batch in bundle["ingests"]]
            id_literals=sql.SQL(",").join(sql.Literal(x) for x in ingest_ids)
            filter_sql=sql.SQL("ingest_id = ANY(ARRAY[{}]::uuid[])").format(id_literals)
            for relation in order:
                ref=bundle["tables"][relation]; path=_bundle_path(root,ref["path"])
                cols=sql.SQL(",").join(map(sql.Identifier,ref["columns"]))
                with path.open("rb") as stream:
                    cur.copy_expert(sql.SQL("COPY usa_atlas.{} ({}) FROM STDIN WITH (FORMAT text, ENCODING 'UTF8')").format(sql.Identifier(relation),cols).as_string(db),stream)
            for relation in order:
                ref=bundle["tables"][relation]; cols=sql.SQL(",").join(map(sql.Identifier,ref["columns"]))
                # Compare current full relation rows by exporting the exact inserted rows back to canonical COPY.
                if relation=="reader_v2_catalog_field":
                    filt=sql.SQL("source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE {} UNION SELECT source_release FROM usa_atlas.election_contest WHERE {})").format(filter_sql,filter_sql)
                else: filt=filter_sql
                query=sql.SQL("COPY (SELECT {} FROM usa_atlas.{} WHERE {} ORDER BY {}) TO STDOUT WITH (FORMAT text, ENCODING 'UTF8')").format(cols,sql.Identifier(relation),filt,sql.SQL(",").join(map(sql.Identifier,ref["primary_key"])))
                import io
                actual=io.BytesIO(); cur.copy_expert(query.as_string(db),actual)
                # Hash only package rows after staging; package currently carries a complete v2 snapshot.
                if hashlib.sha256(actual.getvalue()).hexdigest()!=ref["sha256"]:
                    raise ValueError("staged relation content differs from portable canonical digest: "+relation)
        db.commit()
        print(json.dumps({"status":"staged_local_review","target":target["target_id"],"bundle_sha256":bundle["manifest_sha256"],"ingest_batches":len(bundle["ingests"]),"mutated":True},indent=2))
    except Exception:
        db.rollback(); raise
    finally: db.close()


def read_manifest(path):
    ref = file_ref(path)
    return json.loads(pathlib.Path(path).read_text()), ref


def collect_receipts(node, role, found):
    if isinstance(node, dict):
        if node.get("raw_source_path") and node.get("raw_source_sha256"):
            ref=file_ref(node["raw_source_path"],node["raw_source_sha256"])
            found.append({"role":role,"source_id":node.get("source_release") or node.get("sourceId"),**ref})
        if node.get("path") and node.get("sha256") and node.get("sourceId"):
            ref=file_ref(node["path"],node["sha256"])
            found.append({"role":role,"source_id":node.get("sourceId"),**ref})
        if node.get("path") and node.get("prepared_sha256"):
            ref=file_ref(node["path"],node["prepared_sha256"])
            found.append({"role":role,"source_id":node.get("source_release"),**ref})
        for value in node.values(): collect_receipts(value,role,found)
    elif isinstance(node,list):
        for value in node: collect_receipts(value,role,found)


def connect_target(config_path):
    config_path = pathlib.Path(config_path).resolve()
    if GUARD_ROOT not in config_path.parents:
        raise ValueError("target config must be inside the approved task runtime")
    config = json.loads(config_path.read_text())
    policy = json.loads(TARGET_POLICY.read_text())
    target = policy["targets"].get(config.get("target_id"))
    database_match=(config.get("dbname")==target.get("database") if target else False)
    if target and target.get("database_prefix"):
        database_match=config.get("dbname","").startswith(target["database_prefix"])
    if not target or config.get("target_class") != target["class"] or not database_match:
        raise ValueError("target is not declared in the committed v2 target policy")
    if config.get("reader_role") != target["reader_role"]:
        raise ValueError("target reader role differs from the declared policy")
    if target["class"] == "disposable_test":
        if not str(config.get("host", "")).startswith(target["host_prefix"]):
            raise ValueError("disposable target must use the approved task socket")
    elif not config.get("host") or not config.get("port"):
        raise ValueError("production target requires explicit operator runtime host/port")
    for key in ("host", "port", "user", "dbname"):
        if key not in config:
            raise ValueError("target config is missing required connection identity")
    return config


def count_ingests(config, expected_manifest_hashes, contract_sha256):
    db = psycopg2.connect(host=config["host"], port=config["port"], user=config["user"],
                          dbname=config["dbname"], connect_timeout=4)
    try:
        with db.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("""SELECT b.ingest_id::text,b.contract_version,b.observation_release,
                b.input_manifest_sha256,i.status,i.artifact_sha256,i.contract_sha256,i.row_count,
                (SELECT count(*) FROM usa_atlas.reader_observation o WHERE o.ingest_id=b.ingest_id),
                (SELECT count(*) FROM usa_atlas.geography_boundary g WHERE g.ingest_id=b.ingest_id),
                (SELECT count(*) FROM usa_atlas.election_contest c WHERE c.ingest_id=b.ingest_id),
                (SELECT count(*) FROM usa_atlas.election_candidate c WHERE c.ingest_id=b.ingest_id),
                (SELECT count(*) FROM usa_atlas.election_party_result p WHERE p.ingest_id=b.ingest_id),
                (SELECT count(*) FROM usa_atlas.election_availability a WHERE a.ingest_id=b.ingest_id)
                FROM (SELECT DISTINCT ON (b.input_manifest_sha256) b.*
                      FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING(ingest_id)
                      WHERE b.contract_version='2.0.0' AND b.candidate_status='local_review' AND i.status='pass'
                        AND b.input_manifest_sha256=ANY(%s::character(64)[]) AND i.contract_sha256=%s
                      ORDER BY b.input_manifest_sha256,b.created_at DESC,b.ingest_id DESC) b
                JOIN usa_atlas.ingest_run i USING(ingest_id)
                ORDER BY b.created_at,b.ingest_id""",(expected_manifest_hashes,contract_sha256))
            rows = cur.fetchall()
        result=[]
        with db.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'; SET DateStyle TO ISO, YMD; SET IntervalStyle TO iso_8601; SET client_encoding TO 'UTF8'")
            for r in rows:
                item={"ingest_id":r[0],"contract_version":r[1],"observation_release":r[2],
                 "input_manifest_sha256":r[3],"ingest_status":r[4],"artifact_sha256":r[5],
                 "contract_sha256":r[6],"row_count":r[7],
                 "table_counts":{"reader_observation":r[8],"geography_boundary":r[9],
                    "election_contest":r[10],"election_candidate":r[11],
                    "election_party_result":r[12],"election_availability":r[13]}}
                item["table_digests"]={relation:_relation_digest(cur,relation,r[0]) for relation in RELATIONS}
                result.append(item)
        return result
    finally:
        db.close()


def prepare(args):
    politics, politics_ref = read_manifest(args.politics_manifest)
    refresh, refresh_ref = read_manifest(args.refresh_manifest)
    bls, bls_ref = read_manifest(args.bls_manifest)
    contract = json.loads(CONTRACT.read_text())
    contract_ref = file_ref(CONTRACT)
    if contract.get("format") != "usa_atlas_reader_contract" or contract.get("version") != "2.0.0":
        raise ValueError("formal v2 contract identity is missing")
    artifacts = [politics_ref, refresh_ref, bls_ref, contract_ref]
    source_receipts=[]
    collect_receipts(politics.get("sources",{}),"politics_source",source_receipts)
    collect_receipts(bls,"bls_source",source_receipts)
    for source_id,item in refresh.get("verified_raw_sources",{}).items():
        source_receipts.append({"role":"refresh_source","source_id":source_id,
                                **file_ref(item["path"],item["sha256"])})
    output_roles = (("politics", politics.get("outputs", {}).values()),
                    ("refresh", [refresh.get("output", {})]),
                    ("bls", [bls.get("output", {})]))
    for role, outputs in output_roles:
        for item in outputs:
            if not item or not item.get("path") or not item.get("sha256"):
                continue
            ref = file_ref(item["path"], item["sha256"])
            artifacts.append({"role":role, **ref, "rows":item.get("rows")})
    house = politics.get("sources", {}).get("elections", {}).get("house", {})
    identity_meta = politics.get("house_identity_metadata", {})
    identity_path = identity_meta.get("path")
    if not identity_path or not pathlib.Path(identity_path).is_file():
        raise ValueError("pinned official House metadata artifact is missing from politics inventory")
    if sha256(identity_path) != identity_meta.get("sha256"):
        raise ValueError("pinned official House metadata artifact changed")
    proof = verify_house_identity(house.get("raw_source_path", ""), identity_path)
    if proof != identity_meta.get("proof"):
        raise ValueError("House source identity proof no longer matches its deterministic reconstruction")
    source_receipts.append({"role":"house_official_metadata","source_id":"dataverse-IG0UN2-v15",
                            **file_ref(identity_path,identity_meta["sha256"])})
    code_artifacts=[{"path":str((ROOT/rel).resolve()),"sha256":sha256(ROOT/rel),"bytes":(ROOT/rel).stat().st_size} for rel in CODE_FILE_PATHS]
    blockers=[]
    if not house.get("production_eligible") or proof.get("status") != "official_original_identity_verified":
        blockers.append("House MEDSL official v15 byte identity did not pass executable verification")
    if politics.get("candidate_status") != "local_review_not_admitted":
        blockers.append("politics input is not a local-review candidate bundle")
    if refresh.get("candidate_status") != "local_review_not_admitted":
        blockers.append("refresh input is not a local-review candidate bundle")
    if bls.get("candidate_status") not in ("local_review_not_admitted", "local_review"):
        blockers.append("BLS input is not a local-review candidate bundle")
    target = connect_target(args.target_config)
    expected_manifest_hashes=[politics_ref["sha256"],refresh_ref["sha256"]]
    ingests = count_ingests(target,expected_manifest_hashes,contract_ref["sha256"])
    if not ingests:
        blockers.append("target database has no passing v2 batches bound to exact politics/refresh manifests and current contract hash")
    releases={batch["observation_release"] for batch in ingests}
    if releases!={"multi-source-local-review","multi-source-refresh-local-review"}:
        blockers.append("target snapshot does not contain exactly the current politics/BLS and refresh batches")
    for batch in ingests:
        if batch["contract_sha256"] != contract_ref["sha256"]:
            blockers.append("one or more loaded batches reference a different reader contract hash")
            break
    result={
        "format":"usa_atlas_reader_v2_admission_bundle","bundle_version":1,
        "contract_id":contract["contract_id"],"contract_version":contract["version"],
        "contract_sha256":contract_ref["sha256"],"schema_fingerprint":contract["schema_fingerprint"],
        "candidate_status":"local_review_not_admitted","production_eligible":not blockers,
        "admission_status":"blocked" if blockers else "ready_for_independent_review",
        "prepared_at":datetime.now(timezone.utc).isoformat(),
        "source_inventories":{"politics":politics_ref,"refresh":refresh_ref,"bls":bls_ref},
        "verified_artifacts":artifacts,"source_receipts":source_receipts,
        "code_artifacts":code_artifacts,"ingests":ingests,
        "expected_input_manifest_sha256s":expected_manifest_hashes,
        "completeness":{"politics_counts":politics.get("counts"),
            "refresh_observation_rows":refresh.get("output",{}).get("rows"),
            "bls_observation_rows":bls.get("normalized_row_count"),
            "bls_source_gap_rows":bls.get("missingness_row_count"),
            "source_gaps_preserved":True},
        "source_quality":{"politics_source_status":politics.get("source_status"),
            "house_source_identity_verified":proof.get("status") == "official_original_identity_verified",
            "house_identity_evidence":proof,
            "president_unspecified_contests_quarantined":politics.get("counts",{}).get("president",{}).get("unspecified_mode_contests")},
        "blockers":blockers,
        "house_source_identity":{"raw_source_path":house["raw_source_path"],
            "raw_source_sha256":house["raw_source_sha256"],
            "official_metadata_path":identity_path,"official_metadata_sha256":identity_meta["sha256"],
            "reconstructed_sha256":proof["original_sha256"]},
        "admission_filter":contract["admission_filter"],
        "additional_reader_filter":contract["additional_reader_filter"],
    }
    out=pathlib.Path(args.output_dir).resolve()
    if GUARD_ROOT not in out.parents:
        raise ValueError("admission bundle output must be inside the approved task runtime")
    out.mkdir(parents=True,exist_ok=True)
    bundle=out/"admission-bundle.json"
    bundle.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    digest=sha256(bundle)
    (out/"admission-bundle.sha256").write_text(digest+"  admission-bundle.json\n")
    print(json.dumps({"status":result["admission_status"],"bundle":str(bundle),"sha256":digest,
                      "blockers":blockers,"ingest_batches":len(ingests)},indent=2))


def validate_bundle(path):
    path=pathlib.Path(path).resolve()
    if GUARD_ROOT not in path.parents:
        raise ValueError("admission bundle must be under the approved task runtime")
    data=json.loads(path.read_text())
    if data.get("format")=="usa_atlas_reader_v2_portable_stage_bundle":
        root,portable=_read_portable_bundle(path.parent)
        evidence=json.loads(_bundle_path(root,portable["evidence_manifest"]["path"]).read_text())
        contract=json.loads(CONTRACT.read_text())
        if (portable["contract_sha256"]!=sha256(CONTRACT) or portable["schema_fingerprint"]!=contract["schema_fingerprint"] or
                contract.get("admission_filter")!="usa_atlas.ingest_run.status = 'pass'" or
                contract.get("additional_reader_filter")!="usa_atlas.reader_batch.candidate_status = 'admitted'"):
            raise ValueError("portable bundle does not match the current reader contract and access gates")
        ingests=[]
        for item in portable["ingests"]:
            row=item["ledger"]
            if row[8]!="pass" or row[4]!=portable["contract_sha256"]:
                raise ValueError("portable ledger row is not a current passing v2 ingest")
            ingests.append({"ingest_id":row[0],"artifact_sha256":row[3],"contract_sha256":row[4],
                "row_count":row[5],"input_manifest_sha256":item["input_manifest_sha256"],
                "table_counts":item["table_counts"],"table_digests":item["table_digests"]})
        return {"format":"usa_atlas_reader_v2_admission_bundle","contract_id":contract["contract_id"],
            "contract_version":"2.0.0","contract_sha256":portable["contract_sha256"],
            "schema_fingerprint":portable["schema_fingerprint"],"candidate_status":"local_review_not_admitted",
            "production_eligible":True,"blockers":[],"ingests":ingests,
            "expected_input_manifest_sha256s":sorted({x["input_manifest_sha256"] for x in ingests}),
            "source_evidence_manifest_sha256":portable["evidence_manifest"]["sha256"]},sha256(path)
    if data.get("format")!="usa_atlas_reader_v2_admission_bundle" or data.get("contract_version")!="2.0.0":
        raise ValueError("admission bundle contract identity is invalid")
    contract=json.loads(CONTRACT.read_text())
    if (data.get("contract_id")!=contract.get("contract_id") or data.get("contract_sha256")!=sha256(CONTRACT) or
            data.get("schema_fingerprint")!=contract.get("schema_fingerprint") or
            contract.get("admission_filter")!="usa_atlas.ingest_run.status = 'pass'" or
            contract.get("additional_reader_filter")!="usa_atlas.reader_batch.candidate_status = 'admitted'" or
            data.get("candidate_status")!="local_review_not_admitted"):
        raise ValueError("bundle does not match the current standard contract identity and both reader gates")
    for ref in data.get("verified_artifacts",[]):
        if not pathlib.Path(ref["path"]).is_file() or sha256(ref["path"])!=ref["sha256"]:
            raise ValueError("one or more bound source/prepared/contract artifacts changed")
    for ref in data.get("source_receipts",[]):
        if not pathlib.Path(ref["path"]).is_file() or sha256(ref["path"])!=ref["sha256"]:
            raise ValueError("one or more bound source receipts changed")
    for ref in data.get("code_artifacts",[]):
        if not pathlib.Path(ref["path"]).is_file() or sha256(ref["path"])!=ref["sha256"]:
            raise ValueError("one or more bound producer code artifacts changed")
    expected_code_paths={str((ROOT/rel).resolve()) for rel in CODE_FILE_PATHS}
    if {ref["path"] for ref in data.get("code_artifacts",[])} != expected_code_paths:
        raise ValueError("bundle does not bind the complete producer contract/code artifact set")
    if not {ref.get("role") for ref in data.get("verified_artifacts",[])} >= {"politics","refresh","bls"}:
        raise ValueError("bundle does not bind prepared outputs for politics, refresh, and BLS")
    house = data["house_source_identity"]
    if sha256(house["raw_source_path"]) != house["raw_source_sha256"] or sha256(house["official_metadata_path"]) != house["official_metadata_sha256"]:
        raise ValueError("House source or official metadata changed after bundle preparation")
    evidence=verify_house_identity(house["raw_source_path"],house["official_metadata_path"])
    if evidence["original_sha256"] != house["reconstructed_sha256"] or not data.get("source_quality",{}).get("house_source_identity_verified"):
        raise ValueError("executable House source identity proof failed")
    if data.get("blockers") or not data.get("production_eligible"):
        raise ValueError("admission bundle is blocked by unresolved source/readiness gates")
    return data,sha256(path)


def apply_action(args, action):
    target=connect_target(args.target_config)
    bundle,bundle_sha=validate_bundle(args.bundle)
    receipt_path=pathlib.Path(args.review_receipt).resolve() if args.review_receipt else None
    if not args.apply:
        print(json.dumps({"status":"dry_run","action":action,"target":target["target_id"],
                          "bundle_sha256":bundle_sha,"expected_batches":len(bundle["ingests"]),"mutated":False},indent=2)); return
    if not target.get("write_enabled"):
        raise ValueError("target config does not explicitly enable this write action")
    if not receipt_path or GUARD_ROOT not in receipt_path.parents:
        raise ValueError("--apply requires a bundle-bound review receipt under the approved task runtime")
    receipt=json.loads(receipt_path.read_text())
    expected_decision="approved" if action=="admit" else "revoke"
    if (receipt.get("decision")!=expected_decision or receipt.get("bundle_sha256")!=bundle_sha or
            receipt.get("contract_sha256")!=bundle["contract_sha256"] or receipt.get("target_id")!=target["target_id"] or
            not receipt.get("reviewer") or not receipt.get("expires_at")):
        raise ValueError("review receipt does not authorize this exact action, bundle, contract and target")
    try:
        expiry=datetime.fromisoformat(receipt["expires_at"].replace("Z","+00:00"))
    except ValueError as error:
        raise ValueError("review receipt expiry is malformed") from error
    if expiry <= datetime.now(timezone.utc):
        raise ValueError("review receipt has expired")

    db=psycopg2.connect(host=target["host"],port=target["port"],user=target["user"],dbname=target["dbname"],connect_timeout=4)
    try:
        with db.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='120s'; SET LOCAL TIME ZONE 'UTC'; SET LOCAL DateStyle TO ISO, YMD; SET LOCAL IntervalStyle TO iso_8601; SET LOCAL client_encoding TO 'UTF8'")
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)",(ADVISORY_LOCK,))
            if not cur.fetchone()[0]:
                raise ValueError("reader-v2 admission advisory lock is busy")
            expected_batch_status="local_review" if action=="admit" else "admitted"
            cur.execute("""SELECT DISTINCT ON (b.input_manifest_sha256) b.ingest_id::text
                FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING(ingest_id)
                WHERE b.contract_version='2.0.0' AND b.candidate_status=%s AND i.status='pass'
                  AND b.input_manifest_sha256=ANY(%s::character(64)[]) AND i.contract_sha256=%s
                ORDER BY b.input_manifest_sha256,b.created_at DESC,b.ingest_id DESC""",
                (expected_batch_status,bundle["expected_input_manifest_sha256s"],bundle["contract_sha256"]))
            current_ids=sorted(row[0] for row in cur.fetchall())
            if current_ids != sorted(batch["ingest_id"] for batch in bundle["ingests"]):
                raise ValueError("latest passing batch set for the bound manifests changed after bundle preparation")
            for batch in bundle["ingests"]:
                cur.execute("""SELECT i.status,i.artifact_sha256,i.contract_sha256,i.row_count,b.candidate_status,
                    b.input_manifest_sha256 FROM usa_atlas.ingest_run i JOIN usa_atlas.reader_batch b USING(ingest_id)
                    WHERE i.ingest_id=%s::uuid FOR UPDATE OF i,b""",(batch["ingest_id"],))
                found=cur.fetchone()
                if not found:
                    raise ValueError("admission batch disappeared from target database")
                i_status,artifact_sha,contract_sha,row_count,b_status,input_sha=found
                wanted="local_review" if action=="admit" else "admitted"
                if (i_status!="pass" or artifact_sha!=batch["artifact_sha256"] or
                        contract_sha!=bundle["contract_sha256"] or row_count!=batch["row_count"] or
                        b_status!=wanted or input_sha!=batch["input_manifest_sha256"]):
                    raise ValueError("target ingest ledger differs from hash-bound admission snapshot")
                for relation,expected in batch["table_counts"].items():
                    if relation=="reader_v2_catalog_field":
                        cur.execute("SELECT count(*) FROM usa_atlas.reader_v2_catalog_field WHERE source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=%s::uuid UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=%s::uuid)",(batch["ingest_id"],batch["ingest_id"]))
                    else:
                        cur.execute(sql.SQL("SELECT count(*) FROM usa_atlas.{} WHERE ingest_id=%s::uuid").format(sql.Identifier(relation)),(batch["ingest_id"],))
                    if cur.fetchone()[0]!=expected:
                        raise ValueError("target v2 relation count differs from admission bundle")
                if set(batch.get("table_digests",{}))!=set(RELATIONS):
                    raise ValueError("admission bundle is missing canonical relation content digests")
                for relation,expected_digest in batch["table_digests"].items():
                    if _relation_digest(cur,relation,batch["ingest_id"])!=expected_digest:
                        raise ValueError("target relation content differs from the reviewed canonical digest: "+relation)
                cur.execute("""SELECT count(*) FROM usa_atlas.reader_observation o WHERE o.ingest_id=%s::uuid AND
                    ((o.period_kind='monthly' AND (o.period_month NOT BETWEEN 1 AND 12 OR o.period_start_year<>o.period_year OR o.period_end_year<>o.period_year)) OR
                     (o.period_kind='annual' AND (o.period_month IS NOT NULL OR o.period_start_year<>o.period_year OR o.period_end_year<>o.period_year)) OR
                     (o.period_kind='multi_year' AND (o.period_month IS NOT NULL OR o.period_start_year>=o.period_end_year)) OR
                     (o.quality_status='observed' AND (o.value IS NULL OR o.source_value_status<>'observed' OR o.geography_mapping_status<>'mapped')) OR
                     (o.quality_status IN ('missing','suppressed','invalid','no_election') AND o.value IS NOT NULL) OR
                     (o.geo_type='congressional_district' AND (o.state_fips IS NULL OR o.district_code IS NULL OR o.boundary_vintage IS NULL OR o.congress_session IS NULL)))""",(batch["ingest_id"],))
                if cur.fetchone()[0]:
                    raise ValueError("reader-v2 observation period, quality, or geography invariant failed")
                expected_catalog_status="local_review" if action=="admit" else "admitted"
                cur.execute("""SELECT count(*) FROM usa_atlas.reader_v2_catalog_field cf WHERE cf.candidate_status<>%s
                    AND cf.source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=%s::uuid
                      UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=%s::uuid)""",
                    (expected_catalog_status,batch["ingest_id"],batch["ingest_id"]))
                if cur.fetchone()[0]:
                    raise ValueError("versioned v2 catalog metadata is not in local-review state")
            if action=="admit":
                cur.execute("UPDATE usa_atlas.reader_batch SET candidate_status='admitted' WHERE ingest_id=ANY(%s::uuid[])",[ [x["ingest_id"] for x in bundle["ingests"]] ])
                cur.execute("""UPDATE usa_atlas.reader_v2_catalog_field SET candidate_status='admitted'
                    WHERE source_release IN (
                      SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=ANY(%s::uuid[])
                      UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=ANY(%s::uuid[]))""",
                    ([x["ingest_id"] for x in bundle["ingests"]],[x["ingest_id"] for x in bundle["ingests"]]))
            else:
                cur.execute("UPDATE usa_atlas.reader_batch SET candidate_status='local_review' WHERE ingest_id=ANY(%s::uuid[])",[ [x["ingest_id"] for x in bundle["ingests"]] ])
                ids=[x["ingest_id"] for x in bundle["ingests"]]
                cur.execute("""UPDATE usa_atlas.reader_v2_catalog_field cf SET candidate_status='local_review'
                    WHERE cf.source_release IN (SELECT source_release FROM usa_atlas.reader_observation WHERE ingest_id=ANY(%s::uuid[])
                      UNION SELECT source_release FROM usa_atlas.election_contest WHERE ingest_id=ANY(%s::uuid[]))
                    AND NOT EXISTS (
                      SELECT 1 FROM usa_atlas.reader_batch b JOIN usa_atlas.ingest_run i USING(ingest_id)
                      WHERE b.candidate_status='admitted' AND i.status='pass' AND b.ingest_id<>ALL(%s::uuid[])
                        AND (EXISTS (SELECT 1 FROM usa_atlas.reader_observation o WHERE o.ingest_id=b.ingest_id AND o.source_release=cf.source_release)
                          OR EXISTS (SELECT 1 FROM usa_atlas.election_contest c WHERE c.ingest_id=b.ingest_id AND c.source_release=cf.source_release)))""",
                    (ids,ids,ids))
            actor=receipt.get("reviewer") if receipt_path else args.actor
            reason=receipt.get("reason", "") if receipt_path else args.reason
            cur.execute("""INSERT INTO usa_atlas.reader_v2_admission_event
                (ingest_id,action,admission_bundle_sha256,contract_sha256,actor,reason)
                SELECT unnest(%s::uuid[]),%s,%s,%s,%s,%s""",
                ([x["ingest_id"] for x in bundle["ingests"]],"admitted" if action=="admit" else "revoked",
                 bundle_sha,bundle["contract_sha256"],actor,reason))
            if action=="admit":
                role=sql.Identifier(target["reader_role"])
                cur.execute(sql.SQL("GRANT USAGE ON SCHEMA usa_atlas TO {}").format(role))
                for relation in ("catalog_field","ingest_run","observation","reader_batch","reader_v2_catalog_field",
                                 "reader_observation","geography_boundary","election_contest","election_candidate",
                                 "election_party_result","election_availability","reader_v2_admission_event"):
                    cur.execute(sql.SQL("GRANT SELECT ON usa_atlas.{} TO {}").format(sql.Identifier(relation),role))
        db.commit()
        print(json.dumps({"status":"admitted" if action=="admit" else "revoked","target":target["target_id"],
                          "bundle_sha256":bundle_sha,"ingest_batches":len(bundle["ingests"]),"mutated":True},indent=2))
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="command",required=True)
    p=subs.add_parser("prepare"); p.add_argument("--politics-manifest",required=True); p.add_argument("--refresh-manifest",required=True); p.add_argument("--bls-manifest",required=True); p.add_argument("--target-config",required=True); p.add_argument("--output-dir",required=True); p.set_defaults(func=prepare)
    p=subs.add_parser("export"); p.add_argument("--target-config",required=True); p.add_argument("--evidence-manifest",required=True); p.add_argument("--output-dir",required=True); p.set_defaults(func=export_bundle)
    p=subs.add_parser("stage"); p.add_argument("--bundle-dir",required=True); p.add_argument("--target-config",required=True); p.add_argument("--review-receipt"); p.add_argument("--apply",action="store_true"); p.set_defaults(func=stage_bundle)
    for name in ("admit","revoke"):
        p=subs.add_parser(name); p.add_argument("--bundle",required=True); p.add_argument("--target-config",required=True); p.add_argument("--review-receipt"); p.add_argument("--apply",action="store_true",help="Mutate the explicitly declared database; default is dry-run."); p.add_argument("--actor",default=""); p.add_argument("--reason",default=""); p.set_defaults(func=lambda a,n=name:apply_action(a,n))
    args=parser.parse_args(); args.func(args)


if __name__=="__main__":
    try: main()
    except (OSError,ValueError,KeyError,psycopg2.Error) as e:
        print(json.dumps({"status":"blocked","error":str(e)}),file=sys.stderr); sys.exit(65)
