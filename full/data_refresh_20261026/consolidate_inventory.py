#!/usr/bin/env python3
"""Build one immutable, hash-bound local runtime from verified refresh outputs."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

OUTPUT_KEYS = {"output", "annualOutput", "comparisonOutput", "incomeOutput", "perResidentOutput",
               "missingnessOutput", "annualMissingness", "missingnessPath", "loaderInput", "loaderMissingnessInput",
               "definitionMatrixPath"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def row_count(path: Path) -> int | None:
    if path.suffix.lower() == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            return max(0, sum(1 for _ in csv.reader(stream)) - 1)
    if path.suffix.lower() == ".jsonl":
        with path.open("rb") as stream:
            return sum(1 for line in stream if line.strip())
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("rows"), list):
            return len(value["rows"]) + len(value.get("additionalRows", []))
        if isinstance(value, list):
            return len(value)
        return 1
    return None


def _walk_result_outputs(node: Any, address: str = "results") -> list[tuple[str, str, dict[str, Any] | None, str | None]]:
    found: list[tuple[str, str, dict[str, Any] | None, str | None]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{address}.{key}"
            if key in OUTPUT_KEYS and isinstance(value, str):
                expected = node.get(key + "Sha256")
                found.append((child, value, node, expected))
            elif key == "outputs" and isinstance(value, list):
                for index, path in enumerate(value):
                    if isinstance(path, str):
                        found.append((f"{child}[{index}]", path, None, None))
            elif key == "preparedArtifacts" and isinstance(value, list):
                for index, artifact in enumerate(value):
                    if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                        found.append((f"{child}[{index}].path", artifact["path"], artifact, artifact.get("sha256")))
            else:
                found.extend(_walk_result_outputs(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk_result_outputs(value, f"{address}[{index}]"))
    return found


def validate_output_bindings(inventory: dict[str, Any], validate_medical: bool = True) -> None:
    runtime = Path(inventory["runtimePath"]).resolve()
    raw_root = (runtime / "raw/receipts").resolve()
    for receipt in inventory.get("sourceArtifacts", []):
        if "payloadAvailable" not in receipt:
            continue
        path_value = receipt.get("path")
        if not receipt.get("payloadAvailable"):
            if path_value is not None or receipt.get("status") != "blocked_http":
                raise ValueError("source_receipt_unavailable_status_mismatch")
            continue
        path = Path(path_value).resolve()
        if not path.is_relative_to(raw_root) or not path.is_file():
            raise ValueError("source_receipt_outside_runtime_or_missing")
        digest = sha256_file(path)
        if digest != receipt.get("storedBytesSha256") or path.stat().st_size != receipt.get("storedBytes"):
            raise ValueError("source_receipt_stored_hash_mismatch")
        if receipt.get("sha256") and digest != receipt["sha256"]:
            raise ValueError("source_receipt_original_hash_mismatch")
    prepared_root = (runtime / "prepared").resolve()
    artifacts = inventory.get("preparedArtifacts", [])
    by_path: dict[str, dict[str, Any]] = {}
    basenames: set[str] = set()
    for item in artifacts:
        path = Path(item["path"]).resolve()
        if path in (Path(x).resolve() for x in by_path):
            raise ValueError("duplicate_prepared_artifact_path")
        if path.name in basenames:
            raise ValueError("prepared_basename_collision")
        basenames.add(path.name)
        if not path.is_relative_to(prepared_root) or not path.is_file():
            raise ValueError("prepared_artifact_outside_runtime_or_missing")
        digest = sha256_file(path)
        if digest != item.get("sha256") or path.stat().st_size != item.get("bytes") or row_count(path) != item.get("rowCount"):
            raise ValueError("prepared_artifact_hash_or_size_mismatch")
        by_path[str(path)] = item
    bindings = inventory.get("resultOutputBindings", [])
    binding_map = {binding["resultField"]: binding for binding in bindings}
    if len(binding_map) != len(bindings):
        raise ValueError("duplicate_result_output_binding")
    for address, path_value, _parent, expected_hash in _walk_result_outputs(inventory.get("results", {})):
        path = Path(path_value).resolve()
        if not path.is_relative_to(prepared_root):
            raise ValueError("result_output_outside_final_runtime")
        item = by_path.get(str(path))
        if item is None:
            raise ValueError("result_output_missing_prepared_artifact")
        digest = sha256_file(path)
        if expected_hash and expected_hash != digest:
            raise ValueError("result_output_declared_hash_mismatch")
        binding = binding_map.get(address)
        if not binding or binding.get("path") != str(path) or binding.get("sha256") != digest:
            raise ValueError("result_output_binding_mismatch")
    if set(binding_map) != {address for address, *_ in _walk_result_outputs(inventory.get("results", {}))}:
        raise ValueError("result_output_binding_set_mismatch")
    if validate_medical:
        _validate_medical_rates(prepared_root)


def _validate_medical_rates(prepared_root: Path) -> None:
    expected = (("cancer-2023-rates.csv", "2023", 52, "total"),
                ("hiv-2024-rates.csv", "2024", 51, "age_13_plus"),
                ("child-deaths-under18-2024-rates.csv", "2024", 51, "under_18"))
    for filename, year, count, denominator_kind in expected:
        path = prepared_root / filename
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != count or len({row["geo_id"] for row in rows}) != count:
            raise ValueError("medical_rate_geography_coverage_mismatch")
        if any(row["year"] != year or row["denominator_year"] != year or row["denominator_kind"] != denominator_kind for row in rows):
            raise ValueError("medical_event_denominator_year_or_kind_mismatch")
        for row in rows:
            numerator, denominator = int(row["numerator"]), int(row["denominator"])
            if numerator < 0 or denominator <= 0:
                raise ValueError("medical_rate_numerator_denominator_invalid")
            calculated = Decimal(numerator) * Decimal(100000) / Decimal(denominator)
            if abs(Decimal(row["value"]) - calculated) > Decimal("1e-20"):
                raise ValueError("medical_rate_formula_mismatch")
        if filename == "cancer-2023-rates.csv":
            national = [row for row in rows if row["geo_id"] == "US" and row["geo_type"] in {"nation", "national"}]
            if len(national) != 1 or national[0]["numerator"] != "1941540" or national[0]["denominator"] != "336755052":
                raise ValueError("cancer_native_us_source_or_denominator_mismatch")


def _copy_file(source: Path, target: Path, expected_sha: str | None = None) -> str:
    if not source.is_file():
        raise ValueError("input_file_missing")
    digest = sha256_file(source)
    if expected_sha and digest != expected_sha:
        raise ValueError("input_file_hash_mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if sha256_file(target) != digest:
        raise ValueError("copied_file_hash_mismatch")
    return digest


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "source"


def reader_contract_version(inventory: dict[str, Any]) -> str | None:
    """Prefer the version declared by the result contract over a legacy seed default."""
    results = inventory.get("results", {})
    return results.get("readerContractVersion") or inventory.get("readerContractVersion")


def collector_version(inventory: dict[str, Any]) -> str | None:
    """Use the producer package version recorded by the preparation results."""
    results = inventory.get("results", {})
    return results.get("collectorVersion") or inventory.get("collectorVersion")


def _rewrite_paths(node: Any, prepared_map: dict[str, str], raw_map: dict[str, str], evidence_map: dict[str, str]) -> Any:
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if isinstance(value, str) and not key.lower().startswith("original") and (key.lower().endswith("path") or key.lower().endswith("output") or key in OUTPUT_KEYS or key in {"sourcePath", "path"}):
                value = prepared_map.get(value, raw_map.get(value, evidence_map.get(value, value)))
            elif key == "outputs" and isinstance(value, list):
                value = [prepared_map.get(item, raw_map.get(item, evidence_map.get(item, item))) if isinstance(item, str) else item for item in value]
            else:
                value = _rewrite_paths(value, prepared_map, raw_map, evidence_map)
            out[key] = value
        return out
    if isinstance(node, list):
        return [_rewrite_paths(value, prepared_map, raw_map, evidence_map) for value in node]
    return node


def consolidate(source_inventory: Path, correct_prepared: Path, fbi_prepared: Path,
                fbi_raw: Path, final_runtime: Path, inventory_output: Path,
                commit: str) -> dict[str, Any]:
    destination_runtime = final_runtime.resolve()
    final_runtime = destination_runtime.with_name(destination_runtime.name + ".building")
    if destination_runtime.exists() or final_runtime.exists():
        raise ValueError("final_runtime_exists_immutable")
    source = json.loads(source_inventory.read_text(encoding="utf-8"))
    results = source["results"]
    final_runtime.mkdir(parents=True)
    prepared_dir = final_runtime / "prepared"
    prepared_dir.mkdir()

    output_sources: dict[str, Path] = {}
    output_aliases: set[str] = set()
    for address, value, _parent, _expected in _walk_result_outputs(results):
        original = Path(value)
        output_aliases.add(str(original))
        if address.endswith(".definitionMatrixPath"):
            original = fbi_prepared / "definition_matrix.json"
        if original.name == "fbi-annual-estimates-2025.csv": original = fbi_prepared / original.name
        if original.name == "fbi-annual-estimates-2025-missingness.jsonl": original = fbi_prepared / original.name
        if original.name == "fbi-2023-baseline-2025-annual-ranks.csv": original = fbi_prepared / original.name
        if original.parent.name != "prepared" and not str(original).startswith(str(fbi_prepared)):
            raise ValueError("result_output_not_prepared_input")
        if not original.is_file():
            raise ValueError("result_output_source_missing")
        prior = output_sources.get(original.name)
        if prior and prior.resolve() != original.resolve():
            raise ValueError("result_output_basename_collision")
        output_sources[original.name] = original

    for source_path in correct_prepared.iterdir():
        if not source_path.is_file() or source_path.name in {"fbi-2023-baseline-2025-annual-pending.csv", "definition_matrix.json"}:
            continue
        prior = output_sources.get(source_path.name)
        if prior and prior.resolve() != source_path.resolve():
            if sha256_file(prior) != sha256_file(source_path):
                raise ValueError("prepared_input_basename_collision")
            # The result's explicit path is authoritative; this is a byte-identical alias.
            continue
        output_sources[source_path.name] = source_path
    for source_path in output_sources.values():
        shutil.copyfile(source_path, prepared_dir / source_path.name)

    # Copy each collected source payload by source identity and content hash, never by basename alone.
    raw_map: dict[str, str | None] = {}
    copied_sources = []
    source_records = []
    for index, artifact in enumerate(source.get("sourceArtifacts", [])):
        source_path = Path(artifact["path"])
        expected = artifact.get("sha256")
        if not source_path.is_file():
            if artifact.get("status") != "blocked_http":
                raise ValueError("source_receipt_missing")
            raw_map[str(source_path)] = None
            source_records.append({**artifact, "originalPath": str(source_path), "path": None,
                                  "sha256": None, "storedBytesSha256": None, "storedBytes": 0,
                                  "payloadAvailable": False, "hashKind": "blocked_http_no_payload"})
            continue
        actual = sha256_file(source_path)
        if expected and actual != expected:
            raise ValueError("source_receipt_hash_mismatch")
        source_id = _safe_id(artifact.get("sourceId", f"source-{index}"))
        suffix = source_path.suffix or ".bin"
        target = final_runtime / "raw/receipts" / source_id / f"{actual}{suffix}"
        if not target.exists():
            _copy_file(source_path, target, expected)
            copied_sources.append(target)
        raw_map[str(source_path)] = str(target)
        source_records.append({**artifact, "originalPath": str(source_path), "path": str(target),
                               "sha256": expected, "storedBytesSha256": actual,
                               "storedBytes": target.stat().st_size,
                               "payloadAvailable": True,
                               "hashKind": "source_bytes" if expected else "captured_error_receipt_bytes"})

    evidence_map: dict[str, str] = {}
    def copy_evidence(original: str, expected_hash: str | None, rel: str) -> None:
        src = Path(original)
        if not src.is_file():
            raise ValueError("evidence_receipt_missing")
        actual = sha256_file(src)
        if expected_hash and actual != expected_hash:
            raise ValueError("evidence_receipt_hash_mismatch")
        dst = final_runtime / "evidence" / rel
        if not dst.exists(): _copy_file(src, dst, expected_hash)
        evidence_map[original] = str(dst)

    for f in results.get("fbiAnnualComparison", {}).get("baselineSnapshots", []):
        copy_evidence(f["path"], f["sha256"], "published-before/" + Path(f["path"]).name)
    baseline_inventory = results.get("fbiAnnualComparison", {}).get("baselineSource")
    if baseline_inventory:
        copy_evidence(baseline_inventory, None, "published-before/inventory.json")
    for item in results.get("existingMedicalRates", {}).values():
        receipt_path = item.get("publisherRawReceipt", {}).get("retrievalReceiptPath")
        receipt_hash = item.get("publisherRawReceipt", {}).get("retrievalReceiptSha256")
        if receipt_path:
            copy_evidence(receipt_path, receipt_hash, "medical-retrieval-receipts/" + Path(receipt_path).name)
    bls_result_path = results.get("blsUnemployment", {}).get("sourceResultPath")
    if bls_result_path:
        expected = results["blsUnemployment"].get("sourceResultSha256")
        copy_evidence(bls_result_path, expected, "bls/parent-results.json")

    # Rebind every prepared output to this immutable directory and store a direct hash binding.
    prepared_map = {}
    for original in output_sources.values():
        prepared_map[str(original)] = str(prepared_dir / original.name)
    for original in output_aliases:
        name = Path(original).name
        if name not in output_sources:
            raise ValueError("result_output_alias_has_no_selected_artifact")
        prepared_map[original] = str(prepared_dir / name)
    # The generated FBI source outputs and definition matrix are mapped by their chosen exact input paths.
    for name in ("fbi-annual-estimates-2025.csv", "fbi-annual-estimates-2025-missingness.jsonl",
                 "fbi-2023-baseline-2025-annual-ranks.csv", "definition_matrix.json"):
        candidates = [p for p in (fbi_prepared / name, correct_prepared / name) if p.is_file()]
        if not candidates:
            raise ValueError("required_final_prepared_file_missing")
        prepared_map[str(candidates[0])] = str(prepared_dir / name)

    rewritten = _rewrite_paths(results, prepared_map, raw_map, evidence_map)
    # Replace source artifact and prepared artifact lists with exact final-runtime manifests.
    for record in rewritten.get("blsUnemployment", {}).get("preparedArtifacts", []):
        if record.get("sourcePath") in raw_map: record["sourcePath"] = raw_map[record["sourcePath"]]
    for root in ("fixedSources", "freshnessPageSnapshots"):
        for artifact in rewritten.get(root, {}).values():
            if isinstance(artifact, dict) and artifact.get("path") in raw_map:
                artifact["path"] = raw_map[artifact["path"]]
    rewritten["fbiAnnualComparison"]["annualSource"]["path"] = raw_map.get(
        source["results"]["fbiAnnualComparison"]["annualSource"]["path"],
        str(final_runtime / "raw/receipts/fbi-srs-estimated-crimes-1979-2025" / f"{sha256_file(fbi_raw)}{fbi_raw.suffix}"))

    prepared_artifacts = []
    for path in sorted(prepared_dir.iterdir()):
        if not path.is_file(): continue
        count = row_count(path)
        prepared_artifacts.append({"path": str(path), "bytes": path.stat().st_size,
                                   "sha256": sha256_file(path), "rowCount": count,
                                   "artifactType": "locally_prepared_or_imported"})
    artifact_by_path = {item["path"]: item for item in prepared_artifacts}
    bindings = []
    for address, value, parent, expected in _walk_result_outputs(rewritten):
        path = Path(value).resolve()
        artifact = artifact_by_path.get(str(path))
        if not artifact:
            raise ValueError("rewritten_result_output_unbound:" + address + ":" + path.name)
        if expected and expected != artifact["sha256"]:
            raise ValueError("result_declared_hash_mismatch")
        bindings.append({"resultField": address, "path": str(path), "sha256": artifact["sha256"],
                         "rowCount": artifact["rowCount"]})
        if parent is not None:
            # The following object is only used for metadata injection; stored inventory is rewritten below.
            pass
    final_source_records = []
    for record in source_records:
        record = _rewrite_paths(record, prepared_map, raw_map, evidence_map)
        final_source_records.append(record)
    output = {**source, "collectorVersion": collector_version(source),
              "readerContractVersion": reader_contract_version(source), "workerCommit": commit,
              "runtimePath": str(final_runtime.resolve()), "results": rewritten,
              "definitionMatrix": rewritten.get("definitionMatrixPath"),
              "preparedArtifacts": prepared_artifacts, "sourceArtifacts": final_source_records,
              "resultOutputBindings": bindings,
              "ready": False,
              "readinessReason": "Immutable, hash-verified local preparation only; source gaps, native-US gaps and House source identity remain review gates. No database admission is performed."}
    validate_output_bindings(output)
    final_runtime.parent.mkdir(parents=True, exist_ok=True)
    final_runtime.replace(destination_runtime)
    old_prefix, new_prefix = str(final_runtime.resolve()), str(destination_runtime)
    def move_runtime_prefix(value: Any) -> Any:
        if isinstance(value, dict): return {k: move_runtime_prefix(v) for k, v in value.items()}
        if isinstance(value, list): return [move_runtime_prefix(v) for v in value]
        if isinstance(value, str) and value.startswith(old_prefix): return new_prefix + value[len(old_prefix):]
        return value
    output = move_runtime_prefix(output)
    output["runtimePath"] = new_prefix
    validate_output_bindings(output)
    inventory_output.parent.mkdir(parents=True, exist_ok=True)
    tmp = inventory_output.with_suffix(inventory_output.suffix + ".tmp")
    tmp.write_text(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(inventory_output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-inventory", type=Path, required=True)
    parser.add_argument("--correct-prepared-dir", type=Path, required=True)
    parser.add_argument("--fbi-prepared-dir", type=Path, required=True)
    parser.add_argument("--fbi-raw", type=Path, required=True)
    parser.add_argument("--final-runtime", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    consolidate(args.source_inventory, args.correct_prepared_dir, args.fbi_prepared_dir,
                args.fbi_raw, args.final_runtime, args.inventory, args.commit)
    print(json.dumps({"status": "complete", "inventory": str(args.inventory), "runtime": str(args.final_runtime)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
