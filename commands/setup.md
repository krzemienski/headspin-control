---
description: Onboard the HeadSpin Control plugin — verify config, explain userConfig, and confirm API connectivity.
argument-hint: "(no args)"
---

# /headspin:setup

Guide the user through first-time setup of the HeadSpin Control plugin. Do NOT type
credentials for the user and NEVER echo the token value.

## Steps

1. **Check resolved config** from the plugin's injected env vars:

   ```bash
   echo "API : ${CLAUDE_PLUGIN_OPTION_API_HOST:-<unset>}"
   echo "UI  : ${CLAUDE_PLUGIN_OPTION_UI_HOST:-<unset>}"
   echo "Tunnel: ${CLAUDE_PLUGIN_OPTION_TUNNEL_HOST:-<unset>}:${CLAUDE_PLUGIN_OPTION_TUNNEL_PORT:-<unset>}"
   echo "Token set: $([ -n \"${CLAUDE_PLUGIN_OPTION_API_TOKEN}\" ] && echo yes || echo NO)"
   ```

2. **If any required value is unset**, tell the user to run `/plugin`, enable
   `headspin-control`, and fill `api_host`, `ui_host`, and `api_token` (marked
   sensitive → stored in the OS keychain). If they have no token yet, point them at
   `/headspin:login` to obtain one from the UI.

3. **Verify connectivity** — first an unauthenticated reachability probe, then a Bearer-authed check:

   ```bash
   # (a) reachability — /v0/logindetails is UNAUTHENTICATED; 200 only proves the host is reachable, NOT that the token is valid
   curl -sS -o /dev/null -w "%{http_code}" \
     "${CLAUDE_PLUGIN_OPTION_API_HOST}/v0/logindetails"

   # (b) token check — exercise the Authorization: Bearer header against a real Bearer-authed route (per-device iOS info)
   curl -sS -o /dev/null -w "%{http_code}" \
     -H "Authorization: Bearer ${CLAUDE_PLUGIN_OPTION_API_TOKEN}" \
     "${CLAUDE_PLUGIN_OPTION_API_HOST}/v0/idevice/{udid}@{proxy-host}.headspin.io/info?json"
   ```

   - `(a) 200` → API host reachable. (Does **not** validate the token — `logindetails` takes no auth.)
   - `(b) 200` → token accepted.
   - `(b) 401` → token revoked or wrong `api_host`; suggest `/headspin:login`.
   - `(b) 403` → token lacks the permission for that route; an org admin must grant it.

   There is no `/v0/devices/keys` route and no `orgkey:token` header in this environment (`e2e-evidence/headspin-forge-260702/har-forensics/API-CONTRACT.md` §1, DL-1/DL-6). If no iOS `device_address` is known, skip (b) and let `/headspin:devices` surface a `401` instead.

4. **Print the resolved environment** as a single copyable line, then suggest next
   steps: `/headspin:login` (if not authenticated) or `/headspin:devices`.

For the full auth + env-persistence flow, invoke the **headspin-login** skill.
