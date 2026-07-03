---
name: headspin-waterfall
description: Download and inspect a HeadSpin session's Waterfall network data and captured artifacts — the HAR network waterfall, screen-recording MP4, device event log (device.log.gz), and PCAP. LIVE-VALIDATED 2026-07-02 against real captured sessions (real 3.1 MB MP4, 36 KB device syslog, real timeseries CSVs streamed to disk) via the bundled MCP tool hs_session_download. Invoke when the user asks for the Waterfall, the network HAR, the session video/screen recording, the device log / "what happened on the device", or wants to download session artifacts.
allowed-tools: [Read, Bash, Grep]
---

# headspin-waterfall

Download a capture session's **Waterfall network data** and other captured artifacts to disk,
then inspect them. The Waterfall in the HeadSpin UI is backed by the session's HAR (network
timing) plus the issue card (`headspin-reports`); this skill retrieves the raw data.

> **Real bytes, real capture.** LIVE-VALIDATED 2026-07-02
> (`e2e-evidence/headspin-forge-260702/v11-report-validation/03-real-artifacts.txt`): a real
> session downloaded a **3,124,416-byte MP4** (magic bytes `ftyp`, h264, 1170×2532@29.99fps) and a
> **36,299-byte `device.log.gz`** that gunzips to real iOS syslog
> (`iPhone runningboardd(RunningBoard)[34] <Notice>: Removing process …`). All via the bundled
> `hs_session_download` MCP tool (`GET /v0/sessions/{sid}.{ext}`, Bearer).

## When to use

- The user asks for the **Waterfall** or the **network HAR** of a session.
- The user wants the session **video / screen recording** (MP4).
- The user wants the **device log** ("what happened on the device") or PCAP.
- `headspin-reports` has surfaced an issue and the user wants the underlying capture.

## Prerequisites

- `headspin-login` has run; `HS_API_TOKEN` + `HS_API_HOST` set; the `headspin` MCP server enabled.
- A `session_id` (from `hs_list_sessions` via `headspin-reports`, or the user).

## Workflow

### 1. Confirm the artifact exists

Before downloading a large file, check what the session has:

```
hs_session_video_metadata { "session_id": "<sid>" }     # 200 => has an MP4 (dims/fps/duration)
hs_session_timeseries_info { "session_id": "<sid>" }     # what device signals were captured
```

A 404 on `video_metadata` means the session is network-only (no screen recording) — download HAR /
device log instead of MP4.

### 2. Download the Waterfall network data (HAR)

```
hs_session_download { "session_id": "<sid>", "ext": "har", "enhanced": true }
```

`ext:"har"` is the **network waterfall** — standardized HTTP Archive JSON (`log.entries[]` with
request/response timing). `enhanced:true` adds HTTP request/response bodies (HTTP/1.x only). The
file streams to disk; the tool returns `{saved_to, bytes, content_type}` — never the bytes. Then
read + summarize:

```bash
# entries, slowest requests, status distribution
python3 - "<saved_to>" <<'PY'
import json,sys
h=json.load(open(sys.argv[1])); e=h.get("log",{}).get("entries",[])
print("entries",len(e))
slow=sorted(e,key=lambda x:x.get("time",0),reverse=True)[:5]
for x in slow: print(round(x.get("time",0)),x["request"]["method"],x["response"]["status"],x["request"]["url"][:70])
PY
```

If the session has no HAR (network capture disabled), the endpoint returns a small
`404 "Could not find a HAR file"` body — report "no network waterfall for this session".

### 3. Download other artifacts

```
hs_session_download { "session_id":"<sid>", "ext":"mp4" }            # screen recording (optionally "fps": 15)
hs_session_download { "session_id":"<sid>", "ext":"device.log.gz" }  # device event log (gunzip to read)
hs_session_download { "session_id":"<sid>", "ext":"pcap" }           # raw packet capture (+ sslkeylog.txt to decrypt)
hs_session_download { "session_id":"<sid>", "ext":"appium.log.gz" }  # Appium driver log
```

Valid `ext` values: `har`, `mar`, `csv`, `mp4`, `pcap`, `device.log.gz`, `appium.log.gz`,
`selenium.log.gz`, `jsconsole.log.gz`, `sslkeylog.txt`. Downloads go under `HS_DOWNLOAD_DIR`
(default `/tmp/headspin-control/downloads/`) or a `save_path` you pass.

### 4. Point the user at the UI Waterfall

The interactive Waterfall lives at `https://<ui_host>/sessions/<sid>/waterfall`. Offer that URL
alongside the downloaded data so the user can open the visual timeline.

## Output format

```
Waterfall for session <sid[:8]>:
  HAR: <n> requests, slowest <ms> (<url>), <n> non-2xx
  Video: <dims>@<fps>, <dur>s, <MB> MB  → <saved_to>
  Device log: <KB> KB (gzip)  → <saved_to>
  UI: https://<ui_host>/sessions/<sid>/waterfall
```

Never inline a multi-MB file into chat. Summarize; cite the `saved_to` path. Redact any tokens,
device serials, or owner emails that appear in logs.

## Evidence

- Real artifact downloads (MP4 3.1 MB `ftyp`-valid, device.log.gz 36 KB → real syslog, timeseries
  CSVs): `e2e-evidence/headspin-forge-260702/v11-report-validation/03-real-artifacts.txt` +
  `04-artifact-integrity.txt` + `VERDICT.md`.
- Download-data API (ext list, har `enhanced`, mp4 `fps`): `headspin-docs/api-reference/session-api.md:359-438`.
- Waterfall UI URL shape: `headspin-docs/api-reference/session-api.md:340` (import→`/sessions/{id}/waterfall`).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `hs_session_download ext=har` → 404 | Session captured no network / no HAR | Report "no network waterfall"; try device.log / mp4. |
| `hs_session_download ext=mp4` → 404 | Network-only session (no screen recording) | Confirm with `hs_session_video_metadata` first. |
| Download very large / slow | Full MP4 or PCAP | Use `"fps"` to resample MP4; warn the user before large PCAP pulls. |
| PCAP unreadable | Encrypted TLS | Also download `ext:"sslkeylog.txt"` and decrypt in Wireshark. |
| `HS_API_TOKEN` empty | `headspin-login` not run | Re-run `/headspin:login`. |
