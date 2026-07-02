---
name: headspin-connect-ios
description: "Establish a HeadSpin control session on an iOS device. Two real (HAR-observed) surfaces exist in this environment: (1) an Appium wd/hub W3C session created via REST with the 32-hex API token embedded in the URL path (xcuitest driver, headspin:controlLock + headspin:remoteControl caps); (2) the interactive remote-control plane — a raw JSON-over-WebSocket control socket on dev-in-blr-0:5002 (/api/devices/{udid}/control?jwt=<JWT>) for input, plus a Janus WebRTC / /screen/mp4 video plane. Invoke when /headspin:connect picks an iOS device, when the user wants to drive an iPhone/iPad, or when headspin-control-ios reports no live session."
allowed-tools: [Read, Bash, Grep]
---

# headspin-connect-ios

Depends on: `headspin-session-manager` (reads `/tmp/headspin-control/lock.json` produced by session-manager step 1). Unlike Android/Cast, iOS control does **not** ride the `/d/{serial}/{port}/` socket.io tunnel that `headspin-connection-manager` opens — iOS has its own raw-JSON control WebSocket (see below), so this skill establishes the session directly.

## When to use

- `/headspin:connect` resolved a device with `device_type: "iOS"`.
- The user wants to drive an iPhone or iPad (tap, swipe, Home, screenshot, app inventory).
- `headspin-control-ios` reports "no live session" or "session expired".

## iOS has two distinct real surfaces (both HAR-observed, on two different devices/regions)

Do not conflate these with the Android control stack. The socket.io `42[...]` framing and the `/d/{serial}/{port}/` tunnel are **Android/Cast only** — iOS uses neither.

| Surface | Purpose | Host:Port + path | Auth carrier | Observed on |
|---|---|---|---|---|
| **Appium `wd/hub`** | scripted W3C automation session | `POST https://dev-ca-tor-0.headspin.io:7028/v0/{32-hex-token}/wd/hub/session` | 32-char lowercase-hex API token in the **URL path** (no header) | iPhone 11, udid `00008030-001174DE2260402E`, iOS 14.4.2, Toronto (`dev-ca-tor-0`) |
| **Control WebSocket** | interactive touch / Home / WebRTC gate | `wss://dev-in-blr-0.headspin.io:5002/api/devices/{udid}/control?jwt=<JWT>` — raw JSON `{"type":…}`, **NOT socket.io** | `?jwt=<JWT>` query param | iPhone udid `00008101-000530A821C2001E` (tail `000530A821C2001E`), Bangalore (`dev-in-blr-0`) |
| **Screen (video)** | live device screen | `wss://dev-in-blr-0.headspin.io:5002/api/devices/{udid}/screen/mp4?jwt=<JWT>` (fMP4-over-WS) **and/or** Janus WebRTC (`janus.plugin.streaming`, H264 `42e01f`, HTTP long-poll on `:150xx`) | `?jwt=` (screen/mp4) / body `token`+`pin` (Janus) | same Bangalore device |
| **App inventory / device info** | installed apps, device metadata | `GET https://api-dev.headspin.io/v0/idevice/{udid}@{host}/installer/list?json` and `…/info?json` | `Authorization: Bearer <api_token>` (header name is bare `authorization`) | Toronto iPhone 11 |

**New region introduced by this environment:** `dev-in-blr-0.headspin.io` (Bangalore) hosts the iOS control/screen plane, distinct from the Toronto `dev-ca-tor-0` Appium/Janus host. A device's real host comes from its device record — never assume a single host.

## Prerequisites

- `headspin-login` and `headspin-list-devices` have run. `/tmp/headspin-control/selected-device.txt` holds `<udid>@<hostname>` and `/tmp/headspin-control/selected-type.txt` holds `iOS`.
- `headspin-session-manager` has acquired the device lock. **Taking a lock re-mints the JWT**: for a locked device the control-WS / Appium JWT `email` claim becomes the lock UUID (`…@lock.hspin.io`), matching the device object's `owner.email` and `lockId` (`raw-forensics/socketio-control.md` §4). An unlocked JWT carries the operator's real email.
- The credential (`HEADSPIN_API_KEY`) is used in **different forms per surface** — see the auth table above. The WS planes want the **JWT** form (`?jwt=` / `?access_token=`); REST wants `Authorization: Bearer <api_token>`; Appium wants the **32-hex token in the path**. Never a header on the WS or Appium surfaces. `orgkey:token` does not exist and must never be sent.

