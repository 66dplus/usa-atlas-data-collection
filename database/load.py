#!/usr/bin/env python3
"""Admit and stream completed collector artifacts into a pinned PostgreSQL database."""

from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import parse_qsl, urlsplit


HERE = Path(__file__).resolve().parent
FULL = HERE.parent / "full"
SCHEMA = HERE / "schema.sql"
TARGET_DATABASE = "usa_atlas"
MAINTENANCE_DATABASE = "postgres"
DISK_FLOOR_BYTES = 6 * 1024**3
SCRATCH_MIN_BYTES = 256 * 1024**2
LOAD_FIXED_BYTES = 512 * 1024**2
# Generated from canonical_catalog_document() after applying this schema to fresh PG16.
EXPECTED_SCHEMA_CATALOG_SHA256 = "9a9b11d1266ec0e16e517b7eed08a2d069d8b2979880dd3d870308799f085f10"

REQUIRED_FIELDS = {
    "geo_id", "geo_type", "year", "field_id", "catalog_field_id", "value", "unit",
    "source", "source_release", "source_url", "methodology_note", "retrieved_at",
}
CONTRACT_FIELDS = {
    "field_id", "catalog_label", "catalog_source", "catalog_geography", "catalog_note",
    "planned_state", "unavailable_geography", "unit", "source_release", "acquisition_mode",
    "source_selector", "source_variables", "derivation", "target_geographies",
    "rate_limit_profile", "license_status",
}
PLANNED_STATES = {
    "run_now", "blocked_access", "definition_required", "source_required", "license_required",
}
ACTIVE_PROFILES = {
    "census_acs", "bea_rpp", "bls_laus", "fbi_cde", "cdc_places", "irs_soi",
    "eia", "usda_fea", "epa_airdata",
}
SENSITIVE_QUERY_KEYS = {"key", "api_key", "userid", "email", "registrationkey", "app_token"}


class AdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class Admission:
    source: str
    artifact_path: Path
    artifact_relative_path: str
    artifact_sha256: str
    contract_sha256: str
    row_count: int
    contract: tuple[dict, ...]


@dataclass(frozen=True)
class StorageProjection:
    selected_artifact_bytes: int
    scratch_reserved_bytes: int
    load_reserved_bytes: int
    available_before_bytes: int
    projected_free_before_bytes: int
    available_after_scratch_bytes: int
    projected_free_for_load_bytes: int

    def as_dict(self) -> dict[str, int]:
        return {
            "selected_artifact_bytes": self.selected_artifact_bytes,
            "scratch_reserved_bytes": self.scratch_reserved_bytes,
            "load_reserved_bytes": self.load_reserved_bytes,
            "disk_floor_bytes": DISK_FLOOR_BYTES,
            "available_before_bytes": self.available_before_bytes,
            "projected_free_before_bytes": self.projected_free_before_bytes,
            "available_after_scratch_bytes": self.available_after_scratch_bytes,
            "projected_free_for_load_bytes": self.projected_free_for_load_bytes,
        }


