---
name: headspin-control-ios
description: "Drive an already-connected iOS device over the two real control surfaces. Interactive input rides the raw JSON-over-WebSocket control channel on dev-in-blr-0:5002 (CONTROL_TOUCH_PATHS for tap/swipe, CONTROL_HOME for Home, CONTROL_WEBRTC_START/…_DISCONNECTED to gate the video leg). Scripted automation and app inventory ride Appium wd/hub (xcuitest) and the REST idevice API. Invoke when the user runs /headspin:control ios <verb>, or when headspin-explore-bugs wants a sequence of iOS interactions in a bug-reproduction script."
allowed-tools: [Read, Bash, Grep]
---

# headspin-control-ios

Depends on: `headspin-connect-ios` (must have established the session at `/tmp/headspin-control/ios-session.json` — the control-WS URL and, for scripted verbs, the Appium `wd/hub` session id — before any control command).

## When to use

- User runs `/headspin:control ios <verb>` (e.g. `tap <x> <y>`, `swipe <x1> <y1> <x2> <y2>`, `home`, `screenshot`, `apps`).
- `headspin-explore-bugs` wants to drive iOS as part of an automated bug repro.
- A test scenario needs to navigate iOS UI.

## Two control surfaces (do not conflate with Android)

iOS input is **not** socket.io. There are no `42[...]` frames and no `input.touchDown/…` events on the iOS plane — that is the Android/Cast stack. iOS uses:

1. **Control WebSocket** — `wss://dev-in-blr-0.headspin.io:5002/api/devices/{udid}/control?jwt=<JWT>`, raw JSON `{"type":"<TYPE>", …}`, one message per text frame. This is the interactive input plane (touch, Home, WebRTC gate).
2. **Appium `wd/hub` (xcuitest)** — REST session created by `headspin-connect-ios` (`POST …:7028/v0/{32-hex-token}/wd/hub/session`) for scripted W3C automation, and the REST `idevice` API for device info / app inventory.

## Inputs

- `/tmp/headspin-control/ios-session.json` — written by `headspin-connect-ios`. Contains `{udid, appium_session_id, control_ws, screen_ws, appium_host, appium_port, os_version}`. If missing, refuse and tell the user to run `/headspin:connect` first.
- The active control WebSocket (raw JSON `{"type":…}` on `:5002`). This skill sends framed JSON commands over it; it does not open the socket (`headspin-connect-ios` does).

## Workflow

1. **Read the session** from `/tmp/headspin-control/ios-session.json`. If absent, route to `headspin-connect-ios` and stop. Confirm the control WS has reached `CONTROL_READY` before sending input (the connect skill records readiness).

2. **Dispatch by verb.** Interactive verbs are JSON messages on the control WS; scripted/inventory verbs use Appium or the REST idevice API. Only the shapes below are HAR-observed; anything else is DOC-INFERRED and must be looked up before use.

   **Control-WS verbs (HAR-observed on `:5002`):**

   | Verb | Wire shape (raw JSON on the control WS) | Notes |
   |---|---|---|
   | `tap <x> <y>` | `{"type":"CONTROL_TOUCH_PATHS","spec":{"0":[[1,<x>,<y>,0],[3,<x>,<y>,0]]},"boundingW":1,"boundingH":1}` | One gesture per message with embedded timing. `spec` key = finger id (`"0"` = first contact). Each point = `[opcode,x,y,t]`; opcode `1`=down, `2`=move, `3`=up. A tap = down then up at the same point. |
   | `swipe <x1> <y1> <x2> <y2> [<steps>]` | `{"type":"CONTROL_TOUCH_PATHS","spec":{"0":[[1,<x1>,<y1>,0],[2,<xa>,<ya>,<t>],…,[3,<x2>,<y2>,<t_end>]]},"boundingW":1,"boundingH":1}` | Down (`1`) → N moves (`2`) with increasing `t` (seconds within the gesture) → up (`3`). Unlike Android, the whole path with timing is one message, not incremental events. |
   | `home` | `{"type":"CONTROL_HOME"}` | Press Home. |
   | `webrtc_start` | `{"type":"CONTROL_WEBRTC_START"}` | Request/renew the WebRTC video leg. Observed renewed ~every 40s while the control WS stays open. |
   | `webrtc_stop` | `{"type":"CONTROL_WEBRTC_DISCONNECTED"}` | Tear down the video leg (control WS stays open). |

   **Coordinates are normalized 0.0–1.0** of `boundingW`/`boundingH` (both `1` → full-screen fraction), origin top-left. Convert screenshot pixel coords to fractions (`x/width`, `y/height`) before building the path.

   **Scripted / inventory verbs (Appium xcuitest + REST idevice):**

   | Verb | Surface | Notes |
   |---|---|---|
   | `apps` | `GET https://api-dev.headspin.io/v0/idevice/{udid}@{host}/installer/list?json` → `{"data":[Info.plist,…]}` | HAR-observed app inventory. Each entry is an app's Info.plist as JSON (`CFBundleIdentifier`, `CFBundleDisplayName`, version, `ApplicationType`, entitlements). `Authorization: Bearer <api_token>`. |
   | `info` | `GET https://api-dev.headspin.io/v0/idevice/{udid}@{host}/info?json` → 200 | HAR-observed device metadata (DeviceClass, ProductType, ProductVersion, UniqueDeviceID). |
   | scripted automation (find/tap/screenshot/type via WebDriver) | `…/v0/{32-hex-token}/wd/hub/session/{appium_session_id}/…` | Appium xcuitest driver. **DOC-INFERRED** — the session *create* is HAR-observed but no post-create WebDriver command was captured; look up the exact W3C endpoint in the Appium xcuitest docs before calling. |

