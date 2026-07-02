---
name: headspin-connect-roku
description: "Documented capability — the Roku CONTROL WIRE is DOC-SOURCED, not captured (no Roku traffic in the HAR/Raw captures), though real Roku devices DO exist in this environment (live /v0/devices on 2026-07-02 returned 3 online Roku: YH001N51126312 Roku Streaming Stick+, X02600RUALWE + X02600LX08J3 Roku Express). Establish a HeadSpin control session on a Roku device per HeadSpin docs: validate it is a Roku platform via the device record, connect the Appium Roku driver (ECP port 8060), and surface a `roku_session_id` for `headspin-control-roku`. The connect/drive wire details are DOC-SOURCED from headspin-docs, not observed in any captured session. Invoke when /headspin:connect picks a Roku device, when the user wants to drive a Roku TV, or when headspin-control-roku reports no live session."
allowed-tools: [Read, Bash, Grep]
---

# headspin-connect-roku

> **⚠ Documented capability — NOT HAR-verified in this environment.**
> **No Roku traffic is present in the captured sessions** (both the `ui-dev.headspin.io.har`
> capture and the `Raw_07-02-2026` captures contain **0 Roku control/connect calls**), so the
> connect/drive wire shapes below are unobserved. **Real Roku devices DO exist in this
> environment**, though — a live `GET /v0/devices` on 2026-07-02 returned 3 online Roku
> (`YH001N51126312` Roku Streaming Stick+, `X02600RUALWE` + `X02600LX08J3` Roku Express;
> `live-validation/probe1-devices.json`). Separately, the serial `RFCN80FV2TA`, which looks
> Roku-shaped, is actually a **Samsung SM-G981U (Galaxy S20), Android** — not a Roku
> (API-CONTRACT §2a, DL-2). Everything below is **DOC-SOURCED** from
> `headspin-docs/` (Appium Roku driver docs), not verified against captured traffic. Kept for
> completeness; treat as documentation, not proven behavior. Do not present any Roku wire detail
> as HAR-observed.

Depends on: `headspin-session-manager` (this skill reads `/tmp/headspin-control/lock.json` produced by session-manager step 1; connection-manager opens the actual websocket that this skill hands off to).

## When to use

- `/headspin:connect` resolved a device with `device_type: "Roku"`.
- The user wants to drive a Roku TV (press keys, launch a channel, read screen).
- `headspin-control-roku` reports "no live session" or "session expired".

## Prerequisites

- `headspin-login` and `headspin-list-devices` have run. `/tmp/headspin-control/selected-device.txt` holds the `device_address` and `/tmp/headspin-control/selected-type.txt` holds `Roku`.
- `headspin-session-manager` has acquired the device lock and persisted the lock response to `/tmp/headspin-control/lock.json`. The lock response includes the actual `hostname` for the websocket (per `api-reference/devices-api.md:546-554` — Lock a device matched by selector — which returns `{status, status_code, serial, hostname, device_id}`).

## Workflow

1. **Validate platform.** Read `/tmp/headspin-control/lock.json`. The device type comes from the device record surfaced in step 1 of `headspin-list-devices`; confirm `device_type == "Roku"` before continuing. If it isn't, refuse and route to `headspin-connect-ios` or `headspin-connect-android`.

2. **Discover the Roku ECP port.** Roku TVs expose the External Control Protocol on TCP port `8060` (HTTP-based, used by the Appium Roku driver that HeadSpin wraps). Reference: `headspin-docs/integrations/roku.md:14-46` (Roku + HeadSpin compatibility) and `headspin-docs/automation/rokuQSG.md:69-114` (Appium Roku driver capabilities + supported commands including `roku: pressKey`).

3. **Build the websocket URL.** **DOC-INFERRED — the Roku tunnel shape was NOT observed in this
   environment** (no Roku in the capture; the `/d/<serial>/<port>/` websocket that IS in the capture
   belongs to the Android device `RFCN80FV2TA`, not a Roku). By analogy to the observed HeadSpin
   device tunnel, a Roku control tunnel would take the form:

   ```text
   wss://<device.hostname>:<HEADSPIN_TUNNEL_PORT>/d/<device_id>/8060/?access_token=<JWT>
   ```

   The JWT rides as an `?access_token=` query param (never a Bearer header — that is the observed
   auth carrier for every HeadSpin control websocket; API-CONTRACT §1 AUTH-1/AUTH-2). The
   path-segment port `/8060/` is the Roku ECP port **per Roku's ECP docs**, not a captured value.
   The Appium Roku driver would then issue keypress / launch / screenshot commands as
   `roku: pressKey` Execute Method calls (per `automation/rokuQSG.md:108`). None of this Roku wire
   shape is HAR-verified — implement from the Appium Roku driver docs and confirm against a real
   Roku before relying on it.

