---
description: Drive an already-connected HeadSpin device — screenshot, keypress, tap, swipe, type, launch app.
argument-hint: "<device> <action...>"
---

# /headspin:control

Send control verbs to a device that already has a live session.

## Steps

1. **Pre-flight auth** — token required:

   ```bash
   [ -n "${CLAUDE_PLUGIN_OPTION_API_TOKEN}" ] || { echo "No token — run /headspin:login"; exit 1; }
   ```

   Any `401` downstream → stop and suggest `/headspin:login`.

2. **Resolve the device + type** from `$ARGUMENTS`, falling back to
   `/tmp/headspin-control/selected-type.txt`. If no live session file exists
   (`/tmp/headspin-control/{ios,roku}-session.json`), tell the user to run
   `/headspin:connect` first.

3. **Parse the action verbs** from the rest of `$ARGUMENTS`, e.g.
   `screenshot`, `keypress Home`, `tap 200 400`, `swipe …`, `type "hello"`,
   `launch <bundle-id|app-id>`, `hierarchy`.

4. **Route by device type** to the matching control skill:
   - iOS → **headspin-control-ios** (tap/swipe/type/hardware buttons/launch/screenshot/XML hierarchy)
   - Roku → **headspin-control-roku** (ECP keypress/launch/text/screenshot/UI hierarchy)

5. **Return evidence** — surface the screenshot path or command output. If the websocket
   dropped, **headspin-connection-manager** re-establishes it; retry once.
