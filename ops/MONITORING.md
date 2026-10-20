# Continuous scraper monitoring

Installed on 28 September 2026. `usa-atlas-scraper-watchdog.timer` is enabled in
systemd: it checks 60 seconds after server boot and every 120 seconds after the
previous check (timer precision 10 seconds). Operation continues after chat
sessions are closed. This is a software watchdog with defined recovery rules;
new source schemas and ambiguous errors call for investigation.

## Control and status

From the data repository root:

```bash
python3 ops/scraper_watchdog.py --status
python3 ops/collection_status.py
systemctl status usa-atlas-scraper-watchdog.timer
journalctl -u usa-atlas-scraper-watchdog.service -n 40 --no-pager
```

`--status` reads the latest report. `--check` inspects current state without
changes; `--check --apply` stores the result and allows recovery. The timer runs
the regular checks; running them manually all the time is unnecessary.
`collection_status.py` marks a report older than five minutes as stale.

The first installed run at 19:07 UTC: `overall_state=healthy`,
`needs_attention=[]`, no automatic restarts needed.

## What is monitored

| Process | Watchdog action |
| --- | --- |
| ACS, CDC, ACS alternatives, federal bulk | Checks completion and files. Resumes stopped unfinished jobs after a temporary error or unexpected exit |
| Local portals | Checks systemd, PID, process identity, heartbeat and progress. Recovers a stopped service; on a confirmed stall restarts it in an orderly way |
| Regional refresh | Checks the service, enabled timer, code and unit hashes, completion of the three sets and snapshot freshness; recovery is handled by systemd |
| Nationwide discovery | Checks the service, enabled timer, code and unit hashes, completion of the 52-catalog sweep, cycle freshness and source errors; recovery is handled by systemd |
| PWC buildings | Checks the weekly timer, hashes, a successful snapshot, artifact existence and sizes; the freshness threshold is eight days |
| Database cleanup | Reads the checkpoint and checks the process; records `needs_attention` on a problem |

The local collector publishes a heartbeat from its main thread every 15 seconds
of waiting. While collecting, it marks real requests and progress. An orderly
six-hour wait gets status `idle`. A missing heartbeat or stalled progress within
30 minutes justifies recovery; a next cycle more than 15 minutes late is also
detected.

A long-running active ACS/public worker without progress for over an hour gets
`needs_attention`; its forced termination is not automated. For long database
migration phases the checkpoint threshold is six hours. Migration is never
restarted automatically and is never terminated by the watchdog.

## New periodic jobs: 29 September

Three additional timers were installed and enabled. The regional service and
nationwide first ran on **29 September 2026 at 14:01:33 UTC**. PWC reuses the
already collected 14:11 UTC snapshot; installing its timer did not re-download
it.

| Service and identically named `.timer` | Schedule | Limits |
| --- | --- | --- |
| `usa-atlas-regional-refresh.service` | Daily at **03:15 UTC**; `Persistent=true` runs a missed start after the server is powered on | Three starts per hour, 300-second pause, service limit 1800 seconds; the wrapper bounds the child process to 1500 seconds |
| `usa-atlas-nationwide-discovery.service` | **6 hours after** the previous run completes; first check 120 seconds after server boot | Three starts per hour, 900-second pause, service limit 3900 seconds; the wrapper bounds the child process to 3600 seconds |
| `usa-atlas-pwc-refresh.service` | Sundays at **03:45 UTC**, `Persistent=true` | Three starts per hour, 300-second pause, service limit 1800 seconds; a separate snapshot per run and a global `flock` |

The regional wrapper keeps a separate snapshot per UTC date. A rerun on the same
day continues that snapshot. The first systemd-run start confirmed completion of
all three sets: Texas reservoirs, Colorado well permits, and Washington electric
vehicles. The data stays as separate research files.

Nationwide picks five search topics from a queue and sweeps **50 states, DC and
PR**. The queue holds 33 groups covering 55 coverage gaps; the extra bootstrap
topic `water` makes 34 topics in rotation. One query repeats no more often than
once per 24 hours. Queue position and completed topics are saved; on error the
unfinished position is preserved. First cycle: `data center`, `electricity`,
`water`, `overdose`, `crime`.

The first sweep finished at 14:02:42 UTC and found an ArcGIS Hub parameter bug:
the API requires `startindex >= 1`. After the fix and an update of the pinned
hashes, one full rerun of the same five topics went through
`usa-atlas-nationwide-discovery-repair.service`. Both historical runs are kept.
The rerun completed at **14:06:03 UTC**:

- 52 jurisdictions, 260 job results, 170 actual search-API pages;
- 900 candidate entries; this is not the number of distinct or admitted datasets;
- query execution errors down to **0** from 85;
- three unrecognized adapters blocked 15 jobs and need review;
- 26 failed HTTP attempts saved as evidence, including attempts before a
  successful alternative adapter was selected.

Then the primary official catalogs for Indiana, Nebraska and Ohio were verified
and replaced; the former addresses remain as historical alternatives. The 14:11
UTC rerun removed the unrecognized adapters but found a single network gap for
Oregon/electricity. After adding a bounded retry for network requests, the final
full sweep completed at **14:14:59 UTC**:

- 52 jurisdictions, 260 job results, **180 search-API pages**;
- **953 candidate entries**;
- **0** query errors, unrecognized adapters or blocked jobs;
- 17 failed HTTP attempts saved, including recovered requests and adapter
  selection attempts. They do not mean 17 incomplete jobs.

