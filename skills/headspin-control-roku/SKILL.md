---
name: headspin-control-roku
description: "Documented capability — NOT HAR-verified in this environment (no Roku device present in the ui-dev capture). Drive an already-connected Roku device per HeadSpin docs: press keys (Home, Up, Down, Left, Right, OK, Back, Play, Pause, Power, Volume), launch a channel by app id, send literal text input, take screenshots, and read the UI hierarchy. Every wire shape here is DOC-SOURCED from the Appium Roku driver docs, not observed in the captured session. Invoke when the user runs /headspin:control roku <verb>, or when headspin-explore-bugs wants a sequence of Roku interactions in a bug-reproduction script."
allowed-tools: [Read, Bash, Grep]
---

# headspin-control-roku

> **⚠ Documented capability — NOT HAR-verified in this environment.**
> **No Roku device is present in the captured session** (0 Roku devices in either the
> `ui-dev.headspin.io.har` or the `Raw_07-02-2026` capture; `RFCN80FV2TA` is a Samsung Galaxy S20
> Android, not a Roku — API-CONTRACT §2a, DL-2). Every `42[...]` wire shape below is **DOC-SOURCED**
> from the Appium Roku driver docs, **not observed** in captured traffic. Treat as documentation.

Depends on: `headspin-connect-roku` (must have established a session id at `/tmp/headspin-control/roku-session.json` before any control command).

## When to use

- User runs `/headspin:control roku <verb>` (e.g. `home`, `launch <channel_id>`, `text <message>`, `screenshot`, `dump`).
- `headspin-explore-bugs` wants to drive the Roku as part of an automated bug repro.
- A test scenario in the project needs to navigate Roku UI without writing an Appium script.

## Inputs

- `/tmp/headspin-control/roku-session.json` — written by `headspin-connect-roku` step 6. Contains `{session_id, device_id, hostname}`. If missing, refuse and tell the user to run `/headspin:connect` first.
- `/tmp/headspin-control/selected-device.txt` — for the device_id used in `42["<command>", {session_id, ...}]` payloads.
- The active websocket connection opened by `headspin-connection-manager`. This skill does NOT open a new socket; it sends framed commands over the existing one.

## Workflow

1. **Read the session id** from `/tmp/headspin-control/roku-session.json`. If absent, route to `headspin-connect-roku` and stop.

2. **Dispatch by verb.** Map the user's `<verb>` to an Appium-Roku-driver Execute Method. The
   Appium **method names** below (`roku: pressKey`, `Get Screenshot`, `Get Page Source`, `Send Keys`,
   `Find Element(s)`, `Click Element`) are doc-sourced from `headspin-docs/automation/rokuQSG.md:106-114`;
   `headspin-docs/integrations/roku.md:14-46` is the Roku compatibility / cert-pinning doc.

   > **DOC-INFERRED wire framing.** The `42[...]` socket.io framing shown in the table is an
   > **analogy to the observed Android control channel, NOT a captured Roku transport** — no Roku
   > traffic exists in either capture. In this environment, Appium was observed as a **REST `wd/hub`**
   > surface (path-token auth), not `42[...]` socket.io frames (API-CONTRACT §3). The exact transport
   > the Appium Roku driver uses over the HeadSpin tunnel must be confirmed against a real Roku +
   > the driver docs before relying on the framing below.

   | Verb | Wire shape | Notes |
   |---|---|---|
   | `home` | `42["roku: pressKey", {"session_id": "<id>", "key": "Home"}]` | Roku ECP key `Home`. |
   | `up` / `down` / `left` / `right` / `ok` / `back` | `42["roku: pressKey", {"session_id": "<id>", "key": "<KeyName>"}]` | Map directly. |
   | `play` / `pause` / `stop` / `rewind` / `fastForward` | `42["roku: pressKey", {"session_id": "<id>", "key": "Play" \| "Pause" \| "Stop" \| "Rev" \| "Fwd"}]` | Roku's ECP `key` names differ from the Appium names; map at the skill. The ECP key set is documented externally on Roku's developer site, not in `headspin-docs/`. |
   | `power` | `42["roku: pressKey", {"session_id": "<id>", "key": "Power"}]` | Powers the Roku on/off. |
   | `volumeUp` / `volumeDown` / `mute` | `42["roku: pressKey", {"session_id": "<id>", "key": "VolumeUp" \| "VolumeDown" \| "VolumeMute"}]` | |
   | `launch <channel_id>` | `42["appium:executeScript", {"session_id": "<id>", "script": "mobile: deepLink", "args": [{"url": "roku://launch/<channel_id>"}]}]` | Roku deep links are documented externally; the Appium driver `mobile: deepLink` script is the supported mechanism. |
   | `text <message>` | `42["roku: sendKeys", {"session_id": "<id>", "value": ["<message>"]}]` | Note: sendKeys uses literal characters, not ECP key names; the Appium driver translates them to ECP `LIT_<n>` keypress sequences per `automation/rokuQSG.md:111`. |
   | `screenshot` | `42["appium:getScreenshot", {"session_id": "<id>"}]` | Returns a base64 PNG; write to `/tmp/headspin-control/screenshots/<timestamp>.png`. |
   | `dump` | `42["appium:getPageSource", {"session_id": "<id>"}]` | Returns an XML UI hierarchy; write to `/tmp/headspin-control/dumps/<timestamp>.xml`. |
   | `tap <x> <y>` | `42["appium:click", {"session_id": "<id>", "element": {"x": <x>, "y": <y>}}]` | For non-keypad navigation. |