4. **Open the socket** using the same `wscat` / `websocat` / `open_device_tunnel.py` script that `headspin-connection-manager` documents. Route incoming frames:

   | Frame | Routed to |
   |---|---|
   | `42["device.log", {tag:"roku:*", ...}]` | `/tmp/headspin-control/device.log.jsonl`; consumed by `headspin-explore-bugs`. |
   | `42["device.screenshot", {png: <b64>}]` | Decode base64 → write to `/tmp/headspin-control/screenshots/<frame_id>.png`; consumed by `headspin-bug-report`. |
   | `42["roku.session.ready", {session_id: "..."}]` | Persist to `/tmp/headspin-control/roku-session.json`; consumed by `headspin-control-roku`. |
   | Anything else | Log raw to `/tmp/headspin-control/events.jsonl` for later analysis. |

5. **Negotiate the Appium session handshake.** The HeadSpin Roku tunnel expects the Appium-Roku-driver initial protocol exchange before the first `Execute Method` call works. The minimal handshake:

   ```text
   42["appium:createSession", {"capabilities": {"firstMatch": [{"platformName":"Roku","appium:automationName":"Roku"}]}}]
   ```

   This matches the documented required capabilities at `automation/rokuQSG.md:69-74` (`platformName=Roku`, `appium:automationName=Roku`). HeadSpin supplies `appium:rokuHost`, `appium:rokuEcpPort`, `appium:rokuWebPort`, `appium:rokuUser`, `appium:rokuPassword` automatically (per the doc note at line 74) — the skill must NOT set those.

6. **Surface the session id.** The `appium:createSession` response carries the `session_id`. Persist it to `/tmp/headspin-control/roku-session.json` so `headspin-control-roku` and `headspin-explore-bugs` can use it without re-handshaking.

7. **Surface the result to the user** as a single line: `Connected to Roku <device_id> at <hostname> via tunnel (session=<session_id>). Use /headspin:control roku <key> to drive.`

## Evidence

**Roku-specific detail is DOC-SOURCED only (no Roku in either capture):**
- Roku + HeadSpin compatibility contract: `headspin-docs/integrations/roku.md:14-46` (doc).
- Appium Roku driver capabilities and required keys: `headspin-docs/automation/rokuQSG.md:69-74` (doc).
- Appium Roku driver commands including `roku: pressKey` Execute Method: `headspin-docs/automation/rokuQSG.md:106-114` (doc).

**Non-Roku, environment-observed anchors (used only for the auth carrier + tunnel-shape analogy, NOT as Roku evidence):**
- WS auth carrier is `?access_token=<JWT>`, never Bearer/`orgkey`: `../har-forensics/API-CONTRACT.md` §1 (AUTH-1/AUTH-2), `CONTRACT-ADDENDUM.md` §A.
- The `/d/<serial>/<port>/` device-tunnel websocket that exists in the capture is the **Android** `RFCN80FV2TA` (Galaxy S20), not a Roku: `../har-forensics/API-CONTRACT.md` §4 + §2a + DL-2, `../raw-forensics/socketio-control.md` §2. (The former Roku citation `ui-dev.headspin.io.har:177` was this Android device, mislabeled — corrected.)
- Lock response shape (hostname field): `headspin-docs/api-reference/devices-api.md:546-554` (doc).
- Environment variable contract: `headspin-docs/.../plugins-reference.md:637-670` (doc).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `device_type != "Roku"` | Wrong device selected | Refuse; tell the user to run `/headspin:devices` and pick a Roku. |
| WebSocket closes with 401 on the tunnel | Token expired mid-session | Re-run `/headspin:login` then re-acquire the lock via `headspin-session-manager`. |
| `appium:createSession` returns `500` | Device offline or Appium-Roku-driver not installed on the host | Check `/tmp/headspin-control/device.log.jsonl`; if the host-side stack is missing, escalate to the org admin — this is a fleet-side problem, not a token problem. |
| Keypress via `headspin-control-roku` returns `no such element` | The app on the Roku isn't the dev channel with `name=dev` (per `automation/rokuQSG.md:161-162`) | Install the dev channel via `/headspin:install` (or `app-management.md`) before running keypress tests. |
| Roku responds slowly or drops the socket | Appium keyCooldown may be too aggressive (per `automation/rokuQSG.md:72`) | Set `appium:keyCooldown: 200` (ms) via `/headspin:control roku config keyCooldown 200` if the skill supports it; otherwise tell the user. |
| Lock-renewer (`headspin-session-manager` step 2) died | Background bash loop killed | `headspin-control-roku` calls will start failing as the lease approaches expiry; re-acquire the lock. |