## Workflow

1. **Validate platform.** Read `/tmp/headspin-control/lock.json`. Confirm `device_type == "iOS"`. If it isn't iOS, refuse and route to `headspin-connect-android` (or `headspin-connect-roku`, which is **doc-only / not HAR-verified in this environment** — no Roku device is present in this capture).

2. **Create the Appium `wd/hub` session (scripted automation entry).** iOS uses the **xcuitest** driver. The token is the 32-char lowercase-hex API token in the URL **path segment**, not a header:

   ```text
   POST https://<appium-host>:<appium-port>/v0/<32-hex-token>/wd/hub/session
   Content-Type: application/json
   ```

   Real capability template observed for iOS (`API-CONTRACT.md` §3, iOS/xcuitest, port 7028):

   ```json
   {"capabilities": {"alwaysMatch": {
     "platformName": "ios",
     "appium:automationName": "xcuitest",
     "appium:deviceName": "iPhone 11",
     "appium:udid": "<udid from device record>",
     "appium:platformVersion": "14.4",
     "appium:bundleId": "com.apple.Preferences",
     "headspin:controlLock": true,
     "headspin:remoteControl": true
   }}}
   ```

   - `platformName` is the only unprefixed cap; vendor caps are prefixed `appium:` and `headspin:`. Both `headspin:controlLock:true` and `headspin:remoteControl:true` were present on the observed session.
   - The server negotiates back `webDriverAgentUrl` (observed `http://127.0.0.1:1949`), a `sessionId`, and echoes `automationName: "xcuitest"`.
   - CORS on the endpoint advertises `Authorization` in `Access-Control-Allow-Headers`, but **no Authorization header is ever sent** — the path token is the only credential.

3. **Register the interactive control + screen channels (for `headspin-control-ios` / streaming).** These are the HAR-observed interactive planes on `dev-in-blr-0:5002`:

   ```text
   control : wss://<blr-host>:5002/api/devices/<udid>/control?jwt=<JWT>      # raw JSON {"type":…}
   screen  : wss://<blr-host>:5002/api/devices/<udid>/screen/mp4?jwt=<JWT>   # fMP4-over-WS (endpoint present)
   janus   : https://<host>:<150xx>/janus                                    # WebRTC video, HTTP long-poll
   ```

   The control WS is a **bespoke JSON-message channel** (`{"type":"<TYPE>", …}`, one per text frame) — it is not socket.io and carries no `42[...]` frames. On connect the server sends `CONTROL_VIEWABLE` → `DEVICE_ORIENTED` → `CONTROL_READY`; after `CONTROL_READY` the channel accepts input. `headspin-control-ios` drives this channel.

4. **Open the control socket.** Persist the channel URLs and the resolved `session_id` (from Appium) / control-WS readiness so `headspin-control-ios` can reuse them. Write to `/tmp/headspin-control/ios-session.json`:

   ```json
   {"udid": "<udid>", "appium_session_id": "<id or null>",
    "control_ws": "wss://<blr-host>:5002/api/devices/<udid>/control",
    "screen_ws": "wss://<blr-host>:5002/api/devices/<udid>/screen/mp4",
    "appium_host": "<appium-host>", "appium_port": "<port>", "os_version": "<from record>"}
   ```

   Route the control WS's incoming JSON frames:

   | Frame `type` | Meaning | Routed to |
   |---|---|---|
   | `CONTROL_VIEWABLE` / `DEVICE_ORIENTED` / `CONTROL_READY` | session grant → orientation → ready-for-input | Update session state; `CONTROL_READY` unblocks `headspin-control-ios`. |
   | `CONTROL_WEBRTC_DISCONNECTED` | server signalled the video leg dropped | Streaming skill re-issues `CONTROL_WEBRTC_START`. |
   | anything else | unclassified | Log raw to `/tmp/headspin-control/events.jsonl`. |

5. **Surface the result to the user** as a single line:
   `Connected to iOS <udid> (<os_version>) — Appium session=<id or n/a> on <appium-host>:<port>; control WS on <blr-host>:5002. Use /headspin:control ios <verb> to drive.`

