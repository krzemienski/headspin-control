---
name: headspin-login
description: Authenticate the HeadSpin Control plugin to a HeadSpin environment, persist the bearer token in the OS keychain via ${user_config.api_token}, and surface the resolved environment (UI host, API host, per-platform control hosts/ports) for downstream skills. REST calls use Authorization Bearer; the websocket control/stream surfaces use ?access_token=/?jwt= query params, not Bearer. Invoke when the user runs /headspin:login, when a downstream skill reports "401 Unauthorized", or when the user asks to switch HeadSpin environments.
allowed-tools: Read, Bash, Grep
---

# headspin-login

## When to use

- User runs `/headspin:login` (first time or switching environments).
- A downstream skill (`headspin-list-devices`, `headspin-connect-*`) returns 401 or 403 and you need to refresh the token.
- The user pastes a new API token and asks to apply it.

## Inputs

The plugin manifest (`.claude-plugin/plugin.json`) declares the inputs via `userConfig`. The skill reads them at runtime through `${user_config.<KEY>}` substitution:

| Key | Source | Purpose |
|---|---|---|
| `api_host` | `userConfig.api_host` | REST API base (e.g. `https://api-dev.headspin.io`). |
| `ui_host` | `userConfig.ui_host` | Web UI base (e.g. `https://ui-dev.headspin.io`). |
| `api_token` | `userConfig.api_token` (sensitive) | Bearer token, stored in the OS keychain by Claude Code. |
| `tunnel_host` | `userConfig.tunnel_host` | Default region host for per-device websockets. |
| `tunnel_port` | `userConfig.tunnel_port` | Default region port for per-device websockets. |

Never read the token literal from a HAR file, a .env, or a prompt. The plugin's `sensitive: true` flag sends it to the keychain, not `settings.json`.

## Workflow

1. **Read config via env** — every downstream command consumes these as `CLAUDE_PLUGIN_OPTION_<KEY>` (see plugins-reference.md, "Environment variables" section). To confirm the values are set, run:

   ```bash
   echo "API: $CLAUDE_PLUGIN_OPTION_API_HOST  UI: $CLAUDE_PLUGIN_OPTION_UI_HOST  Tunnel: $CLAUDE_PLUGIN_OPTION_TUNNEL_HOST:$CLAUDE_PLUGIN_OPTION_TUNNEL_PORT"
   ```

   If any required value is empty, stop and tell the user to run `/plugin` and enable the plugin with the missing config.

2. **Probe the environment (unauthenticated)** — call `GET ${CLAUDE_PLUGIN_OPTION_API_HOST}/v0/logindetails`. This is an **unauthenticated org/env config probe** (it takes optional `?org_id=&hostname=` query params and returns `{"email": true, "organization_name": "…"}`); a `200` confirms the API host is reachable and the org config, but it does **NOT** prove the API token is valid — the HAR captures no auth header on this request. Do not treat a `200` here as "token accepted".

   **Validate the token (Bearer-authed)** — to actually exercise the `Authorization: Bearer <api_token>` header, call a REST endpoint that requires it. The one Bearer-authed GET proven in the 2026-07-02 raw capture is the per-device iOS info route:

   ```bash
   curl -sS -o /dev/null -w "%{http_code}" \
     -H "Authorization: Bearer ${CLAUDE_PLUGIN_OPTION_API_TOKEN}" \
     "${CLAUDE_PLUGIN_OPTION_API_HOST}/v0/idevice/{udid}@{proxy-host}.headspin.io/info?json"
   ```

   A `200` means the token is accepted; a `401` means the token is revoked or the API host is wrong — surface the exact status and body so the user can correct it. If no iOS `device_address` is known yet, skip this and let the first `headspin-list-devices` call surface a `401` instead. (The REST `authorization` header carrier is proven by CORS preflight, `raw-forensics/auth-inventory.md` §1a; there is **no** `orgkey:token` header and **no** `/v0/devices/keys` route in the capture.)

3. **Resolve the actual tunnel host** — the 2026-07-02 capture shows the per-device WebSocket host is **not** the UI host. The UI host is `ui-dev.headspin.io`; the socket.io control / `/d/` screen host is `dev-ca-tor-0.headspin.io`, and iOS control lives on a **different** region host (`dev-in-blr-0.headspin.io:5002`). The exact host + port for a given device must be resolved at connect time from the device record's `display.url` (Android/Cast/Fire TV) or the iOS control endpoint — see `headspin-connect-ios` / `headspin-connect-android`. Do not assume `${CLAUDE_PLUGIN_OPTION_TUNNEL_HOST}` is correct for every device.

