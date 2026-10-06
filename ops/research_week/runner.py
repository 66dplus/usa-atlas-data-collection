#!/usr/bin/env python3
"""Bounded real Codex research sessions. No credentials or model overrides."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
RUNTIME = BASE / "runtime"


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(root: Path, value: str):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("artifact must be inside the topic output directory")
    return path


def snapshot(root: Path):
    return {
        str(p.relative_to(root)): digest(p)
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
        and p.name != ".first-session.json"
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    }


def seed_artifacts(root: Path, selected: list[str]):
    readme = root / "README.md"
    if not readme.is_file() or not readme.read_text(encoding="utf-8").strip():
        raise ValueError("seed requires a nonempty README.md")
    files = [inside(root, name) for name in selected] if selected else [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".json", ".csv", ".jsonl"}
        and p.name != ".first-session.json"
        and "sessions" not in p.relative_to(root).parts
        and "smoke" not in p.relative_to(root).parts
    ]
    records = []
    for path in files:
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            valid = bool(read_json(path))
        elif path.suffix.lower() == ".jsonl":
            valid = any(bool(json.loads(line)) for line in path.read_text().splitlines() if line.strip())
        elif path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as stream:
                rows = csv.reader(stream)
                next(rows, None)
                valid = any(any(cell.strip() for cell in row) for row in rows)
        else:
            valid = False
        if valid:
            records.append({"path": str(path.relative_to(root)), "sha256": digest(path)})
    if not records:
        raise ValueError("seed requires nonempty parseable structured records")
    return [{"path": "README.md", "sha256": digest(readme)}, *records]


def window(cfg, now: datetime):
    zone = ZoneInfo(cfg["timezone"])
    start = datetime.fromisoformat(cfg["start_local"])
    deadline_value = cfg.get("deadline_local")
    deadline = datetime.fromisoformat(deadline_value) if deadline_value else None
    if start.astimezone(zone).utcoffset() != start.utcoffset() or (deadline and deadline.astimezone(zone).utcoffset() != deadline.utcoffset()):
        raise ValueError("configured timestamps do not match the named timezone")
    local = now.astimezone(zone)
    remaining = int((deadline - now).total_seconds()) if deadline else None
    active = now >= start and (remaining is None or remaining >= cfg["minimum_remaining_seconds"])
    return local.date().isoformat(), remaining, active


def receipts(topic: str):
    return [read_json(p) for p in (RUNTIME / "receipts" / topic).glob("*.json")]


def guard(cfg, topic: str, now: datetime, smoke=False, retry=False):
    output = (REPO / cfg["topics"][topic]["output_dir"]).resolve()
    date, remaining, active = window(cfg, now)
    if not active:
        return "outside_research_window", date, remaining, output
    seed = read_json(output / ".first-session.json")
    if not seed or seed.get("topic") != topic:
        return "first_session_not_registered", date, remaining, output
    if smoke:
        return None, date, remaining, output
    if seed.get("local_date") == date:
        return "first_session_already_completed_today", date, remaining, output
    past = [r for r in receipts(topic) if r.get("mode") == "research" and r.get("launched")]
    today = [r for r in past if r["local_date"] == date]
    if today:
        if not retry:
            return "session_already_attempted_today", date, remaining, output
        if len(today) >= cfg["max_attempts_per_topic_per_day"]:
            return "daily_attempt_limit_reached", date, remaining, output
        latest = max(today, key=lambda r: r["started_at"])
        if latest.get("status") not in {"failed", "timed_out", "interrupted", "validation_failed", "started"}:
            return "successful_session_already_completed_today", date, remaining, output
    return None, date, remaining, output


def command(cfg, cwd: Path, final: Path):
    return [
        cfg["codex_binary"], "--no-daemon", "--search", "-a", "never",
        "exec", "--sandbox", cfg["sandbox"],
        "-c", "sandbox_workspace_write.network_access=true",
        "--cd", str(cwd), "--json", "--color", "never",
        "--output-schema", str(BASE / "session-report.schema.json"),
        "--output-last-message", str(final), "-",
    ]


def event_summary(path: Path):
    summary = {"thread_id": None, "turn_completed": False, "turn_failed": False,
               "web_searches": 0, "command_executions": 0, "file_changes": 0, "usage": None}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "thread.started":
            summary["thread_id"] = event.get("thread_id")
        elif kind == "turn.completed":
            summary["turn_completed"] = True
            summary["usage"] = event.get("usage")
        elif kind in {"turn.failed", "error"}:
            summary["turn_failed"] = True
        if kind == "item.completed":
            item_type = event.get("item", {}).get("type")
            key = {"web_search": "web_searches", "command_execution": "command_executions",
                   "file_change": "file_changes"}.get(item_type)
            if key:
                summary[key] += 1
    return summary


def validate_report(report, topic: str, output: Path, before: dict, summary):
    keys = {"topic", "run_status", "summary", "artifacts", "sources", "blockers", "next_actions"}
    if not isinstance(report, dict) or set(report) != keys or report["topic"] != topic:
        raise ValueError("final report has an invalid schema or topic")
    if report["run_status"] not in {"completed", "partial", "blocked"} or not isinstance(report["summary"], str):
        raise ValueError("final report has an invalid research status or summary")
    for name in ["artifacts", "blockers", "next_actions"]:
        if not isinstance(report[name], list) or not all(isinstance(x, str) for x in report[name]):
            raise ValueError("final report has an invalid list")
    if not isinstance(report["sources"], list) or not report["sources"]:
        raise ValueError("no checked sources were reported")
    for source in report["sources"]:
        if not isinstance(source, dict) or set(source) != {"url", "title"}:
            raise ValueError("invalid source metadata")
        if not isinstance(source["title"], str) or not isinstance(source["url"], str):
            raise ValueError("source URL and title must be strings")
        parsed = urlparse(source["url"])
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("source must use a public HTTP(S) URL")
    if not summary["turn_completed"] or summary["turn_failed"] or not summary["thread_id"]:
        raise ValueError("no successful real Codex turn was observed")
    if not summary["web_searches"]:
        raise ValueError("no live web-search event was observed")
    changed = []
    for name in report["artifacts"]:
        path = inside(output, name)
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise ValueError("reported artifact does not exist or is empty")
        sha = digest(path)
        if before.get(str(path.relative_to(output))) != sha:
            changed.append({"path": str(path.relative_to(output)), "sha256": sha, "bytes": path.stat().st_size})
    if not changed:
        raise ValueError("no substantive artifact was written or updated")
    return changed


def run(cfg, args):
    reason, date, remaining, output = guard(cfg, args.topic, datetime.now(timezone.utc), args.smoke, args.retry_failed)
    duration = cfg["smoke_timeout_seconds"] if args.smoke else cfg["session_timeout_seconds"]
    if remaining is not None:
        duration = min(duration, remaining)
    if args.timeout_seconds is not None:
        duration = min(duration, args.timeout_seconds)
    plan = {"topic": args.topic, "mode": "smoke" if args.smoke else "research", "local_date": date,
            "timezone": cfg["timezone"], "deadline_local": cfg.get("deadline_local"), "output_dir": str(output),
            "timeout_seconds": max(0, duration), "skip_reason": reason, "model": "inherited from existing Codex configuration"}
    if args.dry_run:
        plan["command"] = command(cfg, output, RUNTIME / "dry-run" / "final.json")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if reason:
        record = dict(plan, status="skipped", launched=False, observed_at=timestamp())
        write_json(RUNTIME / "receipts" / args.topic / f"{date}-skip.json", record)
        print(json.dumps(record, ensure_ascii=False))
        return 0
    lock_path = RUNTIME / "locks" / (args.topic + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps(dict(plan, status="skipped", skip_reason="topic_already_running", launched=False)))
            return 0
        # Recheck inside the lock: two simultaneous starts must never create two attempts.
        reason, date, remaining, output = guard(cfg, args.topic, datetime.now(timezone.utc), args.smoke, args.retry_failed)
        if reason:
            print(json.dumps(dict(plan, status="skipped", skip_reason=reason, launched=False)))
            return 0
        started = datetime.now(timezone.utc)
        run_id = started.strftime("%Y%m%dT%H%M%S%fZ") + ("-smoke" if args.smoke else "")
        run_dir = RUNTIME / "runs" / args.topic / run_id
        run_dir.mkdir(parents=True)
        session = output / ("smoke" if args.smoke else "sessions") / (run_id if args.smoke else date)
        session.mkdir(parents=True, exist_ok=True)
        before = snapshot(output)
        if args.smoke:
            prompt = (
                f"Prove that a short unattended Codex session can research topic {args.topic}. "
                "This is only a capability check, not the full daily research session. "
                "Do not read the whole repository or rebuild the seed. Use one live web search "
                "for an official primary source about "
                + ("Federal Reserve Survey of Consumer Finances net worth definitions" if args.topic == "wealth-datacenters" else "Census ACS five-year estimates margins of error")
                + ". Open one matching official page. Write smoke.md in the session directory with "
                "a short sourced finding (or a precise access failure), its URL and one next action. "
                "Do not perform additional research once this artifact is written. Return JSON with "
                "exact fields topic, run_status, summary, artifacts (paths relative to the output directory), "
                "sources (objects with url and title), blockers, next_actions. "
                "Use the JSON schema supplied by the command. Finish within 2 minutes."
            )
        else:
            prompt = (BASE / cfg["topics"][args.topic]["prompt"]).read_text(encoding="utf-8")
        deadline_text = cfg.get("deadline_local") or "No campaign end date; the daily research cycle continues until disabled."
        prompt += (f"\n\nExecution context:\nRepository (read only): {REPO}\n"
                   f"Writable output directory/current working directory: {output}\n"
                   f"Session directory: {session}\nTopic: {args.topic}\nLocal date: {date}\n"
                   f"Timezone: {cfg['timezone']}\nCampaign end: {deadline_text}\n"
                   f"Time budget: {duration} seconds. Finish and save artifacts before this limit.\n")
        if args.smoke:
            prompt += ("\nTHIS IS A SHORT CAPABILITY SMOKE SESSION. Do one focused live web search and open an actual "
                       "public primary source relevant to the existing seed. Save smoke.md in the supplied smoke session "
                       "directory with a source-grounded finding or exact access blocker and a next action. Update no "
                       "seed datasets or main README/queue. Return the required JSON, with the real smoke.md artifact.\n")
        (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        final = run_dir / "final.json"
        events = run_dir / "events.jsonl"
        receipt_path = RUNTIME / "receipts" / args.topic / (run_id + ".json")
        state_path = RUNTIME / "state" / (args.topic + ".json")
        record = dict(plan, run_id=run_id, status="started", launched=True, started_at=started.isoformat(),
                      receipt=str(receipt_path), events=str(events), final_report=str(final))
        write_json(receipt_path, record)
        write_json(state_path, record)
        process = None
        interrupted = {"signal": None}

        def stop(signum, _frame):
            interrupted["signal"] = signum
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

        previous = {sig: signal.signal(sig, stop) for sig in [signal.SIGTERM, signal.SIGINT]}
        try:
            with events.open("w", encoding="utf-8") as stdout, (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
                process = subprocess.Popen(command(cfg, output, final), cwd=output, stdin=subprocess.PIPE,
                                           stdout=stdout, stderr=stderr, text=True, start_new_session=True)
                try:
                    process.communicate(prompt, timeout=max(1, duration))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                    record["status"] = "timed_out"
                record["exit_code"] = process.returncode
            summary = event_summary(events)
            record["codex"] = summary
            if interrupted["signal"] is not None:
                record["status"] = "interrupted"
                record["signal"] = interrupted["signal"]
            elif record["status"] != "timed_out":
                if process.returncode != 0:
                    record["status"] = "failed"
                else:
                    report = read_json(final)
                    record["changed_artifacts"] = validate_report(report, args.topic, output, before, summary)
                    record["research_status"] = report["run_status"]
                    record["status"] = "completed" if report["run_status"] == "completed" else report["run_status"]
                    record["summary"] = report["summary"]
                    record["sources"] = report["sources"]
                    record["blockers"] = report["blockers"]
                    record["next_actions"] = report["next_actions"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            record["status"] = "validation_failed" if process and process.returncode == 0 else "failed"
            # Keep credential-bearing raw subprocess stderr out of receipts and the journal.
            record["error"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            record["finished_at"] = timestamp()
            record["duration_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
            write_json(receipt_path, record)
            write_json(state_path, record)
        print(json.dumps(record, ensure_ascii=False))
        return 0 if record["status"] in {"completed", "partial", "blocked"} else 1


def main():
    os.umask(0o077)
    cfg = read_json(BASE / "config.json")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    launch = commands.add_parser("run")
    launch.add_argument("topic", choices=cfg["topics"])
    launch.add_argument("--dry-run", action="store_true")
    launch.add_argument("--smoke", action="store_true")
    launch.add_argument("--retry-failed", action="store_true")
    launch.add_argument("--timeout-seconds", type=int)
    seed = commands.add_parser("record-seed")
    seed.add_argument("topic", choices=cfg["topics"])
    seed.add_argument("--artifact", action="append", default=[])
    commands.add_parser("status")
    args = parser.parse_args()
    if args.action == "run":
        if args.timeout_seconds is not None and args.timeout_seconds < 30:
            parser.error("timeout must be at least 30 seconds")
        return run(cfg, args)
    if args.action == "record-seed":
        output = (REPO / cfg["topics"][args.topic]["output_dir"]).resolve()
        date, _, active = window(cfg, datetime.now(timezone.utc))
        if not active:
            raise ValueError("cannot register seed outside the configured week")
        marker = output / ".first-session.json"
        if marker.exists():
            raise ValueError("first session is already registered; do not replace its receipt")
        evidence = seed_artifacts(output, args.artifact)
        record = {"topic": args.topic, "status": "external_first_session_registered", "local_date": date,
                  "timezone": cfg["timezone"], "registered_at": timestamp(), "artifacts": evidence,
                  "note": "Initial collaborative research session; not a CLI execution receipt."}
        write_json(marker, record)
        write_json(RUNTIME / "state" / (args.topic + ".json"), record)
        print(json.dumps(record, ensure_ascii=False))
        return 0
    print(json.dumps({"timezone": cfg["timezone"], "start_local": cfg["start_local"],
                      "deadline_local": cfg.get("deadline_local"),
                      "topics": {topic: {"first_session": read_json(REPO / info["output_dir"] / ".first-session.json"),
                                          "latest": read_json(RUNTIME / "state" / (topic + ".json")),
                                          "receipts": receipts(topic)} for topic, info in cfg["topics"].items()}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}), file=sys.stderr)
        sys.exit(2)
