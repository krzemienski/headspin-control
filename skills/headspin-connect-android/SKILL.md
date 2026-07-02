---
name: headspin-connect-android
description: "Establish a HeadSpin control session on an Android / Cast / Fire TV device via the Engine.IO-v3 + Socket.IO control channel (the observed Android control plane): open the socket.io control websocket for the device's fleet port, authenticate with the JWT as an ?access_token= query param (NOT a Bearer header), read the fleet `devicelist` to resolve the device's base64 `channel` token and per-device screen-stream URL, and surface those so control can inject `input.*` events (normalized 0.0-1.0 coords, channel-token-addressed) and open the minicap screen stream. Invoke when /headspin:connect picks an Android device, when the user wants to drive an Android phone / Chromecast / Fire TV, or when an Android control step reports no live session."
allowed-tools: [Read, Bash, Grep]
---

# headspin-connect-android

Depends on: `headspin-session-manager` (reads `/tmp/headspin-control/lock.json` produced by session-manager step 1; `headspin-connection-manager` opens/maintains the raw websocket that this skill hands off to).

> **Downstream note:** `headspin-connection-manager` routes Android events to a
> `headspin-control-android` skill, but that skill does **not exist in this plugin yet**. Until
> it is authored, the socket.io control session established here is the handoff point: this skill
> documents the exact `input.*` injection contract a control step must send (§ "Control handoff"
> below). Do not fabricate a `headspin-control-android` invocation.

## Auth carrier (read first — a common wrong assumption)

The socket.io control channel and the per-device screen stream authenticate with the **JWT as an
`?access_token=<JWT>` query parameter**. There is **no `Authorization` header and no `orgkey:token`**
on these WebSocket surfaces (`authorization` header count = 0 across the whole capture; `orgkey` is
fabricated and absent everywhere). `Authorization: Bearer` is only for the REST (`api-dev.headspin.io/v0/…`)
surface — never for these websockets.

Source: API-CONTRACT §1 (AUTH-1/AUTH-2), CONTRACT-ADDENDUM §A, `../raw-forensics/socketio-control.md` §1a/§4.

## When to use

- `/headspin:connect` resolved a device with `device_type: "Android"` (includes Chromecast and Fire TV, which report `platform: "Android"`).
- The user wants to drive an Android phone/tablet, a Chromecast, or a Fire TV.
- An Android control step reports "no live session" or "session expired".

## Prerequisites

- `headspin-login` and `headspin-list-devices` have run. `/tmp/headspin-control/selected-device.txt` holds the `device_address` and `/tmp/headspin-control/selected-type.txt` holds `Android`.
- `headspin-session-manager` has acquired the device lock and persisted the lock response to `/tmp/headspin-control/lock.json`, which carries the device's `hostname` (region host, e.g. `dev-ca-tor-0.headspin.io`).

## The control plane (what is actually observed)

Android control is **Engine.IO v3 + Socket.IO**, NOT an Appium-over-websocket handshake and NOT an
Appium UiAutomator2 forwarded-ADB port. There are two distinct websockets per device:

1. **Control channel (socket.io)** — one connection per **fleet port**, multiplexes commands to any device in that fleet by its `channel` token.
2. **Screen stream** — a separate, per-device `/d/{serial}/{screenPort}/` websocket carrying the bespoke minicap protocol (JPEG + H264 binary frames). NOT socket.io framing.

The socket.io **port selects a device fleet/pool** (`CTRL ∈ {23100, 27100, 33100, 34100}` on the
region host). Observed pools:

| ctrl port | fleet (observed in `devicelist`) |
|---|---|
| 23100 | 13-device Samsung/Pixel Galaxy pool |
| 27100 | Chromecast `18191HFDD2YKNJ` + 2 Samsung |
| 33100 | 3-device Galaxy pool (incl. **`RFCN80FV2TA` = Samsung SM-G981U / Galaxy S20, Android 13** — this is NOT a Roku) |
| 34100 | Fire TV `G071EL1520331CDP` (AFTSSS) + Chromecast (offline) + 1 Samsung |

Source: API-CONTRACT §4 + §2a, CONTRACT-ADDENDUM §C/§D, `../raw-forensics/socketio-control.md` §1d.