4. **Persist the env** — for this session only, export the resolved values to a temp file the other skills can source:

   ```bash
   mkdir -p /tmp/headspin-control
   cat > /tmp/headspin-control/env.sh <<EOF
   export HEADSPIN_API_HOST="$CLAUDE_PLUGIN_OPTION_API_HOST"
   export HEADSPIN_UI_HOST="$CLAUDE_PLUGIN_OPTION_UI_HOST"
   export HEADSPIN_TUNNEL_HOST="$CLAUDE_PLUGIN_OPTION_TUNNEL_HOST"
   export HEADSPIN_TUNNEL_PORT="$CLAUDE_PLUGIN_OPTION_TUNNEL_PORT"
   # The bearer token is read inline from $CLAUDE_PLUGIN_OPTION_API_TOKEN;
   # never written to disk.
   EOF
   chmod 600 /tmp/headspin-control/env.sh
   ```

   The token itself is never persisted to disk. Every downstream skill reads it from the env var, not from the temp file.

5. **Surface the resolved environment** — print a single-line summary the user can copy:

   ```text
   Logged in to HeadSpin dev. API: api-dev.headspin.io  UI: ui-dev.headspin.io  Android control host: dev-ca-tor-0.headspin.io (ports 23100/27100/33100/34100)  iOS control host: dev-in-blr-0.headspin.io:5002
   ```

   Do **not** compute a device count here from a `/v0/devices` call — that REST route is **not exercised in the capture** and is not a real inventory carrier (`API-CONTRACT.md` DL-6). Device inventory has two real carriers, surfaced by `headspin-list-devices`: iOS via REST `idevice/info`, and Android/Cast/Fire TV via the socket.io `devicelist` event on the control ports. Point the user at `/headspin:devices` for the roster.

## Evidence

- REST auth carrier: `e2e-evidence/headspin-forge-260702/raw-forensics/auth-inventory.md` §1a — REST `/v0/…` is guarded by an `Authorization: Bearer <JWT>` header, proven by the CORS preflight (`access-control-request-headers: authorization` → server `access-control-allow-headers: Authorization,Content-Type`). No `orgkey:token`, no cookie auth.
- `logindetails` is unauthenticated: `e2e-evidence/headspin-forge-260702/har-forensics/API-CONTRACT.md` §1 "logindetails — what it actually is" (`GET /v0/logindetails?org_id=&hostname=` → 200 org-config probe; no auth header observed).
- Bearer-authed REST GET (token validation): `raw-forensics/auth-inventory.md` §3 (`GET /v0/idevice/{udid}@{host}/info?json` → 200 with `Authorization: Bearer`).
- Websocket auth shape: `har-forensics/API-CONTRACT.md` §1 AUTH-1/AUTH-2 (socket.io control + `/d/` screen stream carry the JWT as `?access_token=` query param — **not** a Bearer header); iOS control WS carries it as `?jwt=` (`raw-forensics/auth-inventory.md` §1b).
- `/v0/devices*` is NOT a real inventory route: `API-CONTRACT.md` DL-6.
- Token storage: `plugins-reference.md:535-572` (`sensitive: true` routes to the OS keychain).
- Variable substitution contract: `plugins-reference.md:637-670` (${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_PLUGIN_DATA}, ${user_config.*}).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `CLAUDE_PLUGIN_OPTION_API_TOKEN` empty | Plugin not enabled or token not set in `/plugin` UI | Re-run `/plugin` -> Configure headspin-control, paste the token. |
| `401 Unauthorized` from `/v0/idevice/…/info?json` (or any Bearer REST call) | Token revoked or wrong host | Check the user account at the UI host; if the token is valid, confirm `api_host` matches the host the token was issued against. |
| `403 Forbidden` from a Bearer REST call | Token is valid but lacks the required permission for that route | Org admin needs to grant the permission, or the user needs to be promoted. |
| `/v0/logindetails` returns 200 but downstream REST calls 401 | `logindetails` is unauthenticated — a 200 there never proved the token | Validate the token against a Bearer-authed route (step 2), not against `logindetails`. |
| Tunnel host is not `${CLAUDE_PLUGIN_OPTION_TUNNEL_HOST}` | Device is in a different region (iOS control is `dev-in-blr-0:5002`; Android control is `dev-ca-tor-0:{ctrl}`) | Resolve the host/port at connect time from the device record (`display.url`) or the iOS control endpoint; do not overwrite the plugin default. |
