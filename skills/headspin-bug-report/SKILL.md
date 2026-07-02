---
name: headspin-bug-report
description: Turn a HeadSpin exploration evidence run into standardized, file-a-device-bug reports. Use for "file a device bug report", "headspin bug", "write up a bug from exploration evidence", "make a bug report", "turn crashes into tickets", or after headspin-explore-bugs finds anomalies. Reads an exploration run directory and emits one BUG-{n}.md + BUG-{n}.json per anomaly — device context, verbatim repro steps, expected vs actual, evidence paths, and the HeadSpin session URL/video link. Token stays keychain-only and is never written into a report.
allowed-tools: Read, Bash, Grep
---

# headspin-bug-report

## When to use

- User runs `/headspin:bug-report` or asks to "file a device bug / write up a bug".
- `headspin-explore-bugs` just produced anomaly evidence to turn into tickets.
- You have a run directory and need shareable, redacted BUG-{n} artifacts.

## Scope

- **In scope:** reading an exploration run dir, deriving severity, formatting the
  report (markdown + JSON sidecar), linking the session URL/video, emitting one
  report per anomaly.
- **Out of scope:** discovering the bugs (`headspin-explore-bugs`), driving the
  device (`headspin-control-*`), and submitting the report to an external tracker
  (Jira/GitHub) — this skill produces the artifact; filing it elsewhere is a
  separate, explicit step.

## Security policy

- Token from the plugin config ONLY (`$CLAUDE_PLUGIN_OPTION_API_TOKEN`,
  keychain-backed). It is NEVER read, needed, or written by this skill — report
  generation is offline over local evidence files.
- REDACT before writing: if any evidence field contains an API token or a
  token-in-path `driver_url` (`/v0/{TOKEN}/wd/hub`), replace the token with `***`.
  A bug report is a shareable artifact — it must carry zero secrets.

## Report schema

Each anomaly yields two files.

**`BUG-{n}.md`** (see `assets/report-template.md`):

```
# BUG-{n}: {title}

- **Severity:** {critical|high|medium|low}
- **Device:** {device_address}  ({device_type}, OS {os_version})
- **App:** {app_id}
- **Session:** https://ui.headspin.io/sessions/{session_id}
- **Video:** https://{api}/v0/sessions/{session_id}.mp4
- **Detected:** {ISO-8601 timestamp}

## Repro Steps
1. {verbatim action from action_log.json}
...

## Expected vs Actual
- **Expected:** {inferred normal outcome}
- **Actual:** {anomaly signal — crash / error text / stuck screen / not foreground}

## Evidence
- screenshot / page source / ocr / log tail: {paths}

## Environment
- api base / run id / signal
```

**`BUG-{n}.json`** — the same fields as structured data (`id`, `title`,
`severity`, `device{}`, `app_id`, `repro_steps[]`, `expected`, `actual`,
`evidence{}`, `session_url`, `video_url`, `environment{}`). A `bugs-index.json`
lists all emitted reports.

## Severity mapping (from anomaly signal)

| Signal | Severity | Rationale |
|--------|----------|-----------|
| `crash_driver_death` | critical | app/session died — hard stop |
| `error_text_ocr` / `error_text_page_source` | high | user-visible error surfaced |
| `app_not_foreground` | high | app kicked out / backgrounded unexpectedly |
| `stuck_screen` | medium | frozen / dead-end, no hard crash |

## Quick start

```bash
# Emit BUG-*.md + BUG-*.json for every anomaly in a run directory.
python3 "${CLAUDE_PLUGIN_ROOT}/skills/headspin-bug-report/scripts/make_report.py" \
  ./headspin-exploration/20260702-141530 \
  --app-id com.example.app \
  --api "${CLAUDE_PLUGIN_OPTION_API_HOST#https://}"
```

Output lands next to the anomalies in the run dir; `bugs-index.json` indexes them.
The `--api` value is only used to build the video URL — no token, no live call.

## Workflow position

```
headspin-explore-bugs  →  {run-dir}/anomaly-*/{screenshot,page_source,ocr,log_tail,meta}
        │
        ▼
headspin-bug-report    →  {run-dir}/BUG-{n}.md + BUG-{n}.json + bugs-index.json
```

## Evidence

- Session URL / video link shape (`https://ui.headspin.io/sessions/{id}`,
  `/v0/sessions/{id}.mp4`): `plans/260702-headspin-skills/SYNTHESIS.md` §9.
- Device context fields (`device_type`, `os_version`) resolved from the device
  record: `headspin-docs/api-reference/devices-api.md:39-65`.

## Related skills

- `headspin-explore-bugs` — produces the evidence bundles this skill reads (run FIRST).
- `headspin-session-manager` — the lock/session under which the video was captured.
- `headspin-connection-manager` — the control session the bug was found on (Android drives socket.io `input.*` on `dev-ca-tor-0`; iOS drives `CONTROL_TOUCH_PATHS` on `dev-in-blr-0:5002`). `device_type` in a report is Android or iOS; Roku is doc-only and not exercised in this environment.
- `headspin-list-devices` — resolve `device_type` / `os_version` device context.

## Resources

- `scripts/make_report.py` — reads a run dir → emits BUG-{n}.md + BUG-{n}.json per
  anomaly, with token / driver_url redaction. Offline; no token needed.
- `assets/report-template.md` — the markdown report template (placeholders filled
  per anomaly).