## Evidence

- Appium iOS session shape + real xcuitest caps (`platformName:ios`, `automationName:xcuitest`, iPhone 11, iOS 14.4, `headspin:controlLock`/`remoteControl`, token-in-path port 7028): `e2e-evidence/headspin-forge-260702/har-forensics/API-CONTRACT.md` §3.
- iOS control WS (`dev-in-blr-0:5002 /api/devices/{udid}/control?jwt=`, raw JSON `{"type":…}`, `CONTROL_VIEWABLE`/`CONTROL_READY` handshake): `e2e-evidence/headspin-forge-260702/raw-forensics/socketio-control.md` §3a–3b.
- `/screen/mp4` iOS screen endpoint + Janus video plane: `raw-forensics/socketio-control.md` §3d, §6; `raw-forensics/janus.md` §1–§3.
- Bangalore (`dev-in-blr-0`) region + iOS device `000530A821C2001E`: `har-forensics/CONTRACT-ADDENDUM.md` §C/§D; `raw-forensics/socketio-control.md` §3.
- Auth carriers (WS `?jwt=`/`?access_token=`, REST Bearer, Appium path token, no `orgkey`): `API-CONTRACT.md` §1; `CONTRACT-ADDENDUM.md` §A.
- Lock re-mints the JWT (email → `…@lock.hspin.io`): `raw-forensics/socketio-control.md` §4.
- Environment variable contract: plugin `commands/setup.md` (`HEADSPIN_API_KEY`, `HEADSPIN_API_HOST`, `HEADSPIN_TUNNEL_PORT`).

## Unsupported / not HAR-verified in this environment

- **WebDriverAgent on TCP port 8100 via a `/d/<device_id>/8100/` tunnel** — not observed. iOS control is the `:5002` raw-JSON control WS + Appium `wd/hub`; there is no iOS `/d/{serial}/{port}/` socket.io tunnel in this capture.
- **`42["appium:createSession", …]` socket.io framing for iOS** — not observed. The Appium session is created via a REST `POST …/wd/hub/session`; the interactive control WS uses raw `{"type":…}` JSON, not socket.io `42[...]` events.
- **iOS 17 / Appium 2 / XCUITest 5.x behaviour** (auto-upgrade, iOS-17 feature matrix, Biometrics-SDK "Not Supported") — **doc-only, not HAR-verified**. The only iOS device observed is iOS **14.4.2** with the `xcuitest` driver. Treat any iOS-17 claim as documentation, not fact about this environment.
- **Appium session teardown (`DELETE`) and post-create WebDriver commands** (find/tap/screenshot via `/wd/hub/session/{id}/…`) — not captured (CORS advertises `DELETE`/`POST` but no such traffic exists). Implement from Appium docs only; mark DOC-INFERRED.
- **A phone/tablet Android Appium session** — the only Android Appium sessions captured are Fire TV + Chromecast; irrelevant to iOS but noted so no cross-platform assumptions leak in.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `device_type != "iOS"` | Wrong device selected | Refuse; tell the user to run `/headspin:devices` and pick an iOS device. |
| Control WS closes with `HTTP/1.1 0` / no upgrade | The `:5002` handshake did not upgrade (retry churn observed in capture) | Re-issue the control WS connect; confirm the `?jwt=` value is a live JWT for this region. |
| Appium `POST …/wd/hub/session` returns non-2xx | Device offline, WDA not running, or wrong token in path | Confirm the 32-hex token and that the device is `present/ready`; WDA installs are managed by HeadSpin. |
| WS closes with 401 mid-session | JWT expired or wrong region (Toronto vs Bangalore) | Re-run `/headspin:login`, re-acquire the lock (re-mints the JWT), reconnect. |
| Only `CONTROL_WEBRTC_DISCONNECTED` seen after upgrade | Video leg dropped; control WS still fine | `headspin-control-ios` re-issues `CONTROL_WEBRTC_START`; input still works over the control WS. |
| Lock re-minted JWT rejected | Using the pre-lock JWT after acquiring the lock | Use the JWT returned with the lock (email is now the lock UUID). |
| Lock-renewer died | Background renew loop killed | `headspin-control-ios` calls will start failing; re-acquire the lock via `headspin-session-manager`. |