## Workflow

1. **Validate platform.** Read `/tmp/headspin-control/lock.json`. Confirm the device reports
   `platform == "Android"`. If it does not, refuse and route to `headspin-connect-ios` (iOS is a
   different stack entirely — raw JSON-over-WS on `dev-in-blr-0:5002`) or `headspin-connect-roku`.

2. **Open the socket.io CONTROL websocket.** The control port is the outer port encoded in the
   device record's `display.url` (see step 4) — it is NOT a fixed env constant and NOT a per-device
   inner port. Shape (Engine.IO v3, direct websocket, no polling upgrade):

   ```text
   wss://<hostname>:<CTRL_PORT>/socket.io/?access_token=<JWT>&EIO=3&transport=websocket
   ```

   where `<hostname>` is the device's region host (e.g. `dev-ca-tor-0.headspin.io`), `<CTRL_PORT>`
   is one of `{23100, 27100, 33100, 34100}`, and `<JWT>` is the **UI-minted identity JWT**
   (claims `{name, email, plain_email}`), placed as the `access_token` query param — never a header.
   **The identity JWT is NOT the 32-hex `HEADSPIN_API_KEY` and is NOT the lease JWT that
   `POST /v0/jwt/permissions` mints** — LIVE-PROVEN 2026-07-02: a `_default`-permissions lease JWT
   completes the WS upgrade (HTTP 101) but the socket.io app rejects it with
   `44"Failed to decode jwt access_token."` (`e2e-evidence/headspin-forge-260702/ws-live-probe/01-socketio-33100.txt`).
   The identity JWT is a browser-login artifact obtained by `/headspin:login`; locking the device
   re-mints it with `email = <lockUUID>@lock.hspin.io`. Reuse the `headspin-connection-manager`
   websocket helper (`scripts/open_device_tunnel.py` / `wscat`) for the raw socket lifecycle,
   backoff, and reconnect.

3. **Complete the Engine.IO / Socket.IO handshake.** Framing = Engine.IO digit + optional Socket.IO
   digit, then payload. No `43` ACK frames — this channel is fire-and-forget events.

   | Frame | Meaning |
   |---|---|
   | `0{"sid":…,"upgrades":[],"pingInterval":25000,"pingTimeout":60000}` | Engine.IO **open** (server) |
   | `40` | Socket.IO **connect**, default namespace `/` (server) |
   | `2` → `3` | Engine.IO **ping** (client) → **pong** (server) heartbeat |
   | `41` | Socket.IO **disconnect** (client, at teardown) |
   | `42["<event>", …args]` | Socket.IO **event** |

4. **Read `devicelist` and resolve the device's channel + screen URL.** Right after connect the
   server emits `42["socket.ip","<ip>"]` then `42["devicelist",[ {…device objects…} ]]` — the entire
   fleet for that port. Find the entry whose `serial` matches the selected device and extract:

   - `channel` — the base64 STF-style token used to **address input** to this device (e.g.
     `"KQz/…="` for `RFCN80FV2TA`). **This is NOT the serial.** Persist it.
   - `display.url` — `wss://<hostname>:<CTRL_PORT>/d/<serial>/<screenPort>/` — the per-device screen
     stream URL. The `<screenPort>` is **dynamic and published here**; do NOT compute it from the
     control port (observed: `RFCN80FV2TA`→33110, Chromecast `18191HFDD2YKNJ`→27114). `display.httpScreenPort`
     is the sibling field.
   - `status` (`3` = ready/online, `2` = offline), `lockId` + `owner{email,name,plainEmail,group}`
     (PII → redact) if locked, `using`/`usage`.

   Persist the resolved values to `/tmp/headspin-control/android-session.json`:
   `{serial, channel, control_url, screen_url, screen_port, status}`. This file is the handoff
   artifact for the (future) `headspin-control-android` and for `headspin-explore-bugs`.