@dataclass(frozen=True)
class LoadOutcome:
    sources: tuple[tuple[str, str], ...]
    storage: StorageProjection

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "pass",
            "database": TARGET_DATABASE,
            "sources": dict(self.sources),
            "storage": self.storage.as_dict(),
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def open_jsonl(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise AdmissionError("retrieved_at_not_text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdmissionError("retrieved_at_invalid") from error
    if parsed.tzinfo is None:
        raise AdmissionError("retrieved_at_missing_timezone")
    return parsed.astimezone(timezone.utc)


def validate_record(record: object, source: str, contract_by_id: dict[str, dict]) -> dict:
    if not isinstance(record, dict) or set(record) != REQUIRED_FIELDS:
        raise AdmissionError("record_fields_invalid")
    if record["source"] != source:
        raise AdmissionError("record_source_mismatch")
    catalog_id = record["catalog_field_id"]
    contract_row = contract_by_id.get(catalog_id)
    if contract_row is None:
        raise AdmissionError("catalog_field_unknown")
    if contract_row.get("planned_state") != "run_now":
        raise AdmissionError("catalog_field_not_runnable")
    if contract_row.get("rate_limit_profile") != source:
        raise AdmissionError("catalog_field_source_mismatch")
    if record["field_id"] != catalog_id and not str(record["field_id"]).startswith(f"{catalog_id}:"):
        raise AdmissionError("field_id_parent_mismatch")
    value = record["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AdmissionError("value_not_finite_number")
    for name in ("geo_id", "geo_type", "year", "field_id", "catalog_field_id", "unit",
                 "source", "source_release", "source_url", "methodology_note"):
        if not isinstance(record[name], str) or (name != "methodology_note" and not record[name]):
            raise AdmissionError(f"{name}_invalid")
    parsed_url = urlsplit(record["source_url"])
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise AdmissionError("source_url_invalid")
    if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed_url.query, keep_blank_values=True)):
        raise AdmissionError("source_url_contains_credential")
    parse_timestamp(record["retrieved_at"])
    return record


def artifact_path(full_dir: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise AdmissionError("artifact_path_invalid")
    root = full_dir.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise AdmissionError("artifact_path_outside_collection") from error
    return path


def validate_contract(contract: object) -> tuple[tuple[dict, ...], dict[str, dict]]:
    if not isinstance(contract, list) or len(contract) != 81:
        raise AdmissionError("contract_must_have_81_rows")
    expected_ids = {
        f"{section:02d}.{row:02d}"
        for section, count in enumerate((8, 10, 9, 9, 16, 6, 7, 9, 7), start=1)
        for row in range(1, count + 1)
    }
    contract_by_id: dict[str, dict] = {}
    state_counts = {state: 0 for state in PLANNED_STATES}
    for row in contract:
        if not isinstance(row, dict) or set(row) != CONTRACT_FIELDS:
            raise AdmissionError("contract_row_fields_invalid")
        field_id = row["field_id"]
        if not isinstance(field_id, str) or not re.fullmatch(r"[0-9]{2}\.[0-9]{2}", field_id):
            raise AdmissionError("contract_field_id_invalid")
        if field_id in contract_by_id:
            raise AdmissionError("contract_field_id_duplicate")
        state = row["planned_state"]
        if state not in PLANNED_STATES:
            raise AdmissionError("contract_planned_state_invalid")
        state_counts[state] += 1
        for name in CONTRACT_FIELDS - {"source_variables", "target_geographies"}:
            if not isinstance(row[name], str):
                raise AdmissionError(f"contract_{name}_invalid")
        for name in ("catalog_label", "catalog_source", "catalog_geography", "catalog_note",
                     "unavailable_geography", "unit", "source_release", "acquisition_mode",
                     "derivation", "rate_limit_profile", "license_status"):
            if not row[name]:
                raise AdmissionError(f"contract_{name}_empty")
        if row["unavailable_geography"] != "record_not_available":
            raise AdmissionError("contract_unavailable_geography_invalid")
        if (not isinstance(row["source_variables"], list)
                or any(not isinstance(value, str) or not value for value in row["source_variables"])):
            raise AdmissionError("contract_source_variables_invalid")
        if (not isinstance(row["target_geographies"], list) or not row["target_geographies"]
                or any(not isinstance(value, str) or not value for value in row["target_geographies"])):
            raise AdmissionError("contract_target_geographies_invalid")
        if state == "run_now":
            if row["rate_limit_profile"] not in ACTIVE_PROFILES or not row["source_selector"] \
                    or not row["source_variables"] or row["acquisition_mode"] == "disabled":
                raise AdmissionError("contract_run_now_mapping_invalid")
        elif (row["rate_limit_profile"] != "disabled" or row["acquisition_mode"] != "disabled"
              or row["source_selector"] or row["source_variables"]):
            raise AdmissionError("contract_disabled_mapping_invalid")
        contract_by_id[field_id] = row
    if set(contract_by_id) != expected_ids:
        raise AdmissionError("contract_field_ids_invalid")
    if state_counts != {
        "run_now": 46, "blocked_access": 19, "definition_required": 7,
        "source_required": 6, "license_required": 3,
    }:
        raise AdmissionError("contract_state_totals_invalid")
    return tuple(contract), contract_by_id


def preflight_sources(sources: Iterable[str], full_dir: Path = FULL) -> list[Admission]:
    manifest_path = full_dir / "state" / "run-manifest.json"
    contract_path = full_dir / "field-contract.json"
    if not manifest_path.is_file() or not contract_path.is_file():
        raise AdmissionError("manifest_or_contract_missing")
    try:
        manifest = load_json(manifest_path)
        contract, contract_by_id = validate_contract(load_json(contract_path))
    except json.JSONDecodeError as error:
        raise AdmissionError("manifest_or_contract_json_invalid") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), dict):
        raise AdmissionError("manifest_invalid")
    contract_hash = sha256_file(contract_path)
    if manifest.get("contract_sha256") != contract_hash:
        raise AdmissionError("contract_manifest_hash_mismatch")

    admissions = []
    for source in sources:
        item = manifest["sources"].get(source)
        if not isinstance(item, dict) or item.get("status") != "pass":
            raise AdmissionError(f"source_not_pass:{source}")
        artifact = item.get("normalized_artifact")
        if not isinstance(artifact, dict):
            raise AdmissionError(f"normalized_artifact_missing:{source}")
        path = artifact_path(full_dir, artifact.get("path"))
        if not path.is_file():
            raise AdmissionError(f"normalized_artifact_file_missing:{source}")
        expected_hash = artifact.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AdmissionError(f"normalized_artifact_hash_invalid:{source}")
        if sha256_file(path) != expected_hash:
            raise AdmissionError(f"normalized_artifact_hash_mismatch:{source}")
        rows = 0
        with open_jsonl(path) as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    validate_record(json.loads(line), source, contract_by_id)
                except (json.JSONDecodeError, AdmissionError) as error:
                    raise AdmissionError(f"{source}:line_{line_number}:{error}") from error
                rows += 1
        if rows != item.get("normalized_rows") or rows != artifact.get("rows"):
            raise AdmissionError(f"normalized_row_count_mismatch:{source}")
        admissions.append(Admission(
            source=source,
            artifact_path=path,
            artifact_relative_path=str(path.relative_to(full_dir.resolve())),
            artifact_sha256=expected_hash,
            contract_sha256=contract_hash,
            row_count=rows,
            contract=contract,
        ))
    if not admissions:
        raise AdmissionError("no_sources_selected")
    return admissions


