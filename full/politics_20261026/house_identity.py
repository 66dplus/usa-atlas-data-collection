"""Reconstruct and verify the original released MEDSL House v15 byte stream."""
import hashlib
import json
import pathlib

METADATA_SHA256 = "7f1e58721c198bfd7c1a4254b6704ba42aab6764e034ca456e1f7d536ce25c0b"
SOURCE_SHA256 = "bd0690fbcd753e45edb40810c99d1b8afbb0de928aa54bff1b227c615d69c163"
ORIGINAL_BYTES = 4156562
ORIGINAL_MD5 = "a9566ac393913a1af343284e837c17bb"
ORIGINAL_SHA256 = "76eec42483ee9f0fc5cf6e377442c783d1ae6eefa929729fd6561a69bab47f2a"
ORIGINAL_UNF = "UNF:6:cIJWG41N8qe3Kyf7oKuPdw=="
ROWS = 33805


def digest(data, algorithm):
    return hashlib.new(algorithm, data).hexdigest()


def _released_file(metadata):
    root = json.loads(pathlib.Path(metadata).read_text(encoding="utf-8"))
    if root.get("status") != "OK":
        raise ValueError("official Dataverse metadata status is not OK")
    latest = root["data"]["latestVersion"]
    if latest.get("versionNumber") != 15 or latest.get("UNF") != ORIGINAL_UNF:
        raise ValueError("official dataset is not the pinned released House v15")
    matches = [f["dataFile"] for f in latest["files"]
               if f.get("dataFile", {}).get("id") == 13592823]
    if len(matches) != 1:
        raise ValueError("official metadata does not identify exactly the pinned House data file")
    entry = matches[0]
    if (entry.get("filename") != "1976-2024-house.tab" or
            entry.get("originalFileSize") != ORIGINAL_BYTES or
            entry.get("checksum") != {"type": "MD5", "value": ORIGINAL_MD5}):
        raise ValueError("official House v15 file size or checksum metadata differs")
    return entry


def reconstruct(raw_path):
    raw = pathlib.Path(raw_path).read_bytes()
    if digest(raw, "sha256") != SOURCE_SHA256:
        raise ValueError("House source mirror SHA-256 differs from pinned bytes")
    lines = raw.splitlines()
    if len(lines) != ROWS + 1:
        raise ValueError("House source record count differs from official v15")
    out = [lines[0]]
    for line in lines[1:]:
        if len(line) < 2 or line[:1] != b'"' or line[-1:] != b'"':
            raise ValueError("House source row is not the pinned single-string serialization")
        out.append(line[1:-1].replace(b'\\"', b'"'))
    result = b"\n".join(out) + b"\n"
    if (len(result) != ORIGINAL_BYTES or digest(result, "md5") != ORIGINAL_MD5 or
            digest(result, "sha256") != ORIGINAL_SHA256):
        raise ValueError("reconstructed House bytes do not match official original checksum")
    return result


def verify(raw_path, metadata_path, reconstructed_path=None):
    metadata_path = pathlib.Path(metadata_path)
    if digest(metadata_path.read_bytes(), "sha256") != METADATA_SHA256:
        raise ValueError("official House metadata artifact SHA-256 differs")
    entry = _released_file(metadata_path)
    data = reconstruct(raw_path)
    if reconstructed_path is not None:
        target = pathlib.Path(reconstructed_path)
        if not target.is_file() or target.read_bytes() != data:
            raise ValueError("saved official-byte reconstruction differs from deterministic reconstruction")
    return {"status": "official_original_identity_verified", "version": 15,
            "datafile_id": entry["id"], "metadata_sha256": METADATA_SHA256,
            "source_mirror_sha256": SOURCE_SHA256, "original_bytes": len(data),
            "original_md5": ORIGINAL_MD5, "original_sha256": ORIGINAL_SHA256,
            "one_column_unf": ORIGINAL_UNF, "rows": ROWS,
            "transformation": "Preserve header; for each following line strip one outer quote pair, unescape backslash-quote, join LF with final LF."}