5. **Route the server→client control-channel events:**

   | Event | Shape (real) | Routed to |
   |---|---|---|
   | `socket.ip` | `42["socket.ip","<ip>"]` | Log to `/tmp/headspin-control/events.jsonl`. |
   | `devicelist` | `42["devicelist",[ … ]]` | Consumed in step 4; also persisted for `headspin-list-devices`. |
   | `device.change` | `42["device.change",{"important":bool,"data":{"serial","display":{"state":"on"\|"off"},…}}]` | Incremental delta keyed by **serial**; surface screen on/off + lock changes. |
   | `device.log` | `42["device.log",{"serial","timestamp","priority","tag","pid","message","identifier"}]` | Append to `/tmp/headspin-control/device.log.jsonl`; consumed by `headspin-explore-bugs`. |
   | `tx.done` | `42["tx.done","tx.<uuid>",{"source":"<serial>","seq":0,"success":bool,"data":…,"body":…}]` | Result of an `sd.*` transaction (see handoff). |
   | anything else | — | Log raw to `/tmp/headspin-control/events.jsonl`. |

6. **Open the screen stream (optional, for live view / screenshots).** A **separate** websocket to
   `screen_url` (from step 4) with the JWT as `?access_token=`:

   ```text
   wss://<hostname>:<CTRL_PORT>/d/<serial>/<screenPort>/?access_token=<JWT>
   ```

   This is the bespoke minicap protocol, NOT socket.io. Client sends text `on` to start / `off` to
   stop. Server sends text control lines (`version 2`, `frameSettings {…}`, `h264 socket ready`,
   `start {…}`, `ping`) interleaved with **binary** JPEG/H264 frames (opcode-2 WS binary messages).
   Screenshots come from these binary frames — there is **no** `device.screenshot` socket.io event.
   Save frames under `/tmp/headspin-control/screenshots/`.

7. **Surface the result to the user** as a single line:
   `Connected to Android <serial> (<model>) at <hostname> — control socket.io :<CTRL_PORT>, screen /d/<serial>/<screenPort>/, channel resolved. Drive via input.* (normalized coords, channel-addressed).`

## Control handoff — the `input.*` injection contract

Until `headspin-control-android` exists, this is the exact wire contract for driving the device over
the control socket opened above. **Every input event's 2nd arg is the device `channel` token**
(from step 4), NOT the serial. Coordinates are **normalized 0.0–1.0** of the screen (origin
top-left); the server maps to device pixels.

| Client→server event | Shape (real) |
|---|---|
| `input.gestureStart` / `input.gestureStop` | `42["input.gestureStart","<channel>",{"seq":N}]` |
| `input.touchDown` | `42["input.touchDown","<channel>",{"seq":N,"x":0.505,"y":0.977,"contact":0,"pressure":0.5}]` |
| `input.touchMove` | `42["input.touchMove","<channel>",{"seq":N,"x":f,"y":f,"contact":0,"pressure":0.5}]` |
| `input.touchUp` | `42["input.touchUp","<channel>",{"seq":N,"contact":0,"pressure":0.5}]` |
| `input.touchCommit` | `42["input.touchCommit","<channel>",{"seq":N}]` — flush pending touch(es) to device |
| `input.keyDown` / `input.keyUp` | `42["input.keyDown","<channel>",{"key":"home"}]` — string key names |

- **Touch lifecycle (explicit, commit-based):**
  `gestureStart → touchDown → touchCommit → [touchMove → touchCommit]* → touchUp → touchCommit → gestureStop`,
  each frame carrying a monotonically incrementing `seq` that resets per gesture. A **tap** =
  Down/Commit/Up/Commit; a **swipe** = a long run of Move/Commit pairs (observed swipe `seq` 30→99).
- **Keys are string names**, not keycodes: observed `home`, `app_switch` (Android nav), and D-pad
  keys for Cast/Fire TV: `dpad_down`, `dpad_right`, `dpad_center`.
- **Transactions** (request/reply overlay on the fire-and-forget bus): client sends
  `42["sd.status","<channel>","tx.<uuid>",null]`; server later emits `42["tx.done","tx.<uuid>",{…}]`;
  client sends `42["tx.cleanup","tx.<uuid>"]`. `tx.<uuid>` correlates request↔response; `source`
  carries the serial. Observed on port 27100 (Chromecast `18191HFDD2YKNJ` → `"sd_unmounted"`).

