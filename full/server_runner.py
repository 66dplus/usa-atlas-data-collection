#!/usr/bin/env python3
"""Run one collector source safely under a nonblocking process lock."""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import json
import os
from pathlib import Path
from typing import Iterator

import collect


LOCK_PATH = collect.STATE / "server-runner.lock"


class RunnerBusy(RuntimeError):
    """Raised when another state-changing collector process owns the lock."""


@contextlib.contextmanager
def exclusive_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    """Own *path* for one state-changing command, or fail immediately."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise RunnerBusy("another collector process is running") from None
            raise
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def select_source(mapping: dict, source: str) -> dict:
    """Return a one-source dispatch table while keeping collect.py unchanged."""
    if source not in mapping:
        raise ValueError(f"unknown source: {source}")
    return {source: mapping[source]}


def calibration_ready(source: str) -> bool:
    """Check that the selected source has current, verified calibration evidence."""
    if not collect.CALIBRATION_PATH.exists():
        return False
    try:
        report = collect.load_json(collect.CALIBRATION_PATH)
        if any(report.get(key) != value for key, value in collect.current_bindings().items()):
            return False
        item = report.get("sources", {}).get(source, {})
        if item.get("status") != "pass":
            return False
        for artifact in item.get("artifacts", []):
            verified = collect.verified_file_artifact(collect.HERE / artifact["path"])
            if verified is None or verified["sha256"] != artifact["sha256"]:
                return False
        return bool(item.get("artifacts"))
    except (OSError, KeyError, TypeError, ValueError, collect.CollectionError):
        return False


def calibrate_if_needed(source: str) -> int:
    if calibration_ready(source):
        print(json.dumps({"source": source, "calibration": "reused"}))
        return 0
    collect.CALIBRATORS = select_source(collect.CALIBRATORS, source)
    return collect.run_calibration()


def run_source(source: str) -> int:
    collect.FULL_RUNNERS = select_source(collect.FULL_RUNNERS, source)
    try:
        return collect.run_full()
    except KeyboardInterrupt:
        collect.mark_interrupted()
        return 130


def source_status(source: str) -> int:
    """Print manifest state and relevant live-process state for one source."""
    manifest = (collect.load_json(collect.MANIFEST_PATH)
                if collect.MANIFEST_PATH.exists() else {"status": "not_started", "sources": {}})
    source_state = manifest.get("sources", {}).get(source, {"status": "not_started"})
    runtime = (collect.load_json(collect.STATUS_PATH)
               if collect.STATUS_PATH.exists() else {"status": "not_started"})
    if runtime.get("status") == "running" and runtime.get("pid"):
        try:
            os.kill(int(runtime["pid"]), 0)
        except ProcessLookupError:
            runtime = {**runtime, "status": "interrupted", "reason": "process_not_running"}
        except PermissionError:
            pass
    relevant_runtime = runtime if runtime.get("source") in {None, source} else {
        "status": "not_running_for_source",
        "active_source": runtime.get("source"),
    }
    print(json.dumps({
        "source": source,
        "status": source_state.get("status", "not_started"),
        "run_status": manifest.get("status", "not_started"),
        "details": source_state,
        "runtime": relevant_runtime,
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate, run, or inspect one USA Atlas collector source."
    )
    parser.add_argument("command", choices=("validate", "calibrate-if-needed", "run", "status"))
    parser.add_argument("--source", choices=tuple(collect.FULL_RUNNERS), help="provider source to run")
    args = parser.parse_args()

    if args.command == "validate":
        result = collect.validate_contract()
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    if not args.source:
        parser.error(f"--source is required for {args.command}")
    if args.command == "status":
        return source_status(args.source)

    try:
        with exclusive_lock():
            if args.command == "calibrate-if-needed":
                return calibrate_if_needed(args.source)
            return run_source(args.source)
    except RunnerBusy as error:
        print(json.dumps({"status": "busy", "reason": str(error)}))
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