3. **Handle the response.**
   - Control WS: fire-and-forget JSON frames; there is no per-command ACK. Confirm effect by observing device state / a fresh screen frame, not by a reply. Server may emit `CONTROL_WEBRTC_DISCONNECTED` asynchronously — re-issue `CONTROL_WEBRTC_START` if you need video.
   - REST/Appium: parse the HTTP response body; on non-2xx, surface the status + body, log to `/tmp/headspin-control/events.jsonl`, and stop.

4. **Coordinate translation.** The control WS wants **normalized 0.0–1.0 fractions**, not native pixels. From a screenshot at native resolution `W×H`, send `x/W`, `y/H`. (This differs from a raw Appium coordinate call, which uses pixels — do not mix the two.)

5. **Refuse verbs that are not in the tables.** Don't guess. For control-WS input, only `CONTROL_TOUCH_PATHS`, `CONTROL_HOME`, and the `CONTROL_WEBRTC_*` gates are HAR-observed. For scripted automation, the Appium xcuitest docs are the source — look up any command before issuing it and label it DOC-INFERRED.

## Evidence

- iOS control WS message catalog (`CONTROL_VIEWABLE`/`CONTROL_READY`/`CONTROL_HOME`/`CONTROL_WEBRTC_START`/`…_DISCONNECTED`, `dev-in-blr-0:5002 /api/devices/{udid}/control?jwt=`): `e2e-evidence/headspin-forge-260702/raw-forensics/socketio-control.md` §3a–3b.
- `CONTROL_TOUCH_PATHS` shape (`spec` per-finger `[opcode,x,y,t]`, opcode 1=down/2=move/3=up, normalized `boundingW/H`): `raw-forensics/socketio-control.md` §3c.
- App inventory / device info REST (`installer/list?json`, `info?json`, Bearer): `raw-forensics/socketio-control.md` §5; `har-forensics/API-CONTRACT.md` §2b.
- Appium iOS session create (xcuitest, token-in-path): `har-forensics/API-CONTRACT.md` §3.
- Janus / `/screen/mp4` video plane: `raw-forensics/janus.md` §1–§3; `raw-forensics/socketio-control.md` §3d.

## Unsupported / not HAR-verified in this environment

- **`42["appium:*", …]` socket.io framing for iOS input** (`appium:click`, `appium:executeScript`, `appium:lock`, `appium:getScreenshot`, `appium:getPageSource`, `mobile: swipe`/`mobile: type`/`mobile: pressButton`) — **not observed on the iOS control plane**. iOS interactive input is the raw-JSON `CONTROL_*` control WS. Appium xcuitest commands, if used, go over the REST `wd/hub` session (DOC-INFERRED, session-create only was captured).
- **iOS 17 feature matrix and Biometrics-SDK "Not Supported"** — **doc-only, not HAR-verified**. The only iOS device observed is iOS 14.4.2. Do not assert iOS-17 support/unsupport as fact about this environment.
- **`lock`/`unlock`/`isLocked`/`volumeUp`/`volumeDown`/`terminate` as iOS control-WS verbs** — not observed in this capture. Only `CONTROL_TOUCH_PATHS`, `CONTROL_HOME`, and the `CONTROL_WEBRTC_*` gates were captured on `:5002`. Any other control is DOC-INFERRED (Appium xcuitest) — look it up, don't assume the wire shape.
- **Post-create Appium WebDriver commands** (find/tap/screenshot/type via `/wd/hub/session/{id}/…`) — CORS advertises them but no such traffic was captured; implement from Appium xcuitest docs only, marked DOC-INFERRED.
- **HQ-screenshot / typing / geo / network-shaping "Supported via iOS 17"** claims — doc-only; not exercised in this HAR.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `ios-session.json` missing | `headspin-connect-ios` never ran or failed | Route to `headspin-connect-ios` and re-run. |
| Control WS input has no effect | Sent before `CONTROL_READY`, or coords sent as pixels not fractions | Wait for `CONTROL_READY`; send normalized 0.0–1.0 coords. |
| Only `CONTROL_WEBRTC_DISCONNECTED` in the log | Video leg dropped; control WS still open | Re-issue `CONTROL_WEBRTC_START`; touch/Home still work. |
| `installer/list` returns non-2xx | Wrong `udid@host`, or missing `Authorization: Bearer` | Confirm `udid@host` from the device record and that the REST call carries the Bearer token. |
| WS closes with 401/`HTTP/1.1 0` mid-script | JWT expired, wrong region, or handshake never upgraded | Reconnect via `headspin-connect-ios`; re-acquire the lock (re-mints the JWT) if expired. |
| Session expired mid-script | Lock TTL elapsed (default per session-manager) | Re-acquire via `headspin-session-manager`; the next command reconnects. |
| Video frame stale but touch works | WebRTC leg down while control WS alive | Re-issue `CONTROL_WEBRTC_START`; do not tear down the control WS. |
