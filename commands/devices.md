---
description: List real devices in the current HeadSpin environment, filtered by platform, grouped by availability and lock status.
argument-hint: "[ios|android]"
---

# /headspin:devices

Enumerate the devices available in the current HeadSpin environment.

## Steps

1. **Pre-flight auth** — require a token before calling the API:

   ```bash
   [ -n "${CLAUDE_PLUGIN_OPTION_API_TOKEN}" ] || { echo "No token — run /headspin:login"; exit 1; }
   ```

   If a later call returns `401`, stop and suggest `/headspin:login`.

2. **Resolve the optional platform filter** from `$ARGUMENTS` (`ios` | `android`).
   No arg → query both carriers. There is **no Roku** in this environment (the device
   once assumed Roku, `RFCN80FV2TA`, is an Android Galaxy S20 — `API-CONTRACT.md` DL-2), and
   there is **no `/v0/devices` REST route** to apply a `device_type` selector against
   (`API-CONTRACT.md` DL-6).

3. **Invoke the headspin-list-devices skill** with the parsed platform filter. It uses the two
   real inventory carriers — **iOS** via REST `GET /v0/idevice/{udid}@{host}/info?json`
   (`Authorization: Bearer`), and **Android/Chromecast/Fire TV** via the socket.io `devicelist`
   event (`?access_token=<JWT>` on the control-port handshake) — and records each device's
   control host + per-device screen URL from `display.url`.

4. **Group and surface** the result as a markdown table sorted by platform then serial/udid,
   split into **Available** vs **Locked** (show the redacted lock owner; Android only — iOS lock
   state is not exposed by these carriers). Cap at 50 rows.

The selected device is persisted for the connect skills at
`/tmp/headspin-control/selected-device.txt`.
