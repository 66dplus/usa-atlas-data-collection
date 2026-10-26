"""Export a hash-bound legacy status view for the frozen reader-v2 BLS parser.

The collector result is never edited.  Only the separate ``result.status`` view
is translated from the collector's complete-with-gaps enum to the legacy
reader-v2 enum, after exact source, count, missingness, and raw-response checks.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import subprocess


NORMALIZED_FOR = "reader2.0.0_input_contract"
SOURCE_STATUS = "collection_complete_with_source_gaps"
LEGACY_STATUS = "partial"
EXPECTED_HASHES = {
    "observed_csv": "69d1129d1293086a782ea249b20fc2fe50768656f4755e483f787dc3334fad7c",
    "missingness_jsonl": "85407a19d28a6e02680c2d748c3f45b952368a27249a6c18b69a224c89cad97f",
    "collection_results": "8dead64b434563cd52d28df81885b8b272da137d81fab6e724c081595041fa15",
}
EXPECTED_COUNTS = {
    "batchCount": 256,
    "completedBatchCount": 256,
    "pendingSeriesCount": 0,
    "observedRows": 153312,
    "missingnessRows": 12828,
    "seriesCount": 12780,
    "registeredQueriesRecorded": 443,
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_source_result(result: dict, *, check_raw_files: bool = True) -> None:
    if result.get("status") != SOURCE_STATUS:
        raise ValueError("unrecognized BLS collector completion status")
    for key, expected in EXPECTED_COUNTS.items():
        if result.get(key) != expected:
            raise ValueError("BLS source result count mismatch: " + key)
    note = result.get("note", "")
    if ("M13 is retained as annual" not in note or
            "Missing periods remain missing" not in note):
        raise ValueError("BLS source result lacks the documented annual/gap semantics")

    raw_artifacts = result.get("rawArtifacts")
    if not isinstance(raw_artifacts, list) or len(raw_artifacts) != 256:
        raise ValueError("BLS raw response inventory is incomplete")
    if check_raw_files:
        for artifact in raw_artifacts:
            raw_path = pathlib.Path(artifact.get("path", ""))
            expected = artifact.get("sha256")
            if (not expected or not raw_path.is_file() or
                    sha256_file(raw_path) != expected):
                raise ValueError("BLS raw response is missing or changed")


def legacy_view(result: dict) -> dict:
    """Return the exact legacy input representation while preserving source result."""
    verify_source_result(result, check_raw_files=False)
    view = copy.deepcopy(result)
    view["status"] = LEGACY_STATUS
    unchanged = {key: value for key, value in view.items() if key != "status"}
    original_unchanged = {key: value for key, value in result.items() if key != "status"}
    if unchanged != original_unchanged:
        raise ValueError("legacy BLS view changed non-status collector metadata")
    return view


def current_commit(repo_root: pathlib.Path) -> str:
    try:
        value = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("cannot bind exporter to a local source commit") from exc
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("local exporter commit identity is malformed")
    return value


def export(observed_csv: pathlib.Path, missingness_jsonl: pathlib.Path,
           collection_results: pathlib.Path, output: pathlib.Path,
           repo_root: pathlib.Path) -> dict:
    input_paths = {
        "observed_csv": pathlib.Path(observed_csv).resolve(),
        "missingness_jsonl": pathlib.Path(missingness_jsonl).resolve(),
        "collection_results": pathlib.Path(collection_results).resolve(),
    }
    input_hashes = {}
    for key, path in input_paths.items():
        if not path.is_file() or sha256_file(path) != EXPECTED_HASHES[key]:
            raise ValueError("BLS trusted input hash mismatch: " + key)
        input_hashes[key] = EXPECTED_HASHES[key]

    original_bytes = input_paths["collection_results"].read_bytes()
    original_document = json.loads(original_bytes)
    source_result = original_document.get("result")
    if not isinstance(source_result, dict):
        raise ValueError("BLS source collection result object is missing")
    verify_source_result(source_result)

    # Independently confirm missingness counts and the documented gap shapes.
    m10_missing = 0
    returned_period_gaps = 0
    with input_paths["missingness_jsonl"].open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("bls_period_code") == "M10" and row.get("status") == "source_missing":
                m10_missing += 1
            if row.get("status") == "period_not_returned":
                returned_period_gaps += 1
    if (m10_missing != 12776 or returned_period_gaps != 52 or
            m10_missing + returned_period_gaps != EXPECTED_COUNTS["missingnessRows"]):
        raise ValueError("BLS missingness does not match the documented 2025 gaps")

    source_path = input_paths["collection_results"]
    module_path = pathlib.Path(__file__).resolve()
    module_sha = sha256_file(module_path)
    wrapper = {
        "format": "reader_v2_bls_legacy_status_export_v1",
        "normalizedFor": NORMALIZED_FOR,
        "sourceCollectionStatus": SOURCE_STATUS,
        "legacySnapshotCoverage": "partial_due_to_documented_source_gaps",
        "originalResultPath": str(source_path),
        "originalResultSha256": sha256_bytes(original_bytes),
        "sourceCollectionDocument": original_document,
        "sourceCollectionResult": copy.deepcopy(source_result),
        # The old parser indexes this top-level key; null truthfully records that
        # the recovered result did not include a collector-code fingerprint.
        "executedSourceSha256": original_document.get("executedSourceSha256"),
        "result": legacy_view(source_result),
        "inputHashes": input_hashes,
        "gapControls": {"M10_source_missing": m10_missing,
                        "period_not_returned": returned_period_gaps},
        "converter": {
            "module": "full/data_refresh_20261026/export_bls_reader_v2_input.py",
            "moduleSha256": module_sha,
            "commit": current_commit(pathlib.Path(repo_root).resolve()),
        },
        "statusNormalization": {
            "source": SOURCE_STATUS,
            "readerV2LegacyView": LEGACY_STATUS,
            "reason": "The frozen reader 2.0.0 input contract represents documented source gaps with status partial.",
            "onlyChangedField": "result.status",
        },
    }
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(wrapper, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(output), "sha256": sha256_file(output),
            "originalResultSha256": wrapper["originalResultSha256"],
            "converterCommit": wrapper["converter"]["commit"],
            "converterSha256": module_sha}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-csv", required=True, type=pathlib.Path)
    parser.add_argument("--missingness-jsonl", required=True, type=pathlib.Path)
    parser.add_argument("--collection-results", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--repo-root", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(export(args.observed_csv, args.missingness_jsonl,
                            args.collection_results, args.output, args.repo_root),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
