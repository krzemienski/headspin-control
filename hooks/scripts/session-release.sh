#!/usr/bin/env bash
# Stop hook: if a HeadSpin device lock is still held when the session stops,
# surface a reminder to release it. Stop hooks must NOT block — this only prints
# to stderr and exits 0.
#
# Lock-marker contract: headspin-session-manager writes /tmp/headspin-control/lock.json
# on a successful POST /v0/devices/lock (carrying device_id + hostname) and removes
# it on unlock. That file is the source of truth for "is a device still locked?".
set -uo pipefail

LOCK_FILE="/tmp/headspin-control/lock.json"

# Nothing held → nothing to remind about.
[[ -s "$LOCK_FILE" ]] || exit 0

# Pull the locked device_id for a specific, actionable reminder.
device_id=""
if command -v jq >/dev/null 2>&1; then
  device_id="$(jq -r '.device_id // ""' "$LOCK_FILE" 2>/dev/null)"
elif command -v python3 >/dev/null 2>&1; then
  device_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("device_id",""))' "$LOCK_FILE" 2>/dev/null)"
fi
[[ -n "$device_id" ]] || device_id="(see $LOCK_FILE)"

{
  echo "HeadSpin device still LOCKED at session stop: ${device_id}"
  echo "Release it so it does not stay held until the ~15min server TTL:"
  echo "  POST \${HEADSPIN_API_HOST}/v0/devices/unlock  (via /headspin:disconnect or the headspin-session-manager release step)"
} >&2

exit 0