def _disk_projection(admissions: list[Admission], full_dir: Path) -> tuple[int, int, int, int]:
    selected = sum(item.artifact_path.stat().st_size for item in admissions)
    scratch = max(SCRATCH_MIN_BYTES, 4 * selected)
    load_reserve = 6 * selected + LOAD_FIXED_BYTES
    available = shutil.disk_usage(full_dir).free
    projected = available - scratch - load_reserve
    if projected < DISK_FLOOR_BYTES:
        raise AdmissionError(
            f"disk_headroom_insufficient:available={available}:scratch={scratch}:"
            f"load={load_reserve}:projected={projected}:floor={DISK_FLOOR_BYTES}"
        )
    return selected, scratch, load_reserve, available


def exact_duplicate_scan(admissions: list[Admission], full_dir: Path) -> StorageProjection:
    selected, scratch, load_reserve, available_before = _disk_projection(admissions, full_dir)
    with tempfile.TemporaryDirectory(prefix=".usa-atlas-dedup-", dir=full_dir) as directory:
        database_path = Path(directory) / "keys.sqlite3"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("PRAGMA page_size=4096")
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute(f"PRAGMA max_page_count={scratch // 4096}")
            connection.execute(
                "CREATE TABLE canonical_key ("
                "geo_id TEXT NOT NULL, period TEXT NOT NULL, field_id TEXT NOT NULL, "
                "source_release TEXT NOT NULL, "
                "PRIMARY KEY (geo_id, period, field_id, source_release)) WITHOUT ROWID"
            )
            connection.execute("BEGIN")
            for admission in admissions:
                contract = {row["field_id"]: row for row in admission.contract}
                with open_jsonl(admission.artifact_path) as handle:
                    for line_number, line in enumerate(handle, start=1):
                        try:
                            record = validate_record(json.loads(line), admission.source, contract)
                            connection.execute(
                                "INSERT INTO canonical_key VALUES (?,?,?,?)",
                                (record["geo_id"], record["year"], record["field_id"],
                                 record["source_release"]),
                            )
                        except sqlite3.IntegrityError as error:
                            raise AdmissionError(
                                f"duplicate_canonical_key:{admission.source}:line_{line_number}"
                            ) from error
                        except (json.JSONDecodeError, AdmissionError) as error:
                            raise AdmissionError(
                                f"{admission.source}:line_{line_number}:{error}"
                            ) from error
                if sha256_file(admission.artifact_path) != admission.artifact_sha256:
                    raise AdmissionError(f"artifact_changed_during_admission:{admission.source}")
            connection.commit()
            if database_path.stat().st_size > scratch:
                raise AdmissionError("dedup_scratch_reservation_exceeded")
        except sqlite3.Error as error:
            raise AdmissionError(f"dedup_sqlite_failed:{error}") from error
        finally:
            connection.close()
    available_after = shutil.disk_usage(full_dir).free
    projected_for_load = available_after - load_reserve
    if projected_for_load < DISK_FLOOR_BYTES:
        raise AdmissionError(
            f"disk_headroom_after_dedup_insufficient:available={available_after}:"
            f"load={load_reserve}:projected={projected_for_load}:floor={DISK_FLOOR_BYTES}"
        )
    return StorageProjection(
        selected, scratch, load_reserve, available_before,
        available_before - scratch - load_reserve, available_after, projected_for_load,
    )


@contextmanager
def loader_lock(full_dir: Path):
    """Serialize admission/load operations that share PostgreSQL staging tables."""
    lock_path = full_dir / "state" / ".usa-atlas-load.lock"
    try:
        handle = lock_path.open("a+", encoding="utf-8")
    except OSError as error:
        raise AdmissionError(f"loader_lock_open_failed:{error}") from error
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AdmissionError("loader_lock_unavailable") from error
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def psql(arguments: list[str], *, dbname: str = TARGET_DATABASE,
         input_text: str | None = None, capture: bool = False) -> str:
    command = ["psql", "-X", "--dbname", dbname, "--set", "ON_ERROR_STOP=1", *arguments]
    result = subprocess.run(
        command, input=input_text, text=True, check=False,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "psql_failed")
    return result.stdout.strip() if capture else ""


