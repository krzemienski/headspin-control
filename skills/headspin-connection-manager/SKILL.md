---
name: headspin-connection-manager
description: Open and maintain the platform-correct control transport to a HeadSpin device and keep it alive. Two distinct control stacks exist by platform — Android/Cast/FireTV over socket.io (Engine.IO v3) on dev-ca-tor-0:{23100,27100,33100,34100}, and iOS over a raw JSON-over-WS control channel on dev-in-blr-0:5002 — plus a Janus HTTP long-poll path for the live H264 screen stream. Derive the per-device screen URL from the device's display.url, route incoming frames to the right handler, and re-establish the transport on disconnect. Invoke when /headspin:connect opens a control session, when a downstream control skill reports the socket dropped, or when the user runs /headspin:control.
allowed-tools: Read, Bash, Grep
---

# headspin-connection-manager

## When to use

- `/headspin:connect` is about to open a per-device control session.
- A control skill reports the control transport dropped mid-session.
- The user runs `/headspin:control <verb>` and the transport isn't already open.

## Inputs

- `device_address` — read from `/tmp/headspin-control/selected-device.txt` written by `headspin-list-devices`. Format: `<device_id>@<hostname>`.
- `device_type` — read from `/tmp/headspin-control/selected-type.txt`. In this environment the observed device types are **Android** (phones, Chromecast, Fire TV Stick) and **iOS**. **Roku is doc-only — NOT HAR-verified in this environment** (the serial `RFCN80FV2TA`, sometimes mistaken for a Roku, is a Samsung SM-G981U / Galaxy S20 running Android; no Roku appears in any captured `devicelist`).
- The auth token — an HS256 JWT, passed inline **as a URL query parameter** on every WS handshake (never a header). Read inline from `$CLAUDE_PLUGIN_OPTION_API_TOKEN` (keychain-backed); never written to a file.

## Two control stacks (pick by platform)

The control plane is **not one transport**. It splits by platform — do not conflate them.

| Stack | Transport | Host:Port | Screen | Input primitive |
|-------|-----------|-----------|--------|-----------------|
| **Android / Cast / FireTV** | Engine.IO v3 + Socket.IO | `dev-ca-tor-0.headspin.io:{23100,27100,33100,34100}` | separate `/d/{serial}/{screenPort}/` WS (minicap JPEG + H264 binary) | `input.*` socket.io events — **normalized 0.0–1.0 coords**, addressed by the device's base64 `channel` token (NOT the serial) |
| **iOS** | Raw JSON-over-WS (`{"type":…}` frames) | `dev-in-blr-0.headspin.io:5002` | `/screen/mp4` WS **or** Janus WebRTC (§ Janus streaming) | `CONTROL_TOUCH_PATHS` on the control WS |

Auth carrier differs by stack: socket.io + `/d/` stream use `?access_token=<JWT>`; the iOS `:5002` control/screen WS uses `?jwt=<JWT>`. Both are the same identity-only HS256 JWT; locking a device re-mints it with the lock UUID as the JWT `email` (`…@lock.hspin.io`).

## Workflow

### 1. Select the stack and (for Android) the fleet port

- **`device_type == Android`** → socket.io on `dev-ca-tor-0.headspin.io`. The **socket.io port selects a device fleet/pool** — one control server per device group on the same host. Observed pools:

  | ctrl port | Fleet | notable members |
  |-----------|-------|-----------------|
  | `23100` | large Samsung Galaxy pool (13 devices) | Pixel 3a, SM-A505G, SM-G781U/V ×many, SM-G973W, SM-G981U/V |
  | `27100` | Cast + small Samsung pool (3) | Chromecast `18191HFDD2YKNJ`, SM-G781U1, SM-G781V |
  | `33100` | small Galaxy pool (3) | SM-G981U ×2 (incl `RFCN80FV2TA`), SM-G991U |
  | `34100` | Fire TV + Cast + Samsung | AFTSSS `G071EL1520331CDP` (Fire TV Stick), Chromecast `11141HFDD1VUXU` (offline), SM-G991U |

  The device's own port comes from its `devicelist` record — do not guess it. `tunnel_port` (default `33100`) is only the connect-time default; the real fleet port is the one whose `devicelist` contains the target serial.