3. **Honor `appium:keyCooldown`.** Per `automation/rokuQSG.md:72`, a non-zero `appium:keyCooldown` caps keypress rate. The skill must not send keypress commands faster than the cooldown; the simplest implementation is `sleep ${keyCooldown_ms}` between successive `roku: pressKey` frames. Read the configured value from `/tmp/headspin-control/roku-session.json` (set during `appium:createSession`).

4. **Handle the response.** Each `42[...]` command produces a `42[..., <response>]` or `40[..., {error: "..."}]` reply. The skill must:
   - On success: print the response payload summary (e.g. `home: OK`).
   - On `error`: surface the message to the user, log the full frame to `/tmp/headspin-control/events.jsonl` with the command name and the error, and stop. The most common error is `no such element` after a `tap` when the coordinate misses the target — surface the exact coordinates + screenshot path so the user can re-aim.

5. **Refuse verbs that are not in the table.** Don't guess. Unknown verbs must be looked up in the Appium Roku driver README or Roku's ECP reference before the call, not invented.

## Evidence

**Roku-specific detail is DOC-SOURCED only (no Roku in either capture):**
- Appium Roku driver required capabilities and how HeadSpin supplies the rest: `headspin-docs/automation/rokuQSG.md:69-74` (doc).
- Appium Roku driver command list (`roku: pressKey`, `Get Screenshot`, `Get Page Source`, `Send Keys`, etc.): `headspin-docs/automation/rokuQSG.md:106-114` (doc).
- Appium `keyCooldown` capability: `headspin-docs/automation/rokuQSG.md:72` (doc).
- Dev channel naming constraint: `headspin-docs/automation/rokuQSG.md:161-162` (doc — the dev app is always named `dev`).
- Roku + HeadSpin compatibility (cert pinning for Network Analysis): `headspin-docs/integrations/roku.md:14-46` (doc).

**Framing-analogy note (NOT Roku evidence):**
- The `42[...]` socket.io framing that exists in the capture is the **Android** control channel (`RFCN80FV2TA` = Galaxy S20), not a Roku: `../har-forensics/API-CONTRACT.md` §4, `../raw-forensics/socketio-control.md` §1b. The former citations `ui-dev.headspin.io.har:30891` / `:177` referred to that Android device, not Roku — corrected. In this environment Appium itself was observed as REST `wd/hub` (path token), not `42[...]`: `API-CONTRACT.md` §3.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `roku-session.json` missing | `headspin-connect-roku` was never run, or it failed at step 5 | Route to `headspin-connect-roku` and re-run. |
| `roku: pressKey` returns `no such element` | The Roku is on the wrong screen (Home menu vs app menu) | Press `Home` first, then retry. |
| `roku: sendKeys` is slow or characters are dropped | `appium:keyCooldown` too aggressive | Increase keyCooldown or batch fewer chars per call. |
| `appium:getScreenshot` returns empty PNG | Headspin tunnel dropped the Appium session | Reconnect via `headspin-connect-roku`. |
| `appium:getPageSource` returns no XML (empty body) | The running channel isn't a dev channel; only dev channels expose UI hierarchy (`automation/rokuQSG.md:157-159`) | Install the dev channel before running `dump`. |
| Unknown verb passed by the user | Not in the supported table | Refuse; tell the user the supported verbs. |
| Session expired mid-script | Lock TTL elapsed (15 minutes default per session-manager step 2) | Re-acquire via `headspin-session-manager`; the next keypress will reconnect the Appium session. |
