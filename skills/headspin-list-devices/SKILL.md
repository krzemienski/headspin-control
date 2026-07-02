---
name: headspin-list-devices
description: Enumerate the real devices in the current HeadSpin environment via the two real inventory carriers — iOS through REST GET /v0/idevice/{udid}@{host}/info?json, and Android/Chromecast/Fire TV through the socket.io devicelist event on the control ports — surface availability + lock state, and parse the device_address for downstream connect skills. There is no /v0/devices REST route and no Roku in this environment. Invoke when the user runs /headspin:devices, asks "what devices are available", or any connect skill needs a device_address.
allowed-tools: Read, Bash, Grep
---

# headspin-list-devices

## When to use

- User runs `/headspin:devices` (or asks "what devices do we have").
- A downstream skill (`headspin-connect-ios`, `headspin-connect-android`) needs a `device_address` and the user has not supplied one.
- The user asks which devices are currently free vs locked.
- The user wants to filter by platform (iOS vs Android/Cast/Fire TV).

## Two inventory carriers (do NOT conflate)

There is **no `/v0/devices` REST route** in this environment — it is never called in the capture, and treating it as the roster is fabricated (`API-CONTRACT.md` DL-6). Inventory comes from two different carriers:

| Platform | Carrier | Auth |
|---|---|---|
| **iOS** | REST `GET /v0/idevice/{udid}@{proxy-host}.headspin.io/info?json` (per-device; you must already know the udid@host) | `Authorization: Bearer <api_token>` |
| **Android / Chromecast / Fire TV** | socket.io **`devicelist`** event `42["devicelist",[…]]` on a control port | JWT via `?access_token=` query param on the WS handshake — **not** a Bearer header |

**There is NO Roku in this environment.** The device once assumed to be a Roku (`RFCN80FV2TA`) is a Samsung SM-G981U (Galaxy S20), Android (`API-CONTRACT.md` DL-2). Do not offer a Roku filter or a Roku connect path from this environment.

## Prerequisites

- `headspin-login` has been run in this session. Required env: `HEADSPIN_API_HOST` and `HEADSPIN_API_KEY` (= `$CLAUDE_PLUGIN_OPTION_API_TOKEN`) for the REST carrier. The skill fails fast with a single line if either is missing — do NOT attempt a placeholder call. The socket.io carrier additionally needs the **UI-minted identity JWT** (claims `{name, email, plain_email}`) — **NOT the same value as the `HEADSPIN_API_KEY` Bearer token, and NOT the lease JWT from `/v0/jwt/permissions`**: LIVE-PROVEN 2026-07-02 the lease JWT is rejected by the control server with `"Failed to decode jwt access_token."` (`e2e-evidence/headspin-forge-260702/ws-live-probe/01-socketio-33100.txt`). The identity JWT comes from `/headspin:login` (browser sign-in), plus a control host + port. If you only have the api_token, the REST `/v0/devices` roster below still works; only the socket.io `devicelist` path needs the identity JWT.

## Workflow

1. **Resolve platform filter** (optional). The user can pass:
   - `ios` → iOS carrier only (REST `idevice/info`)
   - `android` (or `cast` / `firetv`) → Android carrier only (socket.io `devicelist`)
   - no filter → query both carriers

   Do **not** map any filter to a `?selector=` on `/v0/devices` — that route does not exist here.

2a. **iOS carrier — REST `idevice/info`.** This route is per-device: you must already have the `{udid}@{proxy-host}.headspin.io` address (from the user, a prior session, or the connect skill). There is no "list all iOS devices" REST call in this capture. For a known address:

   ```bash
   curl -sS -H "Authorization: Bearer ${HEADSPIN_API_KEY}" \
        "${HEADSPIN_API_HOST}/v0/idevice/${DEVICE_ADDRESS}/info?json"
   ```

   Response is a flat iOS lockdownd property dump — `DeviceClass`, `ProductType` (e.g. `iPhone12,1` = iPhone 11), `ProductVersion`, `UniqueDeviceID`. **It carries no lock / owner / reservation state** — iOS lock state is not in this REST body and the iPhone is absent from `devicelist`. Redact `SerialNumber`, IMEI, MAC/`WiFiAddress`/`BluetoothAddress`, and key hashes before persisting.