- **`device_type == iOS`** → the raw JSON-over-WS control channel on `dev-in-blr-0.headspin.io:5002` (a different region/host from the Android stack). iOS devices are **absent** from every socket.io `devicelist` — do not look for iOS lock-state there.

### 2a. Android — socket.io control handshake

```text
wss://dev-ca-tor-0.headspin.io:{ctrlPort}/socket.io/?access_token=<JWT>&EIO=3&transport=websocket
```

- Engine.IO **v3**, pure websocket (no HTTP long-poll upgrade; `"upgrades":[]`). Default namespace `/`.
- On connect: server sends `0{…}` (Engine.IO open, carries `sid`, `pingInterval:25000`, `pingTimeout:60000`) then `40` (Socket.IO connect). Heartbeat: client `2` (ping) → server `3` (pong). Disconnect: client `41`.
- Events are `42["<event>", …args]`. **No `43` ACK frames** — the bus is fire-and-forget; request/reply is overlaid via `sd.*`/`tx.*` transactions carrying a client-minted `tx.<uuid>`.

**Read the roster, then derive the screen URL.** The first `devicelist` frame carries the whole fleet; each device object includes its `channel` (input-routing token) and its `display.url`. See step 3.

**Input injection** targets the device's **`channel` token as the 2nd event arg**, not the serial — this is how one socket.io connection multiplexes to any device in its fleet. Map serial→channel via `devicelist[].channel` first. Coordinates are normalized 0.0–1.0 (origin top-left). Touch lifecycle:

```
input.gestureStart → input.touchDown → input.touchCommit
  → [input.touchMove → input.touchCommit]*
  → input.touchUp → input.touchCommit → input.gestureStop
```

each carrying a monotonically incrementing `seq` (resets per gesture). A tap is Down/Commit/Up/Commit; a swipe is a long run of Move/Commit pairs. Keys are string names, not keycodes: `input.keyDown`/`input.keyUp` with `{"key":"home"}` — observed `home`, `app_switch`, and D-pad keys for Cast/TV fleets (`dpad_down`, `dpad_right`, `dpad_center`). Example:

```
42["input.touchDown","<CHANNEL_REDACTED>",{"seq":1,"x":0.505,"y":0.977,"contact":0,"pressure":0.5}]
```

### 2b. iOS — raw JSON-over-WS control handshake

```text
wss://dev-in-blr-0.headspin.io:5002/api/devices/{udid}/control?jwt=<JWT>
```