## Appium — a separate, real surface (not this websocket)

Appium automation of Android TV form factors **does** exist in the capture, but it is a **REST
`wd/hub`** surface, NOT a socket.io handshake and NOT port 6790:

- `POST https://<hostname>:<70xx>/v0/<32-hex-token>/wd/hub/session` with a W3C body
  (`{"capabilities":{"alwaysMatch":{…}}}`), auth = the **32-hex token in the URL path** (no header).
- Observed only for **Fire TV** (`uiautomator2`, port 7034) and **Chromecast** (`uiautomator2`,
  port 7045) — both TV form factors. **No Android handset Appium session exists in this capture** —
  do not claim one as observed.

If a caller needs Appium, route it to the REST `wd/hub` surface with the path token — never send
`42["appium:createSession", …]` over the socket.io control channel (that frame is fabricated and
was never observed). Source: API-CONTRACT §3 + AUTH-5.

## Evidence

- Auth carrier (WS `?access_token=` JWT, no Bearer, no `orgkey`): `../har-forensics/API-CONTRACT.md` §1 (AUTH-1/AUTH-2), `CONTRACT-ADDENDUM.md` §A, `../raw-forensics/socketio-control.md` §1a/§4.
- Socket.io control plane, Engine.IO-v3 framing, event catalog, `input.*` primitives, channel-token addressing, touch lifecycle, transactions: `API-CONTRACT.md` §4, `CONTRACT-ADDENDUM.md` §C, `../raw-forensics/socketio-control.md` §1b–§1e.
- Per-device screen stream `/d/{serial}/{screenPort}/` (dynamic port from `display.url`, minicap JPEG+H264): `API-CONTRACT.md` §4 (`/d/` route) + DL-13, `../raw-forensics/socketio-control.md` §2.
- Port→fleet map, `RFCN80FV2TA` = Samsung Galaxy S20 (NOT Roku): `API-CONTRACT.md` §2a + §4 port map + DL-2, `CONTRACT-ADDENDUM.md` §D, `../raw-forensics/socketio-control.md` §1d.
- Appium `wd/hub` REST (path token, Fire TV 7034 / Chromecast 7045, TV-only): `API-CONTRACT.md` §3 + AUTH-5 + DL-10/DL-16.
- Underlying HAR/Raw anchors cited by the contract: `har-extract/entry-023.json` (socket.io handshake), devicelist frames idx 23/26/121/128, `entry-253.json` (`/d/` stream), `entry-224.json`/`entry-287.json` (Fire TV/Chromecast Appium).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `platform != "Android"` | Wrong device selected | Refuse; run `/headspin:devices` and pick an Android device. (iOS control is a different stack — `dev-in-blr-0:5002` raw JSON-over-WS.) |
| Socket closes with 401/1006 on the control port | JWT expired, wrong region host, or lock lost | Re-run `/headspin:login`; confirm the region host from the lock response; re-acquire the lock via `headspin-session-manager`. |
| `devicelist` has the device but `status == 2` | Device offline | It is not controllable; pick a `status:3` device or wait for it to come online (watch `device.change`). |
| Input goes nowhere / `input.*` no-op | 2nd arg was the serial, not the `channel` token | Re-read `devicelist[].channel` for the serial and address `input.*` by that channel. |
| Screen stream URL 404 / wrong port | Screen port was computed from the control port | Use `display.url` / `display.httpScreenPort` from the device record — the screen port is dynamic, not a fixed offset. |
| Touches land at the wrong pixel | Coords sent as pixels | Coords must be **normalized 0.0–1.0**; the server maps to device pixels. |
| Tap registers but has no effect | Missing `touchCommit` | Every touch phase must be followed by `input.touchCommit` with the same gesture's incrementing `seq`. |
| Someone expected `42["appium:createSession"]` to work over this socket | That frame is fabricated | Appium is the REST `wd/hub` path-token surface (§ "Appium"), not the socket.io channel. |
| Lock-renewer died | Background bash loop killed | Control calls start failing as the lease nears expiry; re-acquire the lock via `headspin-session-manager`. |