2b. **Android/Cast/Fire TV carrier — socket.io `devicelist`.** Open the socket.io control handshake and read the first `devicelist` frame. The handshake auth is the JWT as a query param, **not** a Bearer header:

   ```
   wss://<control-host>:<CTRL>/socket.io/?access_token=<JWT>&EIO=3&transport=websocket
   CTRL ∈ {23100, 27100, 33100, 34100}   # each port serves a device fleet/pool
   ```

   The server emits `42["devicelist",[ {serial, model, manufacturer, platform, version, status, lockId, owner{…}, using, channel, display:{url, httpScreenPort, state}}, … ]]`. Each control port carries a different subset of the fleet, so enumerate the ports the user cares about (or all four).

3. **Normalize to a one-line-per-device table** for the user. The critical columns for downstream skills are:

   | Column | Source field | Why it matters |
   |---|---|---|
   | `device_address` (iOS) | `{udid}@{proxy-host}.headspin.io` | Direct input to `headspin-connect-ios` and REST `idevice/*` calls. |
   | `serial` (Android) | `devicelist[].serial` | Identity for Android/Cast/Fire TV; maps to the control port it appeared on. |
   | `platform` / `model` | iOS `ProductType`; Android `platform`+`model`+`manufacturer` | Decides which `headspin-connect-{ios,android}` skill to chain. |
   | `screen_url` (Android) | `devicelist[].display.url` | The `/d/{serial}/{screenPort}/` WS URL for the screen stream — **per-device dynamic; read this field, never compute the port** (`API-CONTRACT.md` DL-13). |
   | `channel` (Android) | `devicelist[].channel` | The base64 control token that `input.*` events target (NOT the serial — `API-CONTRACT.md` DL-14). |
   | `locked` (Android) | `devicelist[].lockId != null` (+ `owner`, `using`) | Skip if held by another user; surface the owner (PII → redact in output) so the user can request release. iOS lock state is NOT available here. |
   | `status` (Android) | `devicelist[].status` | `3` = online/ready, `2` = offline. |

4. **Persist the resolution for downstream skills.** Write the user's chosen device to a session-local file the connect skills read:

   ```bash
   mkdir -p /tmp/headspin-control
   echo "${DEVICE_ADDRESS_OR_SERIAL}" > /tmp/headspin-control/selected-device.txt
   echo "${CONTROL_HOST}" > /tmp/headspin-control/selected-host.txt
   echo "${DEVICE_PLATFORM}" > /tmp/headspin-control/selected-type.txt   # ios | android
   chmod 600 /tmp/headspin-control/*.txt
   ```

   Never write the API token or JWT to these files. The token stays in `HEADSPIN_API_KEY` env var and is read inline by the connect skill.

5. **Surface results** to the user as a markdown table sorted by platform then serial/udid, split into **Available** vs **Locked** (Android only — iOS lock state is unavailable via these carriers). Cap at 50 devices per call.

## Evidence

- Two inventory carriers (iOS REST vs Android socket.io `devicelist`): `e2e-evidence/headspin-forge-260702/har-forensics/API-CONTRACT.md` §2 and DL-6.
- iOS `idevice/info` schema + Bearer auth: `e2e-evidence/headspin-forge-260702/raw-forensics/auth-inventory.md` §3.
- Android roster (21 devices, serial/model/manufacturer/port/status/lock): `API-CONTRACT.md` §2a.
- No Roku; `RFCN80FV2TA` = Samsung SM-G981U (Galaxy S20), Android: `API-CONTRACT.md` DL-2 / §2a.
- socket.io `devicelist` frame shape + `channel` addressing + `display.url` screen port: `API-CONTRACT.md` §4 (Events) and DL-13/DL-14.
- socket.io handshake auth is `?access_token=<JWT>` query param (not Bearer): `API-CONTRACT.md` §1 AUTH-1 / §4.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `HEADSPIN_API_KEY` empty | `headspin-login` not run | Re-run `/headspin:login`. |
| 401 from `/v0/idevice/…/info` | Token revoked or wrong host | Re-run `/headspin:login`; if it still 401s, generate a new token in the HeadSpin UI. |
| socket.io handshake rejected (no `devicelist`) | JWT missing/expired on `?access_token=`, or wrong control host/port | Confirm the JWT is the current login token and the control host is `dev-ca-tor-0.headspin.io` on a port in {23100,27100,33100,34100}. |
| A device is missing from `devicelist` | It is on a different control port, offline (`status:2`), or is the iOS device (never in `devicelist`) | Enumerate all four control ports; source iOS via REST `idevice/info` instead. |
| User asks for a Roku | No Roku exists in this environment | Tell the user there is no Roku here; `RFCN80FV2TA` is an Android Galaxy S20. |
| Android device has `lockId != null` (with `owner`) | Someone else holds the device | Surface the lock owner (redact PII); the user can request release or pick a device with `lockId: null`. |
