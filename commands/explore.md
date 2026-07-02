---
description: Run bounded automated exploration on a connected device to surface bugs, capturing evidence bundles.
argument-hint: "<device> [app]"
---

# /headspin:explore

Autonomously explore a device (optionally scoped to one app) via bounded breadth-first
navigation, capturing an evidence bundle for anything anomalous.

## Steps

1. **Pre-flight auth** — token required:

   ```bash
   [ -n "${CLAUDE_PLUGIN_OPTION_API_TOKEN}" ] || { echo "No token — run /headspin:login"; exit 1; }
   ```

   Any `401` downstream → stop and suggest `/headspin:login`.

2. **Resolve device + optional app** from `$ARGUMENTS`, defaulting the device to
   `/tmp/headspin-control/selected-device.txt`. Require a live session
   (`/tmp/headspin-control/{ios,roku}-session.json`); if absent, run `/headspin:connect`.

3. **Invoke the headspin-explore-bugs skill** with the device and app. It drives a bounded
   BFS over reachable UI states via the control skills, capturing screenshots + UI
   hierarchy at each step and flagging anomalies into a timestamped run directory.

4. **Report the run directory** path and a one-line summary of findings. Hand the run dir
   to `/headspin:report` to produce a standardized bug report.
