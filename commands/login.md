---
description: Authenticate to a HeadSpin environment — open the UI to sign in, accept a pasted API token, validate, and persist non-secret env.
argument-hint: "[api-token] [api_host=<url>] [ui_host=<url>]"
---

# /headspin:login

Authenticate the plugin to a HeadSpin environment. HeadSpin API tokens can only be
**created in the web UI** (User Settings → API Tokens) — there is no credentials-for-token
API. NEVER type the user's username or password for them.

## Steps

1. **Parse `$ARGUMENTS`** — a bare token, plus optional `api_host=` / `ui_host=` overrides.
   Overrides take precedence over `CLAUDE_PLUGIN_OPTION_API_HOST` / `_UI_HOST` for this run.

2. **If no token is available** (`$ARGUMENTS` empty AND `CLAUDE_PLUGIN_OPTION_API_TOKEN`
   unset), open the UI so the user signs in themselves and copies a token:

   ```bash
   open "${UI_HOST:-${CLAUDE_PLUGIN_OPTION_UI_HOST}}"   # macOS; use xdg-open on Linux
   ```

   Then ask the user to paste the token from Settings → API Tokens. Do not proceed until
   you have a token.

3. **Probe reachability, then validate the token.** `GET /v0/logindetails` is an **unauthenticated** org/env probe — a `200` proves only that the API host is reachable, not that the token is valid (`e2e-evidence/headspin-forge-260702/har-forensics/API-CONTRACT.md` §1):

   ```bash
   # reachability (no auth header needed)
   curl -sS -o /dev/null -w "%{http_code}" \
     "${API_HOST:-${CLAUDE_PLUGIN_OPTION_API_HOST}}/v0/logindetails"

   # token validation — exercise the Bearer header against a real Bearer-authed route
   curl -sS -o /dev/null -w "%{http_code}" \
     -H "Authorization: Bearer ${TOKEN}" \
     "${API_HOST:-${CLAUDE_PLUGIN_OPTION_API_HOST}}/v0/idevice/{udid}@{proxy-host}.headspin.io/info?json"
   ```

   Second call `200` → token accepted. `401` → wrong token/host; show the status and stop. If no iOS `device_address` is known yet, defer validation to the first `/headspin:devices` call. Do NOT send `orgkey:token` — that header format does not exist here (`API-CONTRACT.md` DL-1).

4. **Persist non-secret env** to a session file (token stays out of disk):

   ```bash
   mkdir -p /tmp/headspin-control
   umask 077
   cat > /tmp/headspin-control/env.sh <<EOF
   export HEADSPIN_API_HOST="${API_HOST:-${CLAUDE_PLUGIN_OPTION_API_HOST}}"
   export HEADSPIN_UI_HOST="${UI_HOST:-${CLAUDE_PLUGIN_OPTION_UI_HOST}}"
   EOF
   chmod 600 /tmp/headspin-control/env.sh
   ```

5. **Direct the user to store the token durably** — put it in the plugin `userConfig`
   (`api_token`, sensitive → OS keychain) via `/plugin`, or `export HS_API_TOKEN=…` for the
   shell. Never write the token to `/tmp` or `settings.json`.

6. **Invoke the headspin-login skill** for the full flow (env resolution, tunnel-host
   resolution, device-count summary).
