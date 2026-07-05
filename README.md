# HeadSpin Control

A Claude Code plugin for driving real devices on a [HeadSpin](https://www.headspin.io/)
device farm: authenticate to an environment, enumerate and lock devices, connect and
control iOS / Android, run automated exploration, and file standardized bug reports —
through HeadSpin REST, Appium, socket.io, and Janus surfaces.

Every skill and the bundled MCP server call the **real** HeadSpin API. There are no
mocked responses. The plugin was validated against `ui-dev.headspin.io` /
`api-dev.headspin.io` using live captures from the 2026-07-02 session (base HAR +
full-body raw capture; see `e2e-evidence/headspin-forge-260702/`).

> **Roku: control WIRE is doc-sourced, but real Roku devices DO exist here.** No Roku
> traffic appears in either capture, so the `headspin-connect-roku` / `headspin-control-roku`
> connect/drive wire shapes come from HeadSpin's Roku/ECP docs, not observed frames.
> However, a **live `GET /v0/devices` on 2026-07-02 returned 3 online, Appium-drivable Roku**
> (`YH001N51126312` Roku Streaming Stick+, `X02600RUALWE` + `X02600LX08J3` Roku Express;
> driver_url on `:7302`). Separately, the Roku-shaped serial `RFCN80FV2TA` is actually a
> Samsung SM-G981U (Galaxy S20) on Android — not a Roku. Treat the Roku *wire* as doc-sourced;
> the *devices* are real.

> **Live-validated 2026-07-02 (`func-validation-260702b/VERDICT.md`).** All 6 original MCP
> tools were exercised against real `api-dev.headspin.io` (login_details, list_devices→34,
> idevice_info, installer_list, lock, unlock) and the lock lifecycle was proven end-to-end.
> The socket.io and Janus control planes are reachable and TLS-valid but **require the
> browser-login identity JWT / Janus secret**, not the account API token — obtain them via
> `/headspin:login`. Exercising any live path needs a real HeadSpin API token for your
> environment, supplied via config (`api_token` → `HS_API_TOKEN`/`CLAUDE_PLUGIN_OPTION_API_TOKEN`).

> **Full-system proof — 20/20 tools live-validated 2026-07-05
> (`e2e-evidence/headspin-cook-260705/VALIDATION-REPORT.md`).** One run exercised every MCP
> tool against the real API: a complete capture lifecycle on a real Galaxy S10
> (lock → record → drive YouTube → stop → **6,899,682-byte MP4** + "Audio Too Quiet −30.8 LUFS"
> issue card + 16 time series pulled to disk), plus a live lock/unlock cycle on a real
> iPhone 11 proving the iOS REST reservation route. Worked examples below use those
> actual responses.

> **New in 1.1 — sessions, reports, Waterfall, device events (LIVE-VALIDATED 2026-07-02,
> `v11-report-validation/VERDICT.md`).** Bearer-REST MCP tools (20 total in 1.2.0) list capture
> sessions, pull the Waterfall issue card, check analysis status, read/download device time
> series, and download session artifacts. Validated against **real captured sessions**: a
> video session returned **31 real time series** (memory, battery, net_cpu,
> video_quality_mos, …), a **3,124,416-byte valid MP4** screen recording (`ftyp` magic), and
> a **36 KB device.log.gz** that gunzips to real iOS syslog. Two new skills
> (`headspin-reports`, `headspin-waterfall`) and two new commands (`/headspin:sessions`,
> `/headspin:waterfall`). Every example in **[docs/USAGE.md](docs/USAGE.md)** shows the real
> captured request/response.

---

## Component inventory

| Type | Count | Items |
|------|-------|-------|
| Skills | 14 | `headspin-login`, `headspin-list-devices`, `headspin-connect-ios`, `headspin-connect-android`, `headspin-connect-roku`, `headspin-control-ios`, `headspin-control-roku`, `headspin-connection-manager`, `headspin-session-manager`, `headspin-explore-bugs`, `headspin-bug-report`, `headspin-reports`, `headspin-waterfall`, `headspin-capture` |
| Commands | 10 | `/headspin:setup`, `/headspin:login`, `/headspin:devices`, `/headspin:connect`, `/headspin:control`, `/headspin:explore`, `/headspin:report`, `/headspin:sessions`, `/headspin:waterfall`, `/headspin:capture` |
| Agents | 2 | `device-explorer`, `bug-reporter` |
| Hooks | 3 | in `hooks/hooks.json` (token-safety + connection-lifecycle guards) |
| MCP server | 1 | `headspin` (stdio, stdlib-only) at `mcp/headspin_mcp_server.py` |

Skills are model-invoked; Claude autonomously chains them. Commands are the explicit
user entry points and are auto-discovered from `commands/`. Agents come from `agents/`,
hooks from `hooks/hooks.json`, and the MCP server from `.mcp.json` — all standard
plugin locations.

---

## Install

**From a marketplace** (once published):

```
/plugin marketplace add <owner>/<marketplace-repo>
/plugin install headspin-control
```

**Local development** — add the containing directory as a local marketplace, then
install:

```
/plugin marketplace add /Users/nick/Desktop/yt-transition-shorts-detector
/plugin install headspin-control
```

After install, enable and configure the plugin in the `/plugin` UI (see Configuration
below). The plugin ships `defaultEnabled: false`, so it stays inert until you turn it on.

> **New here?** Two example-driven guides walk you through it end to end:
> - **[docs/INSTALL.md](docs/INSTALL.md)** — full install, real smoke test, troubleshooting.
> - **[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)** — day-by-day: log in, inspect a
>   device, reserve/drive/release, and realize the value in a week. Explains the two-credential
>   model (API token vs. browser-login identity JWT).
> - **[docs/USAGE.md](docs/USAGE.md)** — every tool and command with the **real** captured
>   request/response: sessions, reports, Waterfall/HAR, device event time series, artifacts.

---

## Onboarding

1. Run **`/headspin:setup`** — checks that your config is resolved and pings
   `GET /v0/devices/keys` to confirm connectivity. It never echoes your token.
2. If you have no token yet, run **`/headspin:login`** — it points you at the HeadSpin
   UI (Settings → API Tokens; tokens are created UI-only, there is no REST create call),
   validates the token, and surfaces the resolved environment (UI host, API host, tunnel
   host/port, device count).
3. Run **`/headspin:devices`** to list what is available, then `/headspin:connect`.

---

## Configuration

Configure these in `/plugin` → Configure `headspin-control`. They are declared as
`userConfig` in the manifest and reach skills as `${CLAUDE_PLUGIN_OPTION_<KEY>}` env
vars (and `${user_config.<key>}` substitution).

| Key | Env var | Default | Sensitive | Purpose |
|-----|---------|---------|-----------|---------|
| `api_host` | `CLAUDE_PLUGIN_OPTION_API_HOST` | `https://api-dev.headspin.io` | no | REST API base URL |
| `ui_host` | `CLAUDE_PLUGIN_OPTION_UI_HOST` | `https://ui-dev.headspin.io` | no | Web UI base; used to confirm the environment |
| `api_token` | `CLAUDE_PLUGIN_OPTION_API_TOKEN` | — | **yes** | Bearer token, stored in the OS keychain |
| `tunnel_host` | `CLAUDE_PLUGIN_OPTION_TUNNEL_HOST` | `dev-ca-tor-0.headspin.io` | no | Default per-device websocket region host |
| `tunnel_port` | `CLAUDE_PLUGIN_OPTION_TUNNEL_PORT` | `33100` | no | Default websocket control-channel port |

The `tunnel_host` / `tunnel_port` defaults are the HAR-confirmed dev values. The actual
tunnel host for a given device is resolved from that device's record at connect time —
the UI host is not the tunnel host (HAR line 177 proves they differ), so connect skills
read `hostname` from the device object rather than assuming the default.

---

## Auth model (five credential surfaces, no `orgkey`)

There is **no `authorization: orgkey:token` format** — it does not exist anywhere in the
captured traffic (0 occurrences across both captures), and there is no cookie auth. The
same identity is carried differently per surface; pick the carrier by surface, they are
not interchangeable:

| Surface | Carrier | Form |
|---------|---------|------|
| REST (`api-dev.headspin.io/v0/…`) | `Authorization: Bearer <JWT>` header | HS256 JWT; header name `authorization` (proven via CORS preflight; the XHR value is capture-stripped, not absent). |
| socket.io control + `/d/` screen stream (`dev-ca-tor-0:{23100,27100,33100,34100}`) | `?access_token=<JWT>` query param | Same HS256 JWT; **query only, never a header**. |
| iOS control + screen WS (`dev-in-blr-0:5002`) | `?jwt=<JWT>` query param | Same HS256 JWT. Locking a device re-mints the JWT with the lock UUID as its `email` (`…@lock.hspin.io`). |
| Janus WebRTC (`:150xx/janus`) | body `token=<16char>` + query `?token=` + `watch`-body `pin=<same>` | A per-session opaque Janus token, **not** the account JWT, **not** Bearer. |
| Appium `wd/hub` (`:70xx`) | 32-hex token embedded in the URL **path** (`/v0/{token}/wd/hub/…`) | No Authorization/Cookie header despite CORS advertising `Authorization`. |

`org_id` (`dfeb7e2e-…`, org "YouTube Benchmarking") is an org **identifier**, not a
credential.

## Security policy

- **The token is never written to disk.** The `sensitive: true` flag on `api_token`
  routes it to the OS keychain, not `settings.json`. Skills read it inline from
  `$CLAUDE_PLUGIN_OPTION_API_TOKEN` and never persist it to the session temp files under
  `/tmp/headspin-control/`.
- Skills never echo the token value, and `/headspin:setup` only ever prints whether a
  token is set, never its contents.
- The Appium path token (`/v0/{token}/wd/hub`) and any JWT query param are redacted
  before being written into evidence bundles or bug reports — a shareable artifact
  carries zero secrets.

---

## MCP server

The bundled `headspin` MCP server (`mcp/headspin_mcp_server.py`) is a stdlib-only,
JSON-RPC-2.0-over-stdio server. It reads `HS_API_TOKEN` and `HS_API_HOST` from the env
(wired from `userConfig` in `.mcp.json`) and exposes **20 tools**, each of which makes a
real HTTP call:

| Tool | REST call | Purpose |
|------|-----------|---------|
| `hs_login_details` | `GET /v0/logindetails` | Env/org probe (unauthenticated — reachability only) |
| `hs_list_devices` | `GET /v0/devices` | List devices (first Bearer call = token validation) |
| `hs_idevice_info` | `GET /v0/idevice/{addr}/info?json` | iOS lockdownd property dump |
| `hs_installer_list` | `GET /v0/idevice/{addr}/installer/list?json` | iOS installed-app inventory |
| `hs_lock_device` | `POST /v0/idevice/{addr}/lock` | Exclusively reserve a device |
| `hs_unlock_device` | `POST /v0/idevice/{addr}/unlock` | Release a device lock |
| `hs_list_sessions` | `GET /v0/sessions` | List capture sessions (`include_all` for ended) |
| `hs_adb_lock` | `POST /v0/adb/{id}/lock` | Reserve an Android/Cast/FireTV device (LIVE-VERIFIED 2026-07-03) |
| `hs_adb_unlock` | `POST /v0/adb/{id}/unlock` | Release an Android device lease |
| `hs_adb_shell` | `POST /v0/adb/{id}/shell` | Run adb shell on a locked device — drive the UI over REST |
| `hs_start_capture` | `POST /v0/sessions` | Start a capture session (video on) on a locked device |
| `hs_stop_capture` | `PATCH /v0/sessions/{sid}` | Stop capture; MP4 uploads on success |
| `hs_session_issues` | `GET /v0/sessions/analysis/issues/{sid}` | **Waterfall UI issue card** — the core report |
| `hs_analysis_status` | `GET /v0/sessions/analysis/status/{sid}` | Are the report analyses done? |
| `hs_session_timestamps` | `GET /v0/sessions/{sid}/timestamps` | Capture start/end/complete epoch marks |
| `hs_session_timeseries_info` | `GET /v0/sessions/timeseries/{sid}/info` | Available device signals (up to 31 series) |
| `hs_session_timeseries_download` | `GET /v0/sessions/timeseries/{sid}/download` | One series as CSV → disk |
| `hs_session_video_metadata` | `GET /v0/sessions/{sid}/video/metadata` | Recording dims/fps/duration/codec |
| `hs_session_download` | `GET /v0/sessions/{sid}.{ext}` | HAR / MP4 / device.log.gz / PCAP → disk |
| `hs_session_tls_exceptions` | `GET /v0/sessions/{sid}/tlsexceptions` | Hosts whose TLS pinning broke capture |

Downloads stream to `HS_DOWNLOAD_DIR` (default `/tmp/headspin-control/downloads/`) and
return `{saved_to, bytes, content_type}` — never raw bytes. HTTP failures come back as
tool results with `isError: true` carrying the HTTP status and response body, so
failures are visible rather than swallowed.

---

## Device control — two stacks by platform

The control plane is not one transport. It splits by platform; `headspin-connection-manager`
picks the correct one:

| Platform | Transport | Host:Port | Screen | Input primitive |
|----------|-----------|-----------|--------|-----------------|
| **Android / Cast / FireTV** | Engine.IO v3 + Socket.IO | `dev-ca-tor-0.headspin.io:{23100,27100,33100,34100}` | separate `/d/{serial}/{screenPort}/` WS (minicap JPEG + H264) | `input.*` socket.io events — normalized 0.0–1.0 coords, addressed by the device's base64 `channel` token (not the serial) |
| **iOS** | Raw JSON-over-WS (`{"type":…}`) | `dev-in-blr-0.headspin.io:5002` | `/screen/mp4` WS or Janus WebRTC | `CONTROL_TOUCH_PATHS` (per-finger `[opcode,x,y,t]` paths) + `CONTROL_HOME` |

- The **socket.io port selects a device fleet/pool** — one control server per device
  group on the host. Each `device` object in the `devicelist` carries its `channel`
  control token and its screen URL: `display.url = wss://…:{ctrlPort}/d/{serial}/{screenPort}/`.
  The screen port is **per-device dynamic** (read `display.url` / `display.httpScreenPort`) —
  never a fixed offset from the control port.
- The Android event bus is fire-and-forget `42["event",…]` (no ACKs); roster via
  `devicelist`, live logs via `device.log`, incremental state via `device.change`,
  request/reply overlaid via `sd.*`/`tx.*` transactions.

## Live screen streaming — Janus (H264)

The WebRTC screen view (and the iOS video leg gated by `CONTROL_WEBRTC_START`) rides a
**Janus** gateway (`janus.plugin.streaming`) over **HTTP long-poll, not a websocket**:

- `POST /janus/{sid}/{handle}` sends commands; `GET /janus/{sid}?rid=&maxev=10&token=`
  long-polls for events. Lifecycle: `create` → `attach` → `watch` (server offers SDP) →
  `start` (browser answers) → `trickle` → `webrtcup` → `hangup` → `detach` → `destroy`.
- Codec is **H264, `profile-level-id=42e01f`** (Constrained Baseline 3.1), video-only
  (audio + datachannel declined). One Janus instance per streamed device; observed ports
  `15033/15035/15042` (`dev-ca-tor-0`) and `15041` (`dev-in-blr-0`).
- **The `janus-protocol` WebSocket transport is unreliable and must not be depended on** —
  the one attempted `wss://…/janus` handshake failed (status 0, one error frame, no
  payload). Use the HTTP long-poll transport.

## Command usage

| Command | What it does |
|---------|--------------|
| `/headspin:setup` | First-run config check + connectivity ping (`/v0/devices/keys`). |
| `/headspin:login` | Authenticate, validate the token, surface the resolved environment. |
| `/headspin:devices` | List free/locked devices, filterable by platform and selector. |
| `/headspin:connect` | Lock a device and open the right control path (iOS / Android / Roku). |
| `/headspin:control` | Drive a connected device (taps, keys, screenshots, OCR). |
| `/headspin:capture` | **(1.2.0)** Full capture lifecycle: lock → record → drive app → stop → report-ready. |
| `/headspin:explore` | Run automated exploration to surface anomalies and crashes. |
| `/headspin:report` | Produce a standardized bug report from exploration evidence. |
| `/headspin:sessions` | List capture sessions; pull the report (issue card, status, time series). |
| `/headspin:waterfall` | Download the Waterfall HAR / MP4 / device log / PCAP for a session. |

### Worked example — capture a 5-minute YouTube session and pull everything

Every response below is real, from the 2026-07-03 live validation run
(`e2e-evidence/headspin-forge-260703/session-validation/`).

```
1. /headspin:devices
   hs_list_devices → 34 devices; pick one with status 3 (online), e.g.
   RFCN80FV2TA (SM-G981U) @ dev-ca-tor-0-proxy-20-lin.headspin.io

2. /headspin:capture RFCN80FV2TA youtube 3.5
   hs_adb_lock      {"device_id":"RFCN80FV2TA","timeout":30}
                    → {"status": 0, "message": "RFCN80FV2TA@… locked."}
   hs_start_capture {"device_address":"RFCN80FV2TA@dev-ca-tor-0-proxy-20-lin.headspin.io"}
                    → {"session_id": "6543ba4e-76b2-11f1-ae1a-56284a680ba9"}
   hs_adb_shell     {"device_id":"RFCN80FV2TA","command":"am start -a android.intent.action.VIEW -d https://m.youtube.com/shorts …"}
   hs_adb_shell     {"device_id":"RFCN80FV2TA","command":"input swipe 400 1400 400 400 200"}   # ×21, ~every 10 s
   hs_adb_shell     {"device_id":"RFCN80FV2TA","command":"dumpsys window | grep mCurrentFocus"}
                    → stdout proves the app is foreground
   hs_stop_capture  {"session_id":"6e163540-…"} → MP4 upload confirmed
   hs_adb_unlock    {"device_id":"RFCN80FV2TA"}

3. /headspin:sessions 6543ba4e
   hs_analysis_status  → analysis pipeline status
   hs_session_issues   → 8 issue cards (TLS Exceptions, Slow DNS Query, Loading
                         Animation, Low Page Content, Duplicate DNS Query, …)
   hs_session_timeseries_info → 50 series (frame_rate, memory_used, battery_temp, …)

4. /headspin:waterfall 6543ba4e mp4
   hs_session_download {"session_id":"6543ba4e-…","ext":"mp4"}
                    → 132,587,822 bytes, h264 752x1664, 363.9 s — frame-verified:
                      extracted stills show different Shorts advancing over 6 minutes
```

Gotchas the commands handle for you (learned the hard way, all reproduced live):
- Start-capture on a device that just ended a session → 500; back off ~90 s.
- Notification shade blocks app launch → recording shows the lock screen. Collapse the
  shade and verify `mCurrentFocus` before driving.
- MP4 fetched immediately after capture-complete can be a partial upload — the container
  header already claims full duration. Check `ffprobe -count_packets ≈ duration × fps`.
- The recorder is VFR: a static screen encodes few packets, so `video_duration_ms` can be
  far below wall-clock. Session truth = `hs_session_timestamps`.
- YouTube **app** on farm devices hits a Google sign-in wall (no account provisioned).
  Drive `https://m.youtube.com/shorts` in Chrome for signed-out Shorts playback.
- A device's recorder can be wired to the WRONG screen farm-side — now reproduced live
  **twice**: an SM-G991U recording a Roku screensaver (2026-07-03) and an SM-G973W capture
  that recorded an iPhone 11's home screen (2026-07-05, session `e8024cb0` — frame
  fingerprint matched the iPhone's exact installed-app inventory). Fingerprint every MP4:
  `ffprobe -show_entries stream=width,height`, then **view extracted frames and match
  visible content against the target device** before trusting a capture. Non-negotiable.

### Worked example 2 — the 90-second smoke run (2026-07-05, every response real)

The fastest possible end-to-end proof that your token, a device, and the whole
report pipeline work — six tool calls, ~90 seconds of wall clock:

```
hs_adb_lock       {"device_id": "R38N70234FA", "timeout": 30}
                  → {"status": 0, "message": "R38N70234FA@dev-ca-tor-0-proxy-2-lin… locked."}
hs_start_capture  {"device_address": "R38N70234FA@dev-ca-tor-0-proxy-2-lin.headspin.io"}
                  → {"session_id": "e8024cb0-788e-11f1-8491-da3445a29211", "state": "active"}
hs_adb_shell      {"device_id": "R38N70234FA",
                   "command": "am start -a android.intent.action.VIEW -d https://www.youtube.com"}
hs_adb_shell      {"device_id": "R38N70234FA", "command": "input swipe 500 1500 500 500 300"}
hs_stop_capture   {"session_id": "e8024cb0-…"}
                  → {"msg": "Video uploaded to https://api-dev.headspin.io:443/v0/sessions/e8024cb0-….mp4"}
hs_adb_unlock     {"device_id": "R38N70234FA"}
```

What the platform handed back for that 80-second session:

```
hs_session_video_metadata → 512×1184 h264, 23.105 fps, 80,111 ms, audio 1ch
hs_analysis_status        → {"status": "done"}
hs_session_issues         → {"Audio Too Quiet": {"Integrated Loudness (LUFS)": ["-30.8"]}}
hs_session_timeseries_info→ 16 series (impact, network, download_rate, blurriness, screen_change, …)
hs_session_download mp4   → {"bytes": 6899682, "content_type": "video/mp4"}   # the actual recording
```

The issue card genuinely caught something: the tab played muted, and the Waterfall
analysis flagged it at −30.8 LUFS. That is the report pipeline working on your data,
not a canned demo.

Typical flow: `/headspin:setup` → `/headspin:login` → `/headspin:devices` →
`/headspin:connect` → `/headspin:control` (or `/headspin:explore`) → `/headspin:report`.
After any capture: `/headspin:sessions` → `/headspin:waterfall`. Real request/response
examples for every command: [docs/USAGE.md](docs/USAGE.md).

---

## Environment note

Defaults target the HeadSpin **dev** environment (`api-dev.headspin.io` /
`ui-dev.headspin.io`), confirmed live in the 2026-07-02 HAR capture. For production,
set `api_host` and `ui_host` to your own HeadSpin subdomain and supply a token issued
against that environment.

---

## Marketplace metadata

- **Name:** `headspin-control`
- **Version:** `1.2.0`
- **License:** MIT
- **Keywords:** headspin, device-farm, roku, ios, android, remote-control,
  qa-automation, bug-reporting, waterfall, session-capture, performance-report,
  network-har
- **Default enabled:** false (opt-in via `/plugin`)
