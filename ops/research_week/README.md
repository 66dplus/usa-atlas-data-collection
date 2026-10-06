# USA Atlas continuous research cycle

Three independent Codex research topics run every day in `Europe/Berlin`:

| Topic | Time | Main focus |
| --- | ---: | --- |
| `wealth-datacenters` | 10:00 | State estimates for millionaires, billionaires and operating data centers |
| `state-facts` | 11:30 | Source-backed state stories, media leads, collections and comparison ideas |
| `medical-data` | 13:00 | HIV, cancer, infant/child mortality, hepatitis and other accessible measures |

The schedule has **no end date**. Each topic runs at most once per day for up to
45 minutes. A failed launched session may get one bounded retry; the runner
limits each topic to two attempts per Berlin calendar day. A successful,
partial or source-blocked result is not retried automatically. Research sources,
definitions, missing values and limitations remain in each topic's README,
queues and source register.

## Health monitoring and recovery

`usa-atlas-continuous-monitor.timer` runs every 30 minutes. It keeps the three
research timers enabled, retries a failed daily research run within the runner's
two-attempt limit, and checks the isolated mobile prototype containers, local
HTTP page and current public tunnel URL. It can start stopped prototype
containers, restart the local app after a failed local probe, and restart a
repeatedly unreachable tunnel with a two-hour cooldown. If a Quick Tunnel URL
changes, the monitor updates `mobile-lab/preview.json` and
`research/2026-10-03/research-week.json`.

The existing `usa-atlas-scraper-watchdog.timer` independently checks collection
workers every two minutes and applies its existing bounded recovery policy.
The 15-minute admission pipeline and scheduled catalog refreshes remain owned
by their existing systemd timers.

Check current state and logs:

```bash
systemctl list-timers --all 'usa-atlas-*' --no-pager
systemctl status usa-atlas-continuous-monitor.timer
journalctl -u usa-atlas-continuous-monitor.service -n 100 --no-pager
```

To stop only the research and 30-minute monitor schedules:

```bash
systemctl disable --now usa-atlas-research-wealth.timer usa-atlas-research-facts.timer usa-atlas-research-medical.timer usa-atlas-continuous-monitor.timer
```

## Receipts and runtime

The runner is `runner.py`; its existing authenticated Codex CLI session is used
with live web search, a 45-minute session limit and isolated topic write paths.
It makes no LLM calls from the 30-minute monitor unless a daily run has failed
and is eligible for its single retry. Receipts, run events, prompts and state
are under the ignored `runtime/` directory. The monitor's latest state is
`/var/lib/usa-atlas-continuous-monitor/state.json`; its journal records each
check and any recovery action.

Research artifacts are under `research/2026-10-03/<topic>/`. The folder name
records the seed date; it does not limit the ongoing schedule.