The rotation position is preserved: the next query is `accidental deaths`,
cursor 5. The regular service and timer are resumed; the next nationwide start
is 29 September at **20:16:36 UTC**, the next regional start — 30 September at
**03:15 UTC**. PWC will first run on schedule on **4 October at 03:45 UTC**.
As of 14:16:36 UTC the watchdog monitors nine jobs, `overall_state=healthy`,
`needs_attention=[]`.

Planned checks and reruns during installation exhausted the three-start limit of
nationwide, although the service itself did not fail. After reviewing the log,
the operator ran `reset-failed` once for that unit only and restored the
six-hour countdown. The reason and the action are recorded in
`full/runtime/watchdog/events.jsonl`. The automatic watchdog still never resets
systemd limits.

PWC keeps **248 data-center building records** of Prince William County,
Virginia: 57 `Completed`, 31 `Under Construction`, 68 `Pending`, 92 `Planned`.
These are building points and statuses; the count of operating facilities and a
mapping to Census block groups are not derived from them automatically. The
dataset stays research-only, without writing to production.

The nationwide timer counts from completion: fixed calendar 00/06/12/18 UTC
slots would conflict with the wrapper's own six-hour bound. After a reboot the
saved rate bound still applies: an early check may run nothing, then the next
call comes six hours later. The watchdog marks a completed cycle older than
eight hours as needing attention, so such a reboot gap stays visible.

In all three jobs `ExecCondition` calls `--preflight`: a start is allowed only
when the job is enabled, the pinned SHA-256 of code and unit files match, and
free space is at least 12 GiB. Collectors hold their own `flock`; systemd also
never starts a second instance of the same oneshot service. After the systemd
start-limit is exhausted, systemd terminates only that service's processes. The
watchdog does not duplicate restarts of these three jobs and never terminates
them on its own.

Nationwide collects catalog metadata and candidates. It currently reads only the
first bounded page of each topic; next-page information is saved but pagination
is not implemented yet. Candidates require publisher, geography, schema and
license review before observation collection uses them. Query execution errors,
unrecognized adapters and blocked queries are visible in the watchdog as
`completed_discovery_has_source_errors_review_required`, even when the process
exits successfully. The counter of HTTP attempts before a successful fallback is
shown separately and does not raise an alert by itself. This is not considered
country-wide data coverage.

```bash
systemctl list-timers 'usa-atlas*' --no-pager
journalctl -u usa-atlas-regional-refresh.service -n 40 --no-pager
journalctl -u usa-atlas-nationwide-discovery.service -n 40 --no-pager
journalctl -u usa-atlas-pwc-refresh.service -n 40 --no-pager
python3 ops/scraper_watchdog.py --check
```

Current checkpoints:

- `research/2026-09-29/regional-expansion/latest.json` and the summary it names.
- `research/2026-09-29/nationwide-portals/runtime/schedule-state.json`.
- `research/2026-09-29/nationwide-portals/discovery-latest.json` — the last
  fully completed cycle; during the first run the file may not exist yet.
- `research/2026-09-29/data-center-expansion/latest.json` — the latest PWC
  snapshot with its artifact list, source building statuses and checksums.

## Recovery conditions

- Completed jobs are never started again.
- At most three watchdog attempts per process per hour, with a growing pause.
- Local portals also carry a systemd limit: three starts per hour,
  `Restart=on-failure`, 120-second pause. `start-limit-hit` needs investigation.
- Before recovery it checks the SHA-256 of code and unit, PID ownership, kernel
  start time, boot ID and existing locks.
- With less than 12 GiB free disk, automatic restart is forbidden.
- Code changes, schema errors, artifact corruption and unknown failure causes
  call for investigation. They are never worked around by re-downloading.

In the two-minute loop, file checks are limited to existence and size. Checksums
are verified by the collectors themselves as downloads continue. Crashes and a
checkpoint format failure are stored as `needs_attention`. Errors are visible in
the report and the journal; no external notifications are configured.

## Journals and configuration

- `ops/scraper-watchdog.json`: processes, thresholds, resume commands, hashes.
- `full/runtime/watchdog/state.json`: latest report and the hour of attempts.
- `full/runtime/watchdog/events.jsonl`: state changes and actions; rotated after
  2 MiB, one previous file kept.
- `full/runtime/watchdog/*.recovery.log`: output of resumed batch processes.
- `research/2026-09-28/local-portals/runtime/heartbeat.json`: daemon state.

Runtime is excluded from Git. To update code: disable the affected job, prepare
the change and update its hash in the configuration, then enable it again. The
watchdog never accepts new code automatically.

## Planned stop

Before intentionally stopping a scraper, set `enabled: false` for its job in
`ops/scraper-watchdog.json`; then stop the process itself. To service the whole
set, the timer can also be stopped:

```bash
systemctl stop usa-atlas-scraper-watchdog.timer
```

Stopping the timer does not disable the local service's own `Restart=on-failure`.
`systemctl stop usa-atlas-local-portals.service` is the orderly stop for that
service. For a new periodic job, after `enabled: false` also stop its timer and
service, for example:

```bash
systemctl stop usa-atlas-nationwide-discovery.timer usa-atlas-nationwide-discovery.service
```

Stopping only the general watchdog does not turn off the regional/nationwide/PWC
timers. After maintenance, set `enabled: true` back and start the timer. Do not
delete attempt history or reset systemd limits without first identifying the
failure cause.

Unit files are stored next to this document; installed copies live in
`/etc/systemd/system/`. Working paths inside the units refer to the current
server.