- **Not socket.io.** Each WS text frame is one bespoke JSON message `{"type":"<TYPE>", …}`.
- Session grant sequence (server→client): `CONTROL_VIEWABLE` → `DEVICE_ORIENTED` → `CONTROL_READY` (ready for input).
- **Input primitive is `CONTROL_TOUCH_PATHS`** — one message is a complete gesture with embedded timing (unlike Android's incremental move stream):

  ```json
  {"type":"CONTROL_TOUCH_PATHS",
   "spec":{"0":[[1,0.472205,0.934482,0],[2,0.475936,0.934482,0.052],[3,0.475936,0.936206,0.082]]},
   "boundingW":1,"boundingH":1}
  ```

  `spec` keys = finger id (`"0"` = first contact; more keys = multi-touch). Each point = `[opcode, x, y, t]`: `x`,`y` normalized 0..1 of `boundingW`/`boundingH`; `t` = seconds offset within the gesture. Opcodes: `1` = down, `2` = move, `3` = up. A tap = `[[1,…,0],[3,…,0]]`; a drag = down + N moves + up with increasing `t`.
- Other control messages: `CONTROL_HOME` (press Home); `CONTROL_WEBRTC_START` / `CONTROL_WEBRTC_DISCONNECTED` (client→server) **gate the Janus-negotiated video leg** — the control WS renews the WebRTC leg roughly every ~40 s while staying open. No `CONTROL_WEBRTC_OFFER/ANSWER/ICE_CANDIDATE` frames ride `:5002`; the actual media SDP is negotiated over Janus (§ Janus streaming).

### 3. Derive the per-device screen URL from `display.url`

The live screen is a **separate transport from control**. For Android it is a bespoke minicap WS on the **same host as the control port**, at a **per-device dynamic screen port** published in the device's `devicelist` record — **never a fixed offset from the control port**:

```text
display.url = wss://dev-ca-tor-0.headspin.io:{ctrlPort}/d/{serial}/{screenPort}/?access_token=<JWT>
```

Read `{screenPort}` from `display.url` (or `display.httpScreenPort`). Observed: `RFCN80FV2TA` (ctrl `33100`) → `/d/RFCN80FV2TA/33110/` (httpScreenPort `33112`); Chromecast `18191HFDD2YKNJ` (ctrl `27100`) → `/d/18191HFDD2YKNJ/27114/`; Fire TV `G071EL1520331CDP` (ctrl `34100`) → `/d/G071EL1520331CDP/34130/`. The apparent `+10/+14/+30` offset is coincidental — always read the field, never compute the port.

The `/d/` stream is a text-control + binary-frame protocol (not socket.io): client sends text `on` to start / `off` to stop; server sends text control lines (`version 2`, `frameSettings {…}`, `h264 socket ready`, `start {…}`, `ping`) interleaved with binary opcode-2 JPEG/H264 frames. For iOS the equivalent stream endpoint is `wss://dev-in-blr-0.headspin.io:5002/api/devices/{udid}/screen/mp4?jwt=<JWT>` (fMP4-over-WS), though live iOS video typically rides the Janus WebRTC leg instead.

### 4. Route incoming events by stack

**Android socket.io — real server→client events only:**

| Event | Routed to |
|---|---|
| `devicelist` | Parse once for `channel` + `display.url` + lock state; cache serial→channel map. |
| `device.log` | Append to `/tmp/headspin-control/device.log.jsonl`; consumed by `headspin-explore-bugs`. Logcat-style, keyed by serial. |
| `device.change` | Incremental device-state delta keyed by serial (e.g. `display.state` on/off). Surface to the active control skill. |
| `socket.ip` | Informational (client origin IP); no-op. |
| `tx.done` | Result of an `sd.*` transaction, correlated by `tx.<uuid>`; hand to the requester, then send `tx.cleanup`. |

There is **no** `device.touch` / `device.tap` / `device.screenshot` socket.io event — screenshots come from the `/d/` binary stream or a REST call, not the control bus. Do not subscribe to events that were never observed.

**iOS `:5002` — server→client control messages:** `CONTROL_VIEWABLE`, `DEVICE_ORIENTED`, `CONTROL_READY` — surface to the active iOS control skill; there is no per-frame log event on this channel (device logs for iOS come from syslog via a separate REST/tail path).

### 5. Reconnect with exponential backoff

On any close code other than 1000 (normal) or 1001 (going away), retry with delay `min(2 ** attempt, 60)` seconds, max 5 attempts. If still failing, surface the most recent `device.log` (Android) or the last `CONTROL_*` frame (iOS) to help diagnose — most often: device went offline, session lease expired, or the device lock was lost.

### 6. Release on Stop hook

The `hooks/hooks.json` Stop hook calls this skill's `release()` step, which closes the transport cleanly (Android: send Socket.IO `41` disconnect then close TCP; iOS: close the `:5002` WS). The connection manager does **not** auto-release the device lock — that is `headspin-session-manager`'s job, called separately from the `SessionEnd` hook.

## Janus streaming (the live H264 view path)

The device screen for WebRTC-based viewing (and the iOS video leg gated by `CONTROL_WEBRTC_START`) rides a **Janus** gateway. Transport is **HTTP long-poll REST, not a websocket** — this is the proven-working path.

- **Base:** `https://{host}:{janusPort}/janus`, one Janus instance per streamed device. Observed ports: `15033`, `15035`, `15042` on `dev-ca-tor-0`, and `15041` on `dev-in-blr-0` (task-referenced `15043` was not observed in this capture).
- **Plugin:** `janus.plugin.streaming` (screen-mirror mountpoint pull). Video-only H264, `profile-level-id=42e01f` (Constrained Baseline 3.1), packetization-mode 1, pt 100 (pt 101 = rtx). Audio and datachannel are explicitly declined (`offer_audio:false`, `offer_data:false`).
- **Auth:** a 16-char opaque `token` in the POST body and as `?token=` on the long-poll GET, plus a `pin` (same value) in the `watch` body. **No `Authorization`/Bearer header** — this is not the account JWT.
- **Transport commands vs events:** `POST /janus/{sid}/{handle}` sends commands; `GET /janus/{sid}?rid={ms-ts}&maxev=10&token=<token>` long-polls for async events.
- **Lifecycle (server-offers flow):** `create` → session_id · `attach {plugin:"janus.plugin.streaming"}` → handle_id · `watch {id:<mountpoint>, offer_video:true, offer_audio:false, offer_data:false, pin}` · server delivers a **jsep OFFER** (H264, sendonly) inside a long-poll event · client `start {jsep:<answer>, request:"start"}` (recvonly) · `trickle` ICE + `{completed:true}` · long-poll events `preparing`→`starting`→`started`→`webrtcup` → media flows · `hangup` → `detach` → `destroy`. Session/handle IDs are server-assigned integers in `data.id` — carry them into subsequent URLs. Poll cadence is sub-second during setup, ~30s idle once `webrtcup`.
- **WS transport is unreliable here — do NOT depend on it.** The single `wss://…:15042/` handshake with subprotocol `janus-protocol` FAILED (HTTP status 0, one `error` frame, zero payload). No `janus-protocol` WS frame was ever carried. Implement Janus over HTTP long-poll only; a `_webSocketMessages`-only reader sees nothing for Janus because the whole lifecycle is in HTTP request/response bodies.

## Evidence

- Two control stacks (Android socket.io vs iOS `:5002` raw-JSON-WS), port→fleet map, `channel`-token input addressing, normalized coords: `e2e-evidence/headspin-forge-260702/raw-forensics/socketio-control.md` §1–§3; `CONTRACT-ADDENDUM.md` §C; base contract `API-CONTRACT.md` §4.
- `display.url` per-device dynamic screen-port derivation (`/d/{serial}/{screenPort}/`, never fixed-offset): `raw-forensics/socketio-control.md` §1d/§2; `API-CONTRACT.md` §4 (DL-13).
- iOS `CONTROL_TOUCH_PATHS` opcode 1/2/3, `CONTROL_HOME`, `CONTROL_WEBRTC_START/…_DISCONNECTED`: `raw-forensics/socketio-control.md` §3b–§3c.
- Janus HTTP long-poll lifecycle, H264 `42e01f`, token+pin auth, failed `janus-protocol` WS: `raw-forensics/janus.md` §1–§7; `CONTRACT-ADDENDUM.md` §B; `API-CONTRACT.md` §5.
- Auth carriers (`?access_token=` socket.io/`/d/`, `?jwt=` iOS `:5002`, `token`+`pin` Janus; no `orgkey`): `raw-forensics/auth-inventory.md` §1; `API-CONTRACT.md` §1.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| WS closes immediately with 401 | Token expired or wrong region | Re-run `/headspin:login`; confirm the token has access to this region (Toronto `dev-ca-tor-0` vs Bangalore `dev-in-blr-0`). |
| WS closes with 1006 (abnormal) | Device offline or session lease expired | Check `/tmp/headspin-control/device.log.jsonl` for the last `device.log`; if "lease expired", re-acquire via `headspin-session-manager`. |
| Android input goes nowhere | Injected against the serial instead of the `channel` token | Map serial→channel via `devicelist[].channel`; the `channel` is the 2nd `input.*` arg. |
| Screen port guessed and rejected | Computed the `/d/` port from the control port | Read `display.url` / `display.httpScreenPort` from the device's `devicelist` record — the port is dynamic. |
| Janus stream never comes up over WS | Depending on the `janus-protocol` WebSocket | Use the HTTP long-poll transport (POST commands + GET `?maxev=10` events); the WS handshake fails in this environment. |
| Asked for a Roku device | Roku is not present in this environment | Roku control is doc-only, not HAR-verified here; the Roku-shaped serial `RFCN80FV2TA` is an Android Galaxy S20. |
