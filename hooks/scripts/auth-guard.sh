#!/usr/bin/env bash
# PreToolUse(Bash): block HeadSpin API calls when the plugin is not authenticated.
# Reads the tool-call JSON from stdin. If the Bash command targets a HeadSpin API
# host / endpoint AND no token env var is set AND the login sentinel is missing,
# block with guidance (stderr + exit 2). Otherwise exit 0 silently.
set -uo pipefail

payload="$(cat)"

# Extract the command string from tool_input. Prefer jq; fall back to python3.
if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')"
elif command -v python3 >/dev/null 2>&1; then
  cmd="$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)"
else
  # No parser available — do not block; fail open.
  exit 0
fi

# Only guard commands that actually touch a HeadSpin API surface.
case "$cmd" in
  *api-dev.headspin.io*|*api.headspin.io*|*/v0/*) ;;
  *) exit 0 ;;
esac

# Authenticated if a token env var is present, or the login sentinel exists.
if [[ -n "${HS_API_TOKEN:-}" ]] \
  || [[ -n "${CLAUDE_PLUGIN_OPTION_API_TOKEN:-}" ]] \
  || [[ -f /tmp/headspin-control/env.sh ]]; then
  exit 0
fi

echo "HeadSpin auth required: this command calls a HeadSpin API endpoint but no API token is set and /tmp/headspin-control/env.sh is missing." >&2
echo "Run /headspin:login first (it validates the token and writes the session env), then retry." >&2
exit 2
