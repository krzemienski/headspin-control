---
name: headspin-reports
description: Retrieve HeadSpin performance reports, Waterfall issue-card data, and device time series for a capture session. LIVE-VALIDATED 2026-07-02 against real captured sessions on api-dev.headspin.io — all Bearer REST via the bundled MCP server (hs_list_sessions, hs_session_issues, hs_analysis_status, hs_session_timeseries_info/download, hs_session_video_metadata, hs_session_tls_exceptions). Invoke when the user asks for a HeadSpin report, "what were the issues on that session", performance/KPI data, the Waterfall issue card, device time series (memory/battery/network/video-quality), or wants to know what a session found.
allowed-tools: [Read, Bash, Grep]
---

# headspin-reports

Retrieve HeadSpin **reports** for a capture session: the Waterfall issue card (performance
issues), analysis status, and the device time series that back the report.

> **All of this is real Bearer REST**, exposed by the bundled MCP server. LIVE-VALIDATED
> 2026-07-02 against real captured sessions (`e2e-evidence/headspin-forge-260702/v11-report-validation/VERDICT.md`):
> a video session returned **31 real time series** (memory, battery, net_cpu, video_quality_mos, …)
> and its issue card / analysis-status endpoints returned real 200 responses.

## When to use

- The user asks for a HeadSpin **report** on a session, or "what did that session find".
- The user wants the **Waterfall issue card** data (Low Frame Rate, Domain Sharding, …).
- The user wants device **time series** / KPIs (memory, battery, network throughput, video quality).
- The user wants to know whether a session's analyses have finished.

## Prerequisites

- `headspin-login` has run; `HS_API_TOKEN` (Bearer) + `HS_API_HOST` are set.
- The bundled `headspin` MCP server is enabled (`.mcp.json`). Every tool below is one of its tools.

## Workflow

### 1. Find the session

```
hs_list_sessions { "include_all": true, "num_sessions": 20 }
```

Returns `{"sessions":[{session_id, device_id, device_address, session_type, state, start_time,
error_code}], "next_token":...}`. `include_all:true` includes **ended** sessions (the ones with
finished reports); default `false` is live-only. Pick the `session_id` the user means (most
recent, or matched by device / time).

### 2. Pull the Waterfall issue card (the core report)

```
hs_session_issues { "session_id": "<sid>", "orient": "record" }
```

This is the **same data shown in the HeadSpin Waterfall UI issue card** (`GET
/v0/sessions/analysis/issues/{sid}`). `orient` is `column` (default) or `record`. Each key is an
issue category — e.g. `Low Frame Rate` (Impact Time, Issue Start, Impact/Total %), `Domain
Sharding` (Domain, Total/Impact Connection Time). An empty `{}`/`[]` means the analysis found no
issues (a real, valid result — not an error).

### 3. Check analysis status (is the report ready?)

```
hs_analysis_status { "session_id": "<sid>", "timeout": 0 }
```

`timeout:0` checks the current state without blocking → `{status: done|timeout|error, message}`.
Optionally `"track": "video-quality-mos"` (or `page-load`, `audio-activity`, …) to wait on one
analysis. Only report issues/time series once status is `done`.

### 4. Read the device time series that back the report

```
hs_session_timeseries_info { "session_id": "<sid>" }
```

Returns a dict of available series, each with `name`/`category`/`units` — e.g. `memory_used` (MiB,
device), `impact` (impacts), `frame_rate`, `video_quality_mos`, `throughput`, `battery_current`,
`network_in_bytes_total`. Then download any one as CSV:

```
hs_session_timeseries_download { "session_id": "<sid>", "key": "memory_used" }
```

The CSV streams to disk; the tool returns `{saved_to, bytes}` (never the raw CSV — it can be large).
Read the saved file to summarize the metric over the session timeline.

### 5. Video metadata + TLS gaps (report context)

```
hs_session_video_metadata { "session_id": "<sid>" }     # dims, fps, duration, codec, audio
hs_session_tls_exceptions { "session_id": "<sid>" }      # {host: count} — hosts that broke capture
```

`video_metadata` 404s for a network-only session (no screen recording) — that is correct, not an
error. `tls_exceptions` surfaces hosts whose TLS pinning blocked network capture (a real waterfall
gap signal).

## Output format

Summarize as a short report, not a JSON dump:

```
Session <sid[:8]> on <device_address> (<state>, started <time>)
Issues: <n categories> — <top issue + its Impact/Total %>
Analysis: <done|pending>
Key metrics: memory <peak> MiB, video-quality MOS <median>, throughput <peak>
Artifacts available: <mp4 / har / device.log>   (see headspin-waterfall to download)
```

Redact device serials / owner emails to their first 8 chars in any shared output.

## Evidence

- Live validation of every tool against real captured sessions:
  `e2e-evidence/headspin-forge-260702/v11-report-validation/VERDICT.md` and
  `01-report-surface-live.txt` (6 real network series), `03-real-artifacts.txt` (31 series).
- Issue-card endpoint = Waterfall UI data: `headspin-docs/api-reference/session-api.md:520-527`
  ("This data is the same as that shown in the Waterfall UI issue card").
- Time series API: `headspin-docs/api-reference/session-api.md:686-793`.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `hs_list_sessions` returns `{"sessions":[]}` | No live sessions (default) | Pass `include_all:true` to include ended sessions. |
| `hs_session_issues` → `{}` / `[]` | Session has no detected issues | Valid result — report "no issues found", don't treat as error. |
| `video_metadata` isError 404 | Network-only session (no screen recording) | Expected; report "no video for this session". |
| `analysis_status` → `timeout` | Analyses still running | Poll again with a longer `timeout`, or report "analysis pending". |
| `HS_API_TOKEN` empty | `headspin-login` not run | Re-run `/headspin:login`. |
