---
description: Lock and open a control session on a HeadSpin device, routing to the iOS / Roku / Android connect skill.
argument-hint: "<device-address | ios | roku | android>"
---

# /headspin:connect

Establish a control session on a HeadSpin device. Lock-first discipline: acquire the
device lock BEFORE opening any control websocket.

## Steps

1. **Pre-flight auth** — token required:

   ```bash
   [ -n "${CLAUDE_PLUGIN_OPTION_API_TOKEN}" ] || { echo "No token — run /headspin:login"; exit 1; }
   ```

   Any `401` downstream → stop and suggest `/headspin:login`.

2. **Resolve the target** from `$ARGUMENTS`:
   - A `device_id@host` address → use it directly.
   - A platform word (`ios` | `roku` | `android`) → invoke **headspin-list-devices** to
     pick the first available device of that type (skip locked ones).
   - No arg → read `/tmp/headspin-control/selected-device.txt`; if absent, run
     `/headspin:devices` first.

3. **Lock the device** — invoke **headspin-session-manager** to acquire the lock via
   `POST /v0/devices/lock` and write `/tmp/headspin-control/lock.json`. If another user
   holds it, surface the owner and stop.

4. **Route by device type** to the matching connect skill, which opens the tunnel through
   **headspin-connection-manager**:
   - iOS → **headspin-connect-ios**
   - Roku → **headspin-connect-roku**
   - Android → **headspin-connect-android**

5. **Confirm** the session id (`ios_session_id` / `roku_session_id` / `android_session_id`)
   and tell the user they can now `/headspin:control` the device.
