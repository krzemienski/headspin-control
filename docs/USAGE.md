# headspin-control — Usage Examples (v1.1)

Every example below shows **real request → real response** captured against live
`api-dev.headspin.io` on 2026-07-02 (evidence:
`e2e-evidence/headspin-forge-260702/`). Session IDs, byte counts, and series names
are actual values, not invented. Device serials and owner emails are redacted to
their first 8 characters.

Sections:

1. [Login + environment](#1-login--environment)
2. [Device roster + device control](#2-device-roster--device-control)
3. [Device locking (reservation)](#3-device-locking-reservation)
4. [Sessions: list what was captured](#4-sessions-list-what-was-captured)
5. [HeadSpin reports: the Waterfall issue card](#5-headspin-reports-the-waterfall-issue-card)
6. [Device event visibility: time series](#6-device-event-visibility-time-series)
7. [Waterfall + artifacts: HAR, MP4, device log, PCAP](#7-waterfall--artifacts-har-mp4-device-log-pcap)
8. [Complete workflows](#8-complete-workflows)
9. [UI control boundaries (what needs a browser credential)](#9-ui-control-boundaries)
10. [Validation pattern (prove it yourself)](#10-validation-pattern)

---

## 1. Login + environment

### Slash command

```
/headspin:login hs_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX api_host=https://api-dev.headspin.io
```

### What actually happens

`GET /v0/logindetails` is **unauthenticated** — a `200` proves reachability only.
Token validity is proven by the first Bearer-authed call:

```
hs_login_details {}
→ 200 {"status":"ok", ...org/env config...}          # host reachable (NOT token-valid)

hs_list_devices {}
→ 200 {"devices":[...33 devices...]}                  # Bearer accepted → token VALID
```

A `401` on `hs_list_devices` = wrong token or wrong host. There is no
`orgkey:token` header format — that is fabricated in some third-party docs; only
`Authorization: Bearer <token>` works (HAR-verified).

---

## 2. Device roster + device control

### List every device in the org

```
hs_list_devices {}
```

Real response shape (one of the 34 devices returned live on 2026-07-02,
`func-validation-260702b/VERDICT.md`; redacted):

```json
{
  "devices": [
    {
      "serial": "00008030-…",
      "model": "iPhone12,1",
      "manufacturer": "Apple",
      "device_type": "ios",
      "os_version": "17.5.1",
      "hostname": "dev-ca-tor-0-proxy-3-mac",
      "status": 3,
      "device_address": "00008030-…@dev-ca-tor-0-proxy-3-mac.headspin.io"
    }
  ]
}
```

`status: 3` = online/ready. `device_type` spans `ios`, `android`, `roku`,
`tizentv`, `safari` — one roster covers every device class.

### Inspect one iOS device

```
hs_idevice_info { "device_address": "00008030-…@dev-ca-tor-0-proxy-3-mac.headspin.io" }
→ lockdownd property dump: ProductType, ProductVersion, DeviceName, …

hs_installer_list { "device_address": "00008030-…@dev-ca-tor-0-proxy-3-mac.headspin.io" }
→ {"data":[ …one raw Info.plist per installed app… ]}
```

Both are iOS-only routes. Android/Roku inventory arrives via the roster
(`hs_list_devices`) — there is no per-device REST dump for them.

---

## 3. Device locking (reservation)

```
hs_lock_device   { "device_address": "<udid>@<proxy-host>.headspin.io" }
hs_unlock_device { "device_address": "<udid>@<proxy-host>.headspin.io" }
```

**Live-corrected gotcha:** a bare `lock_id` UUID in the roster is an *ambient idle
marker* — 13 of 33 online devices carried one at rest with nobody holding them.
A device is actually reserved only when `owner_email` / `session_id` are
populated. Do not treat `lock_id != null` as "busy".

---

## 4. Sessions: list what was captured

### Slash command

```
/headspin:sessions
```

### MCP call

```
hs_list_sessions { "include_all": true, "num_sessions": 20 }
```

Real response (2 of 10 real sessions returned live):

```json
{
  "sessions": [
    {
      "session_id": "968f82b2-7537-11f1-b658-9e1a1e4962e6",
      "session_type": "capture",
      "state": "ended",
      "start_time": "2026-07-01T…",
      "device_address": "00008030-…@dev-ca-tor-0-proxy-3-mac.headspin.io"
    },
    {
      "session_id": "2fa53492-7538-11f1-b049-9e1a1e4962e6",
      "session_type": "capture",
      "state": "ended"
    }
  ],
  "next_token": null
}
```

**`include_all: true` is load-bearing.** The default (`false`) returns *live*
sessions only — in a quiet org that is `{"sessions":[]}`, which looks like an
error but isn't. Ended sessions are where the finished reports live.

---

## 5. HeadSpin reports: the Waterfall issue card

### The issue card (same data as the Waterfall UI)

```
hs_session_issues { "session_id": "2fa53492-7538-11f1-b049-9e1a1e4962e6", "orient": "record" }
→ 200 []
```

An empty `[]` is a **real, valid result**: the analysis ran and found no issues
(Low Frame Rate, Domain Sharding, …). Do not retry it as an error. When issues
exist, each key is a category with Impact Time / Issue Start / Impact% columns.

### Is the report ready?

```
hs_analysis_status { "session_id": "2fa53492-…", "timeout": 0 }
→ 200 {"status": "...", "session_id": "2fa53492-…", "message": "..."}
```

`timeout: 0` = check now, don't block. Pass `"track": "video-quality-mos"` (or
`page-load`, `audio-activity`, …) to wait on one specific analysis. Only cite
issues/time series after status is `done`.

### TLS capture gaps

```
hs_session_tls_exceptions { "session_id": "2fa53492-…" }
→ 200 []          # no hosts broke capture; non-empty = {host: exception_count}
```

---

## 6. Device event visibility: time series

"What occurred on the device" as measurable signals.

### Discover what was captured

```
hs_session_timeseries_info { "session_id": "968f82b2-7537-11f1-b658-9e1a1e4962e6" }
```

Real response — **31 series** on a real video-capture session:

```
battery_current, battery_energy_drain, battery_energy_drain_percent,
blockiness, blurriness, brightness, colorfulness, concurrency, connections,
contrast, download_rate, downsampling_index, impact, impact_kde,
memory_used, memory_used_percent, net_cpu,
network_in_bytes, network_in_bytes_rvi, network_in_bytes_total, network_in_packets,
network_out_bytes, network_out_bytes_rvi, network_out_bytes_total, network_out_packets,
page_content, screen_change, screen_rotation, signal_wifi_rssi,
throughput, video_quality_mos
```

A network-only session returned 6 series (concurrency, connections,
download_rate, throughput, network_in/out_bytes_rvi) — the set scales with what
the capture recorded.

### Download one series as CSV

```
hs_session_timeseries_download { "session_id": "968f82b2-…", "key": "memory_used" }
→ {"saved_to": "/tmp/headspin-control/downloads/968f82b2-…-memory_used.csv", "bytes": 583}
```

Real byte counts from live runs: `memory_used` 583 B, `video_quality_mos` 8.8 KB,
`network_in_bytes_total` 97 B. The CSV streams to disk — the tool returns
`{saved_to, bytes}`, never the raw rows. Read the file to summarize the metric.

---

## 7. Waterfall + artifacts: HAR, MP4, device log, PCAP

### Slash command

```
/headspin:waterfall 968f82b2-7537-11f1-b658-9e1a1e4962e6 ext=mp4
```

### Check what exists first

```
hs_session_video_metadata { "session_id": "968f82b2-…" }
→ 200 {"height": 2532, "width": 1170, "fps": 29.991, "duration_ms": 6535, "codec": "h264", …}
```

A `404` here means network-only session (no screen recording) — expected, not an
error. The same session's real download results:

```
hs_session_download { "session_id": "968f82b2-…", "ext": "mp4" }
→ {"saved_to": "/tmp/headspin-control/downloads/968f82b2-….mp4",
   "bytes": 3124416, "content_type": "video/mp4"}
# magic bytes[4:8] = b'ftyp' → VALID MP4 (real screen recording)

hs_session_download { "session_id": "968f82b2-…", "ext": "device.log.gz" }
→ {"bytes": 36299, "content_type": "binary/octet-stream"}
# gunzip → real iOS syslog:
#   "Jul  1 15:58:46 iPhone runningboardd(RunningBoard)[34] <Notice>: Removing process: …"

hs_session_download { "session_id": "968f82b2-…", "ext": "har", "enhanced": true }
→ 404 "Could not find a HAR file"        # THIS session captured no network — report that,
                                          # don't retry. Sessions with network capture return
                                          # standard HAR JSON (log.entries[] with timings).
```

Valid `ext` values: `har`, `mar`, `csv`, `mp4`, `pcap`, `device.log.gz`,
`appium.log.gz`, `selenium.log.gz`, `jsconsole.log.gz`, `sslkeylog.txt`.
Options: `enhanced: true` (har — include HTTP bodies), `fps: 15` (mp4 — resample).
Downloads land under `HS_DOWNLOAD_DIR` (default `/tmp/headspin-control/downloads/`).

### Summarize a HAR after download

```bash
python3 - "<saved_to>" <<'PY'
import json, sys
h = json.load(open(sys.argv[1])); e = h.get("log", {}).get("entries", [])
print("entries", len(e))
for x in sorted(e, key=lambda x: x.get("time", 0), reverse=True)[:5]:
    print(round(x.get("time", 0)), x["request"]["method"],
          x["response"]["status"], x["request"]["url"][:70])
PY
```

### The interactive UI Waterfall

Offer alongside the raw data: `https://<ui_host>/sessions/<sid>/waterfall`.

---

## 7.5 Capture lifecycle: record a session end-to-end (v1.2.0)

LIVE-VALIDATED 2026-07-03 — three ~5-min YouTube captures on real Samsung devices
(`e2e-evidence/headspin-forge-260703/session-validation/`).

```
hs_adb_lock          { "device_id": "RFCN80FV2TA", "timeout": 30 }
hs_start_capture     { "device_address": "RFCN80FV2TA@dev-ca-tor-0-proxy-20-lin.headspin.io" }
hs_adb_shell         { "device_id": "RFCN80FV2TA", "command": "am start -a android.intent.action.VIEW -d https://www.youtube.com/shorts -n com.google.android.youtube/.UrlActivity" }
hs_adb_shell         { "device_id": "RFCN80FV2TA", "command": "input swipe 400 1400 400 400 200" }   # repeat ~every 10 s
hs_stop_capture      { "session_id": "<sid>" }
hs_session_timestamps{ "session_id": "<sid>" }   # poll for capture-complete
hs_adb_unlock        { "device_id": "RFCN80FV2TA" }
```

Real responses observed (2026-07-03): lock -> `{"status": 0, "message": "... locked."}`;
start -> `{"session_id": "6e163540-..."}`; shell -> `{"status": 0, "stdout": "..."}`;
stop -> MP4 upload message. The resulting session `6e163540` produced a 104,845,566-byte
h264 MP4 (287.7 s), 11 issue cards, and 51 time series.

Hard-won constraints:
- Device MUST be locked before `hs_start_capture` (unlocked -> 500).
- A device that just ended a capture 500s on immediate restart — back off ~90 s.
- Dismiss the notification shade and verify `mCurrentFocus` shows the target app
  (`dumpsys window | grep mCurrentFocus`) before driving; a shade-blocked launch
  records a lock-screen video.
- MP4 downloaded immediately after capture-complete can be PARTIAL (container header
  claims full duration, few packets). Check `ffprobe -count_packets` ≈ duration × fps.

## 8. Complete workflows

### "What did that test run find?" (report retrieval, end to end)

```
1. hs_list_sessions {"include_all": true, "num_sessions": 20}   # find the session
2. hs_analysis_status {"session_id": "<sid>", "timeout": 0}     # report ready?
3. hs_session_issues {"session_id": "<sid>", "orient": "record"} # the issue card
4. hs_session_timeseries_info {"session_id": "<sid>"}           # available KPIs
5. hs_session_timeseries_download {"session_id":"<sid>","key":"video_quality_mos"}
6. hs_session_tls_exceptions {"session_id": "<sid>"}            # capture gaps
```

Output as a short report:

```
Session 968f82b2 on 00008030-…@dev-ca-tor-0-proxy-3-mac (ended, 2026-07-01)
Issues: none detected (issue card empty — valid clean result)
Video: 1170×2532 @ 29.99 fps, 6.5 s, h264
Signals: 31 series (memory, battery, net_cpu, video_quality_mos, …)
Artifacts: mp4 3.1 MB ✓, device.log.gz 36 KB ✓, HAR — none (no network capture)
UI: https://ui-dev.headspin.io/sessions/968f82b2-…/waterfall
```

### "Something looked wrong on the device — what happened?"

```
1. hs_session_download {"session_id":"<sid>","ext":"device.log.gz"}
2. gunzip -c <saved_to> | grep -iE "crash|kill|jetsam|watchdog|error"
3. hs_session_timeseries_download {"session_id":"<sid>","key":"memory_used"}
4. hs_session_download {"session_id":"<sid>","ext":"mp4","fps":15}   # visually confirm
```

Cross-reference the syslog timestamps with the memory CSV and the recording —
three independent views of the same seconds.

### "Explore a device for bugs, then file reports"

```
/headspin:devices              # pick an online device (status 3)
/headspin:connect <serial>     # lock + open control channel
/headspin:explore              # bounded BFS crawl, evidence bundles
/headspin:report <run-dir>     # standardized bug reports from the run
```

---

## 9. UI control boundaries

Two credential classes exist (HAR-proven, live-probed):

| Plane | Credential | Plugin support |
|---|---|---|
| REST (all 20 tools above) | account **API token** (Bearer) | ✅ full |
| socket.io control / Janus video / iOS WS :5002 | **identity JWT** from browser login | ❌ gated |

The API token can mint a *lease* JWT (`POST /v0/jwt/permissions`) but the
control planes reject it: live probe got HTTP 101 upgrade then
`"Failed to decode jwt access_token."`. Real-time UI control (tap/swipe
streaming) therefore requires the browser-issued identity JWT — a platform
boundary, not a plugin bug. Device *interaction* is still available through
Appium (all device types) via the documented Appium endpoint with the 32-hex
token in the URL path.

---

## 10. Validation pattern

Prove any of this yourself in one stdio round-trip (no mocks — every call hits
the live API):

```bash
export HS_API_TOKEN=…  HS_API_HOST=https://api-dev.headspin.io
python3 - <<'PY'
import json, subprocess
p = subprocess.Popen(["python3", "mcp/headspin_mcp_server.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def rpc(m, params=None, i=1):
    p.stdin.write(json.dumps({"jsonrpc":"2.0","id":i,"method":m,"params":params or {}})+"\n")
    p.stdin.flush(); return json.loads(p.stdout.readline())
rpc("initialize", {"protocolVersion":"2024-11-05","capabilities":{},
                   "clientInfo":{"name":"probe","version":"0"}})
r = rpc("tools/call", {"name":"hs_list_sessions",
                       "arguments":{"include_all":True,"num_sessions":5}}, 2)
print(r["result"]["content"][0]["text"][:400])
PY
```

Evidence for every claim in this document:
`e2e-evidence/headspin-forge-260702/v11-report-validation/` (`01`–`04` + `VERDICT.md`).
