#!/usr/bin/env python3
"""Check ongoing USA Atlas research timers and retry eligible failed runs.

The scraper watchdog owns collection worker monitoring and bounded recovery.
This monitor owns only the allowlisted research timers and failed research attempts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_RUNTIME = ROOT / "ops/research_week/runtime"
STATE_DIR = Path("/var/lib/usa-atlas-continuous-monitor")
STATE_FILE = STATE_DIR / "state.json"
RESEARCH_TIMERS = (
    "usa-atlas-research-wealth.timer",
    "usa-atlas-research-facts.timer",
    "usa-atlas-research-medical.timer",
)
TOPICS = {
    "usa-atlas-research@wealth-datacenters.service": "wealth-datacenters",
    "usa-atlas-research@state-facts.service": "state-facts",
    "usa-atlas-research@medical-data.service": "medical-data",
}
FAILURE_STATES = {"failed", "timed_out", "interrupted", "validation_failed"}


def now():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or now()).isoformat()


def read_json(path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default or {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


def invoke(args, timeout=20, cwd=None):
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                              cwd=cwd, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None


def systemd_value(unit, property_name):
    result = invoke(["systemctl", "show", unit, f"--property={property_name}", "--value"])
    return result.stdout.strip() if result and result.returncode == 0 else None


def ensure_timer(unit, actions, checks):
    active = invoke(["systemctl", "is-active", "--quiet", unit])
    enabled = invoke(["systemctl", "is-enabled", "--quiet", unit])
    if active and active.returncode == 0 and enabled and enabled.returncode == 0:
        checks.append({"unit": unit, "state": "healthy"})
        return
    result = invoke(["systemctl", "enable", "--now", unit], timeout=30)
    after_active = invoke(["systemctl", "is-active", "--quiet", unit])
    after_enabled = invoke(["systemctl", "is-enabled", "--quiet", unit])
    ok = bool(result and result.returncode == 0 and after_active and after_active.returncode == 0
              and after_enabled and after_enabled.returncode == 0)
    actions.append({"unit": unit, "action": "enable_and_start_timer", "ok": ok})
    checks.append({"unit": unit, "state": "healthy" if ok else "needs_attention"})


def local_date():
    return now().astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()


def research_attempts(topic, date):
    folder = RESEARCH_RUNTIME / "receipts" / topic
    count = 0
    try:
        paths = folder.glob("*.json")
        for path in paths:
            record = read_json(path)
            if record.get("mode") == "research" and record.get("launched") and record.get("local_date") == date:
                count += 1
    except OSError:
        pass
    return count


def recover_failed_research(actions, checks):
    date = local_date()
    for service, topic in TOPICS.items():
        active = systemd_value(service, "ActiveState")
        result = systemd_value(service, "Result")
        state = read_json(RESEARCH_RUNTIME / "state" / f"{topic}.json")
        failed_today = state.get("local_date") == date and state.get("status") in FAILURE_STATES
        if active == "failed" and failed_today:
            attempts = research_attempts(topic, date)
            if attempts < 2:
                reset = invoke(["systemctl", "reset-failed", service])
                start = invoke(["systemctl", "start", "--no-block", service]) if reset and reset.returncode == 0 else None
                ok = bool(start and start.returncode == 0)
                actions.append({"unit": service, "action": "retry_failed_research_once", "attempts_today": attempts, "ok": ok})
                checks.append({"unit": service, "state": "retrying" if ok else "needs_attention"})
            else:
                checks.append({"unit": service, "state": "needs_attention", "reason": "daily_attempt_limit_reached"})
        elif active == "failed" and result not in (None, "success", "none"):
            checks.append({"unit": service, "state": "needs_attention", "reason": "failed_without_retryable_receipt"})
        elif active in ("activating", "active", "deactivating"):
            checks.append({"unit": service, "state": "running"})
        else:
            checks.append({"unit": service, "state": "ready_for_next_daily_run"})


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    state = read_json(STATE_FILE)
    report = {"checked_at": stamp(), "checks": [], "actions": [], "scope": "research timers and failed research attempts"}
    for timer in RESEARCH_TIMERS:
        ensure_timer(timer, report["actions"], report["checks"])
    recover_failed_research(report["actions"], report["checks"])
    report["overall_state"] = "needs_attention" if any(item.get("state") == "needs_attention" or item.get("ok") is False for item in report["checks"] + report["actions"]) else "healthy"
    state["last_report"] = report
    write_json(STATE_FILE, state)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["overall_state"] == "needs_attention" else 0


if __name__ == "__main__":
    sys.exit(main())
