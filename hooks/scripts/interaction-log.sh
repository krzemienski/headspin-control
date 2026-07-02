#!/usr/bin/env bash
# PostToolUse(Bash): audit-log HeadSpin interactions with tokens redacted.
# If the Bash command targeted a HeadSpin host, append a timestamped, redacted
# line to /tmp/headspin-control/interaction.log. Always exits 0 (never blocks).
set -uo pipefail

payload="$(cat)"

if command -v jq >/dev/null 2>&1; then
  cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')"
elif command -v python3 >/dev/null 2>&1; then
  cmd="$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)"
else
  exit 0
fi

# Only log HeadSpin-targeted commands.
case "$cmd" in
  *headspin.io*|*/v0/*) ;;
  *) exit 0 ;;
esac

# Redact secrets:
#  - Bearer <token>            -> Bearer «REDACTED»
#  - access_token=<token>      -> access_token=«REDACTED»
#  - /v0/<32-hex>/wd/hub       -> /v0/«REDACTED»/wd/hub
redacted="$(printf '%s' "$cmd" | sed -E \
  -e 's/([Bb]earer )[A-Za-z0-9._-]+/\1«REDACTED»/g' \
  -e 's/(access_token=)[A-Za-z0-9._-]+/\1«REDACTED»/g' \
  -e 's#(/v0/)[0-9a-fA-F]{32}(/wd/hub)#\1«REDACTED»\2#g')"

mkdir -p /tmp/headspin-control 2>/dev/null || true
printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$redacted" \
  >> /tmp/headspin-control/interaction.log 2>/dev/null || true

exit 0
