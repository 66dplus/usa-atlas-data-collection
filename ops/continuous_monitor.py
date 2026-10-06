#!/usr/bin/env python3
"""Check ongoing USA Atlas research timers and the isolated mobile prototype.

The existing scraper watchdog remains responsible for bounded recovery of
collection workers. This monitor repairs only the allowlisted research timers,
failed research attempts, and the separate mobile-lab containers and URL.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT.parent / "usa-atlas-design-lab" / "mobile-lab"
PREVIEW = UI / "preview.json"
WEEK_STATUS = ROOT / "research/2026-10-03/research-week.json"
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
APP_CONTAINER = "usa-atlas-mobile-lab-app"
TUNNEL_CONTAINER = "usa-atlas-mobile-lab-tunnel"
COMPOSE = ["docker", "compose", "-f", str(UI / "compose.yaml"), "-p", "usa-atlas-mobile-lab"]
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


def docker_running(container):
    result = invoke(["docker", "inspect", "--format", "{{.State.Running}}", container])
    if not result or result.returncode != 0:
        return None
    return result.stdout.strip().lower() == "true"


def ensure_containers(actions, checks):
    missing = [name for name in (APP_CONTAINER, TUNNEL_CONTAINER) if docker_running(name) is None]
    if missing:
        result = invoke(COMPOSE + ["up", "-d", "--no-build"], timeout=90, cwd=UI)
        actions.append({"component": "mobile_lab", "action": "compose_up_missing_containers", "ok": bool(result and result.returncode == 0)})
    for name in (APP_CONTAINER, TUNNEL_CONTAINER):
        running = docker_running(name)
        if running is False:
            result = invoke(["docker", "start", name], timeout=30)
            running = docker_running(name)
            actions.append({"component": name, "action": "start_stopped_container", "ok": bool(result and result.returncode == 0 and running)})
        checks.append({"component": name, "state": "healthy" if running else "needs_attention"})


def probe(url, timeout=10):
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return {"ok": False, "reason": "invalid_url"}
    request = Request(url, headers={"User-Agent": "USA-Atlas-Monitor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read(4096)
            return {"ok": 200 <= response.status < 400, "status": response.status}
    except HTTPError as exc:
        return {"ok": False, "status": exc.code}
    except (URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "reason": type(exc).__name__}


def update_public_url(url):
    preview = read_json(PREVIEW)
    preview.update(url=url, observed_at=stamp(), status="running")
    write_json(PREVIEW, preview)
    week = read_json(WEEK_STATUS)
    mobile = week.get("mobile_prototype")
    if isinstance(mobile, dict):
        mobile["url"] = url
        mobile["last_health_check_at"] = stamp()
        write_json(WEEK_STATUS, week)


def latest_tunnel_url():
    result = invoke(["docker", "logs", "--tail", "100", TUNNEL_CONTAINER], timeout=20)
    if not result:
        return None
    matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", result.stdout + "\n" + result.stderr)
    return matches[-1] if matches else None


def check_mobile(state, actions, checks):
    local_result = probe("http://127.0.0.1:4199/", timeout=8)
    if not local_result["ok"]:
        time.sleep(3)
        local_result = probe("http://127.0.0.1:4199/", timeout=8)
    if not local_result["ok"]:
        restart = invoke(["docker", "restart", APP_CONTAINER], timeout=30)
        time.sleep(4)
        local_result = probe("http://127.0.0.1:4199/", timeout=8)
        actions.append({"component": APP_CONTAINER, "action": "restart_after_local_http_failure", "ok": bool(restart and restart.returncode == 0 and local_result["ok"])})
    checks.append({"component": "mobile_lab_local_http", **local_result})
    if not local_result["ok"]:
        return

    preview = read_json(PREVIEW)
    url = preview.get("url")
    public_result = probe(url)
    if not public_result["ok"]:
        time.sleep(4)
        public_result = probe(url)
    if not public_result["ok"]:
        last_restart = state.get("last_tunnel_restart_at")
        try:
            age = (now() - datetime.fromisoformat(last_restart)).total_seconds() if last_restart else 10**9
        except (ValueError, TypeError):
            age = 10**9
        if age >= 7200:
            restart = invoke(["docker", "restart", TUNNEL_CONTAINER], timeout=40)
            state["last_tunnel_restart_at"] = stamp()
            time.sleep(8)
            new_url = latest_tunnel_url()
            if new_url:
                url = new_url
                update_public_url(url)
            public_result = probe(url, timeout=15)
            actions.append({"component": TUNNEL_CONTAINER, "action": "restart_after_repeated_public_http_failure", "new_url_found": bool(new_url), "ok": bool(restart and restart.returncode == 0 and public_result["ok"])})
        else:
            public_result = {**public_result, "reason": "restart_cooldown_active"}
    checks.append({"component": "mobile_lab_public_tunnel", "url": url, **public_result})


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    state = read_json(STATE_FILE)
    report = {"checked_at": stamp(), "checks": [], "actions": [], "scope": "research timers and isolated mobile-lab only"}
    for timer in RESEARCH_TIMERS:
        ensure_timer(timer, report["actions"], report["checks"])
    recover_failed_research(report["actions"], report["checks"])
    ensure_containers(report["actions"], report["checks"])
    check_mobile(state, report["actions"], report["checks"])
    report["overall_state"] = "needs_attention" if any(item.get("state") == "needs_attention" or item.get("ok") is False for item in report["checks"] + report["actions"]) else "healthy"
    state["last_report"] = report
    write_json(STATE_FILE, state)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["overall_state"] == "needs_attention" else 0


if __name__ == "__main__":
    sys.exit(main())