def createdb(owner: str) -> None:
    command = [
        "createdb", "--maintenance-db", MAINTENANCE_DATABASE,
        "--owner", owner, TARGET_DATABASE,
    ]
    result = subprocess.run(command, text=True, check=False, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "createdb_failed")


def apply_schema() -> None:
    schema_hash = sha256_file(SCHEMA)
    psql(["--set", f"schema_sha256={schema_hash}", "--file", str(SCHEMA)])


def write_copy(stream, table: str, columns: tuple[str, ...], rows: Iterable[Iterable[object]]) -> None:
    stream.write(f"\\copy {table} ({','.join(columns)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')\n")
    writer = csv.writer(stream, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    stream.write("\\.\n")
    stream.flush()


CATALOG_DOCUMENT_SQL = r"""
WITH user_ns AS (
    SELECT oid, nspname, CASE WHEN pg_get_userbyid(nspowner)=current_user
        THEN '$CURRENT_ROLE' ELSE pg_get_userbyid(nspowner) END AS owner
    FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog','information_schema')
      AND nspname !~ '^pg_(toast|temp|toast_temp)'
),
document AS (
SELECT jsonb_build_object(
 'schemas', COALESCE((SELECT jsonb_agg(jsonb_build_object('name',nspname,'owner',owner)
                                      ORDER BY nspname) FROM user_ns),'[]'::jsonb),
 'extensions', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'name',e.extname,'version',e.extversion,'schema',n.nspname,'relocatable',e.extrelocatable)
        ORDER BY e.extname) FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace),'[]'::jsonb),
 'relations', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',c.relname,'kind',c.relkind,'persistence',c.relpersistence,
        'access_method',COALESCE(am.amname,''),'options',COALESCE(to_jsonb(c.reloptions),'[]'::jsonb),
        'row_security',c.relrowsecurity,'force_row_security',c.relforcerowsecurity,
        'owner',CASE WHEN pg_get_userbyid(c.relowner)=current_user THEN '$CURRENT_ROLE'
                     ELSE pg_get_userbyid(c.relowner) END)
        ORDER BY n.nspname,c.relname,c.relkind)
        FROM pg_class c JOIN user_ns n ON n.oid=c.relnamespace
        LEFT JOIN pg_am am ON am.oid=c.relam),'[]'::jsonb),
 'columns', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'relation',c.relname,'number',a.attnum,'name',a.attname,
        'type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,
        'identity',a.attidentity,'generated',a.attgenerated,
        'default',COALESCE(pg_get_expr(d.adbin,d.adrelid),''),
        'collation',COALESCE(coll.collname,'')) ORDER BY n.nspname,c.relname,a.attnum)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN user_ns n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d
          ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        LEFT JOIN pg_collation coll ON coll.oid=a.attcollation
        WHERE a.attnum>0 AND NOT a.attisdropped),'[]'::jsonb),
 'constraints', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',con.conname,'type',con.contype,
        'relation',COALESCE(c.relname,''),'definition',pg_get_constraintdef(con.oid,true))
        ORDER BY n.nspname,COALESCE(c.relname,''),con.conname)
        FROM pg_constraint con JOIN user_ns n ON n.oid=con.connamespace
        LEFT JOIN pg_class c ON c.oid=con.conrelid),'[]'::jsonb),
 'indexes', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'table',t.relname,'name',i.relname,
        'definition',pg_get_indexdef(x.indexrelid)) ORDER BY n.nspname,t.relname,i.relname)
        FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_class t ON t.oid=x.indrelid JOIN user_ns n ON n.oid=t.relnamespace),'[]'::jsonb),
 'routines', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',p.proname,'identity_args',pg_get_function_identity_arguments(p.oid),
        'kind',p.prokind,'owner',CASE WHEN pg_get_userbyid(p.proowner)=current_user
                     THEN '$CURRENT_ROLE' ELSE pg_get_userbyid(p.proowner) END,
        'definition',pg_get_functiondef(p.oid)) ORDER BY n.nspname,p.proname,pg_get_function_identity_arguments(p.oid))
        FROM pg_proc p JOIN user_ns n ON n.oid=p.pronamespace),'[]'::jsonb),
 'types', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',t.typname,'kind',t.typtype,'category',t.typcategory,
        'relation',COALESCE(c.relname,''),'base',COALESCE(format_type(t.typbasetype,NULL),''),
        'not_null',t.typnotnull,'default',COALESCE(t.typdefault,''),
        'owner',CASE WHEN pg_get_userbyid(t.typowner)=current_user THEN '$CURRENT_ROLE'
                     ELSE pg_get_userbyid(t.typowner) END) ORDER BY n.nspname,t.typname)
        FROM pg_type t JOIN user_ns n ON n.oid=t.typnamespace
        LEFT JOIN pg_class c ON c.oid=t.typrelid),'[]'::jsonb),
 'enum_labels', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'type',t.typname,'sort',e.enumsortorder,'label',e.enumlabel)
        ORDER BY n.nspname,t.typname,e.enumsortorder) FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid
        JOIN user_ns n ON n.oid=t.typnamespace),'[]'::jsonb),
 'triggers', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'table',c.relname,'name',t.tgname,'definition',pg_get_triggerdef(t.oid,true))
        ORDER BY n.nspname,c.relname,t.tgname) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN user_ns n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal),'[]'::jsonb),
 'rules', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'relation',c.relname,'name',r.rulename,'definition',pg_get_ruledef(r.oid,true))
        ORDER BY n.nspname,c.relname,r.rulename) FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class
        JOIN user_ns n ON n.oid=c.relnamespace WHERE r.rulename <> '_RETURN'),'[]'::jsonb),
 'policies', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'table',c.relname,'name',p.polname,'command',p.polcmd,
        'permissive',p.polpermissive) ORDER BY n.nspname,c.relname,p.polname)
        FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN user_ns n ON n.oid=c.relnamespace),'[]'::jsonb),
 'operators', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',o.oprname,'left',format_type(o.oprleft,NULL),
        'right',format_type(o.oprright,NULL),'result',format_type(o.oprresult,NULL))
        ORDER BY n.nspname,o.oprname,o.oprleft,o.oprright) FROM pg_operator o
        JOIN user_ns n ON n.oid=o.oprnamespace),'[]'::jsonb),
 'collations', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',c.collname,'provider',c.collprovider,'deterministic',c.collisdeterministic)
        ORDER BY n.nspname,c.collname) FROM pg_collation c JOIN user_ns n ON n.oid=c.collnamespace),'[]'::jsonb),
 'conversions', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'schema',n.nspname,'name',c.conname,'source',c.conforencoding,'dest',c.contoencoding)
        ORDER BY n.nspname,c.conname) FROM pg_conversion c JOIN user_ns n ON n.oid=c.connamespace),'[]'::jsonb),
 'event_triggers', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'name',evtname,'event',evtevent,'enabled',evtenabled) ORDER BY evtname)
        FROM pg_event_trigger),'[]'::jsonb),
 'publications', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'name',pubname,'all_tables',puballtables) ORDER BY pubname) FROM pg_publication),'[]'::jsonb)
) AS value)
SELECT value::text FROM document
"""


def canonical_catalog_document() -> str:
    return psql(["--tuples-only", "--no-align", "--command", CATALOG_DOCUMENT_SQL], capture=True)


def schema_catalog_sha256() -> str:
    return hashlib.sha256(canonical_catalog_document().encode("utf-8")).hexdigest()


def target_is_empty() -> bool:
    sql = r"""
    WITH user_ns AS (
      SELECT oid,nspname FROM pg_namespace
      WHERE nspname NOT IN ('pg_catalog','information_schema')
        AND nspname !~ '^pg_(toast|temp|toast_temp)'
    )
    SELECT NOT EXISTS (SELECT 1 FROM user_ns WHERE nspname <> 'public')
       AND NOT EXISTS (SELECT 1 FROM pg_class c JOIN user_ns n ON n.oid=c.relnamespace)
       AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN user_ns n ON n.oid=p.pronamespace)
       AND NOT EXISTS (SELECT 1 FROM pg_type t JOIN user_ns n ON n.oid=t.typnamespace)
       AND NOT EXISTS (SELECT 1 FROM pg_operator o JOIN user_ns n ON n.oid=o.oprnamespace)
       AND NOT EXISTS (SELECT 1 FROM pg_collation c JOIN user_ns n ON n.oid=c.collnamespace)
       AND NOT EXISTS (SELECT 1 FROM pg_conversion c JOIN user_ns n ON n.oid=c.connamespace)
       AND NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')
       AND NOT EXISTS (SELECT 1 FROM pg_event_trigger)
       AND NOT EXISTS (SELECT 1 FROM pg_publication)
    """
    return psql(["--tuples-only", "--no-align", "--command", sql], capture=True) == "t"


def catalog_rows(admission: Admission) -> Iterator[tuple[object, ...]]:
    for row in admission.contract:
        yield (
            row["field_id"], row["catalog_label"], row["planned_state"],
            row["rate_limit_profile"], row["source_release"],
            json.dumps(row, separators=(",", ":"), ensure_ascii=False), admission.contract_sha256,
        )


def observation_rows(admission: Admission, ingest_id: str) -> Iterator[tuple[object, ...]]:
    contract = {row["field_id"]: row for row in admission.contract}
    with open_jsonl(admission.artifact_path) as handle:
        for line in handle:
            record = validate_record(json.loads(line), admission.source, contract)
            yield (
                ingest_id, record["geo_id"], record["geo_type"], record["year"],
                record["field_id"], record["catalog_field_id"], record["value"], record["unit"],
                record["source"], record["source_release"], record["source_url"],
                record["methodology_note"], record["retrieved_at"],
            )


def artifact_already_passed(artifact_sha256: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256):
        raise AdmissionError("artifact_sha256_invalid")
    output = psql(["--tuples-only", "--no-align", "--command",
                   "SELECT EXISTS (SELECT 1 FROM usa_atlas.ingest_run "
                   f"WHERE status='pass' AND artifact_sha256='{artifact_sha256}')"], capture=True)
    return output == "t"


def load_admission(admission: Admission) -> str:
    if artifact_already_passed(admission.artifact_sha256):
        return "skipped"
    ingest_id = str(uuid.uuid4())
    command = [
        "psql", "-X", "--dbname", TARGET_DATABASE, "--set", "ON_ERROR_STOP=1",
        "--single-transaction",
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    assert process.stdin is not None
    try:
        process.stdin.write("TRUNCATE usa_atlas.catalog_field_stage, usa_atlas.observation_stage;\n")
        write_copy(
            process.stdin,
            "usa_atlas.ingest_run",
            ("ingest_id", "source", "artifact_path", "artifact_sha256", "contract_sha256",
             "row_count", "started_at", "status"),
            [(ingest_id, admission.source, admission.artifact_relative_path,
              admission.artifact_sha256, admission.contract_sha256, 0,
              datetime.now(timezone.utc).isoformat(), "loading")],
        )
        write_copy(
            process.stdin,
            "usa_atlas.catalog_field_stage",
            ("catalog_field_id", "catalog_label", "planned_state", "rate_limit_profile",
             "source_release", "contract", "contract_sha256"),
            catalog_rows(admission),
        )
        write_copy(
            process.stdin,
            "usa_atlas.observation_stage",
            ("ingest_id", "geo_id", "geo_type", "period", "field_id", "catalog_field_id",
             "value", "unit", "source", "source_release", "source_url",
             "methodology_note", "retrieved_at"),
            observation_rows(admission, ingest_id),
        )
        process.stdin.write(f"SELECT usa_atlas.finish_ingest('{ingest_id}'::uuid,{admission.row_count});\n")
        process.stdin.close()
        error = process.stderr.read() if process.stderr is not None else ""
        if process.stderr is not None:
            process.stderr.close()
        return_code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        if not process.stdin.closed:
            process.stdin.close()
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()
        raise
    if return_code:
        raise RuntimeError(error.strip() or "psql_transaction_failed")
    return "loaded"


def _json_query(sql: str) -> object:
    return json.loads(psql(["--tuples-only", "--no-align", "--command", sql], capture=True))


def database_metrics() -> dict[str, object]:
    return _json_query(r"""
    SELECT json_build_object(
      'catalog_fields',(SELECT count(*) FROM usa_atlas.catalog_field),
      'total_rows',(SELECT count(*) FROM usa_atlas.observation),
      'distinct_keys',(SELECT count(DISTINCT (geo_id,period,field_id,source_release)) FROM usa_atlas.observation),
      'duplicate_groups',(SELECT count(*) FROM (SELECT 1 FROM usa_atlas.observation
          GROUP BY geo_id,period,field_id,source_release HAVING count(*)>1) d),
      'missing_observation_provenance',(SELECT count(*) FROM usa_atlas.observation
          WHERE source IS NULL OR btrim(source)='' OR source_release IS NULL OR btrim(source_release)=''
             OR source_url IS NULL OR btrim(source_url)='' OR retrieved_at IS NULL),
      'missing_ingest_provenance',(SELECT count(*) FROM usa_atlas.ingest_run
          WHERE artifact_path IS NULL OR btrim(artifact_path)='' OR artifact_sha256 IS NULL
             OR contract_sha256 IS NULL OR started_at IS NULL OR completed_at IS NULL),
      'passed_ingests',(SELECT count(*) FROM usa_atlas.ingest_run WHERE status='pass'),
      'all_ingests',(SELECT count(*) FROM usa_atlas.ingest_run),
      'census_rows',(SELECT count(*) FROM usa_atlas.observation WHERE source='census_acs'),
      'source_counts',(SELECT COALESCE(json_object_agg(source,n ORDER BY source),'{}'::json)
          FROM (SELECT source,count(*) n FROM usa_atlas.observation GROUP BY source) s),
      'ingests',(SELECT COALESCE(json_agg(row_to_json(i) ORDER BY source,artifact_sha256),'[]'::json)
          FROM (SELECT source,artifact_path,artifact_sha256,contract_sha256,row_count,status,
                       completed_at IS NOT NULL completed
                FROM usa_atlas.ingest_run) i),
      'source_geography',(SELECT COALESCE(json_agg(row_to_json(g) ORDER BY source,geo_type),'[]'::json)
          FROM (SELECT source,geo_type,count(*) rows,count(DISTINCT geo_id) distinct_geographies
                FROM usa_atlas.observation GROUP BY source,geo_type) g)
    )
    """)


def _expected_source_counts(admissions: list[Admission]) -> dict[str, int]:
    return {item.source: item.row_count for item in admissions}


def assert_complete_state(admissions: list[Admission]) -> dict[str, object]:
    expected_schema_hash = sha256_file(SCHEMA)
    stored_schema_hash = psql([
        "--tuples-only", "--no-align", "--command",
        "SELECT schema_sha256 FROM usa_atlas.schema_metadata WHERE singleton",
    ], capture=True)
    if stored_schema_hash != expected_schema_hash:
        raise AdmissionError("target_schema_template_hash_mismatch")
    observed_catalog_hash = schema_catalog_sha256()
    if observed_catalog_hash != EXPECTED_SCHEMA_CATALOG_SHA256:
        raise AdmissionError(
            f"target_physical_schema_mismatch:observed={observed_catalog_hash}:"
            f"expected={EXPECTED_SCHEMA_CATALOG_SHA256}"
        )
    metrics = database_metrics()
    expected_counts = _expected_source_counts(admissions)
    expected_ingests = sorted(
        (a.source, a.artifact_relative_path, a.artifact_sha256, a.contract_sha256, a.row_count)
        for a in admissions
    )
    observed_ingests = sorted(
        (row["source"], row["artifact_path"], row["artifact_sha256"], row["contract_sha256"],
         int(row["row_count"]))
        for row in metrics["ingests"]
        if row["status"] == "pass" and row["completed"]
    )
    checks = {
        "catalog_fields": metrics["catalog_fields"] == 81,
        "total_rows": metrics["total_rows"] == sum(expected_counts.values()),
        "distinct_keys": metrics["total_rows"] == metrics["distinct_keys"],
        "duplicate_groups": metrics["duplicate_groups"] == 0,
        "observation_provenance": metrics["missing_observation_provenance"] == 0,
        "ingest_provenance": metrics["missing_ingest_provenance"] == 0,
        "ingest_count": metrics["passed_ingests"] == metrics["all_ingests"] == len(admissions),
        "source_counts": metrics["source_counts"] == expected_counts,
        "ingest_manifest": observed_ingests == expected_ingests,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise AdmissionError(f"target_complete_state_mismatch:{','.join(failed)}")
    return metrics


def apply_compact_lookup_index() -> None:
    """Bring a freshly bootstrapped target to the deployed lookup-index shape.

    The online production switch observed in LOOKUP-INDEX-MIGRATION.md replaced
    the bootstrap lookup index with the compact form; a new installation reaches
    the pinned catalog only after the same storage migration.
    """
    psql(["--command", """
CREATE INDEX observation_lookup_compact_idx
  ON usa_atlas.observation_data
  (catalog_field_id, geo_type, geo_id, period DESC);
DROP INDEX usa_atlas.observation_lookup_idx;
ALTER INDEX usa_atlas.observation_lookup_compact_idx
  RENAME TO observation_lookup_idx;
"""])


def ensure_target_database(admissions: list[Admission]) -> str:
    current_role, target_owner = target_identity()
    if not target_owner:
        createdb(current_role)
        apply_schema()
        apply_compact_lookup_index()
        if schema_catalog_sha256() != EXPECTED_SCHEMA_CATALOG_SHA256:
            raise AdmissionError("new_target_physical_schema_mismatch")
        return "created"
    if target_owner != current_role:
        raise AdmissionError(f"target_owner_mismatch:{target_owner}:{current_role}")
    if target_is_empty():
        apply_schema()
        apply_compact_lookup_index()
        if schema_catalog_sha256() != EXPECTED_SCHEMA_CATALOG_SHA256:
            raise AdmissionError("initialized_target_physical_schema_mismatch")
        return "initialized"
    assert_complete_state(admissions)
    return "complete"


def target_identity() -> tuple[str, str]:
    current_role = psql(["--tuples-only", "--no-align", "--command", "SELECT current_user"],
                        dbname=MAINTENANCE_DATABASE, capture=True)
    target_owner = psql([
        "--tuples-only", "--no-align", "--command",
        f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='{TARGET_DATABASE}'",
    ], dbname=MAINTENANCE_DATABASE, capture=True)
    return current_role, target_owner


def no_scan_projection(admissions: list[Admission], full_dir: Path) -> StorageProjection:
    available = shutil.disk_usage(full_dir).free
    selected = sum(item.artifact_path.stat().st_size for item in admissions)
    # shortcut: a complete target with matching passed artifact hashes already has
    # the primary-key/dedup evidence from its admitting load; no scratch index is
    # needed for a read-only idempotent rerun.
    return StorageProjection(selected, 0, 0, available, available, available, available)


def reject_pipeline_managed_target() -> None:
    """Historic exact-manifest commands cannot refresh pipeline-owned facts."""
    _, owner = target_identity()
    if not owner:
        return
    exists = psql(["--tuples-only", "--no-align", "--command",
                   "SELECT to_regclass('usa_atlas_pipeline.dataset') IS NOT NULL"], capture=True)
    if exists == "t":
        managed = psql(["--tuples-only", "--no-align", "--command",
                        "SELECT EXISTS(SELECT 1 FROM usa_atlas_pipeline.dataset)"], capture=True)
        if managed == "t":
            raise AdmissionError("pipeline_managed_target_use_auto_ingest")


def _load_database_locked(sources: list[str], full_dir: Path) -> LoadOutcome:
    reject_pipeline_managed_target()
    admissions = preflight_sources(sources, full_dir)
    current_role, target_owner = target_identity()
    if target_owner and target_owner != current_role:
        raise AdmissionError(f"target_owner_mismatch:{target_owner}:{current_role}")
    if target_owner and not target_is_empty():
        # Existing complete state is admitted read-only before the expensive
        # scratch reservation; a changed artifact still fails closed here.
        assert_complete_state(admissions)
        if all(artifact_already_passed(admission.artifact_sha256) for admission in admissions):
            return LoadOutcome(
                tuple((admission.source, "skipped") for admission in admissions),
                no_scan_projection(admissions, full_dir),
            )
    storage = exact_duplicate_scan(admissions, full_dir)
    ensure_target_database(admissions)
    results = tuple((admission.source, load_admission(admission)) for admission in admissions)
    assert_complete_state(admissions)
    return LoadOutcome(results, storage)


def load_database(sources: list[str], full_dir: Path = FULL) -> LoadOutcome:
    with loader_lock(full_dir):
        return _load_database_locked(sources, full_dir)


def verify_database(sources: list[str], full_dir: Path = FULL) -> dict[str, object]:
    """Fail closed on the complete state and prove a no-op idempotent rerun."""
    with loader_lock(full_dir):
        reject_pipeline_managed_target()
        admissions = preflight_sources(sources, full_dir)
        before = assert_complete_state(admissions)
        rerun = _load_database_locked(sources, full_dir)
        after = assert_complete_state(admissions)
    stable_keys = (
        "catalog_fields", "total_rows", "distinct_keys", "duplicate_groups",
        "missing_observation_provenance", "missing_ingest_provenance", "passed_ingests",
        "all_ingests", "census_rows", "source_counts", "ingests", "source_geography",
    )
    checks = {name: before[name] == after[name] for name in stable_keys}
    checks["rerun_skipped"] = all(status == "skipped" for _, status in rerun.sources)
    checks["idempotent"] = all(checks.values())
    if not checks["idempotent"]:
        failed = ",".join(sorted(name for name, passed in checks.items() if not passed))
        raise AdmissionError(f"idempotent_verification_failed:{failed}")
    return {
        "status": "pass",
        "database": TARGET_DATABASE,
        "sources": [admission.source for admission in admissions],
        "rerun": rerun.as_dict(),
        "before": before,
        "after": after,
        "checks": checks,
    }


def manifest_pass_sources(full_dir: Path = FULL) -> list[str]:
    manifest = load_json(full_dir / "state" / "run-manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), dict):
        raise AdmissionError("manifest_invalid")
    return sorted(source for source, item in manifest["sources"].items()
                  if isinstance(item, dict) and item.get("status") == "pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    load_parser = subparsers.add_parser("load")
    load_parser.add_argument("--all", action="store_true", required=True,
                             help="admit every source whose manifest status is pass")
    load_parser.add_argument("--full-dir", type=Path, default=FULL)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--all", action="store_true", required=True,
                               help="verify the complete target and an idempotent rerun")
    verify_parser.add_argument("--full-dir", type=Path, default=FULL)
    args = parser.parse_args()
    try:
        sources = manifest_pass_sources(args.full_dir)
        outcome = (load_database(sources, args.full_dir) if args.command == "load"
                   else verify_database(sources, args.full_dir))
        print(json.dumps(outcome.as_dict() if isinstance(outcome, LoadOutcome) else outcome,
                         sort_keys=True))
        return 0
    except (AdmissionError, RuntimeError, OSError) as error:
        print(json.dumps({"status": "fail", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
