# Installing HeadSpin Control

A step-by-step install guide for any HeadSpin customer. Every command and every
sample output below is **real** — captured from the 2026-07-02 validation run against
`api-dev.headspin.io`, not invented.

---

## Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Claude Code ≥ 2.1 | plugin host | `claude --version` → `2.1.198 (Claude Code)` |
| Python 3.8+ | MCP server + probes (stdlib only) | `python3 --version` |
| `Appium-Python-Client` | required for app exploration (`/headspin:explore`) | `pip install Appium-Python-Client` |
| A HeadSpin account + API token | every live call is real | see **Getting your API token** below |

The **20 MCP tools and the WebSocket probes are stdlib-only** — there is nothing to
`pip install` to use them. The **app-exploration path** (`/headspin:explore`, which drives
a real Appium `wd/hub` session and analyzes the app's accessibility tree) requires the
Appium client: `pip install Appium-Python-Client`. If you want to drive the plugin
programmatically you can also add the Agents SDK (`pip install claude-agent-sdk`).

---

## 1. Add the plugin marketplace

The plugin ships with its own dev marketplace (`.claude-plugin/marketplace.json`).
Point Claude Code at the plugin directory:

```bash
/plugin marketplace add /path/to/headspin-control
```

## 2. Install and enable

```bash
/plugin install headspin-control@headspin-dev
```

Restart Claude Code, then confirm it is enabled:

```bash
claude plugin list
```

Real output from this environment:

```
  ❯ headspin-control@headspin-dev
    Version: 1.2.0
    Scope: user
```

## 3. Validate the install (optional but recommended)

```bash
claude plugin validate /path/to/headspin-control
```

Expected:

```
Validating marketplace manifest: .../headspin-control/.claude-plugin/marketplace.json

✔ Validation passed
```

## 4. What got installed

| Type | Count | Entry points |
|------|-------|--------------|
| Skills | 14 | model-invoked; Claude chains them autonomously |
| Commands | 10 | `/headspin:setup` `/headspin:login` `/headspin:devices` `/headspin:connect` `/headspin:control` `/headspin:capture` `/headspin:explore` `/headspin:report` `/headspin:sessions` `/headspin:waterfall` |
| Agents | 2 | `device-explorer`, `bug-reporter` |
| Hooks | 3 | token-safety + connection-lifecycle guards (`hooks/hooks.json`) |
| MCP server | 1 | `headspin` (stdio, stdlib-only) — 20 REST tools |

---

## Getting your API token

The token is created in the HeadSpin web UI (**User Settings → API Tokens**) — there is
no REST endpoint to mint one. Two ways to give it to the plugin:

1. **`/headspin:login`** — opens your environment's UI in a browser so you can sign in
   and copy your token (and, for the control/streaming planes, obtain the browser-login
   identity JWT). This is the recommended path.
2. **Plugin config** — set `api_token` in `/plugin` config; it is stored in the OS
   keychain and surfaced to the tools as `HS_API_TOKEN` /
   `CLAUDE_PLUGIN_OPTION_API_TOKEN`. REST calls send it as `Authorization: Bearer <token>`.

> **Security:** the token is a credential. Keep it in the keychain / env, never in a
> committed file. The plugin never writes it to disk in plaintext.

---

## Verifying it actually works (real smoke test)

Once your token is set, the fastest real check is the bundled MCP server answering a
live `GET /v0/logindetails` and `GET /v0/devices`. From a shell:

```bash
export HS_API_TOKEN=<your-token>
export HS_API_HOST=https://api-dev.headspin.io   # your environment's API host
python3 - <<'PY'
import json, subprocess, sys, os
p = subprocess.Popen([sys.executable, "mcp/headspin_mcp_server.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=os.environ.copy())
def call(m, params=None):
    msg = {"jsonrpc":"2.0","id":1,"method":m}
    if params: msg["params"]=params
    p.stdin.write(json.dumps(msg)+"\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())
call("initialize", {"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}})
r = call("tools/call", {"name":"hs_list_devices","arguments":{}})
body = json.loads(r["result"]["content"][0]["text"])
print("devices:", len(body.get("devices", [])))
p.stdin.close()
PY
```

Real result from validation: `devices: 34` (types: android, ios, roku, safari, tizentv).
If you see your device count, the plugin is wired to your live environment.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `HS_API_TOKEN is not set` from a tool | token not configured | run `/headspin:login` or set `api_token` in `/plugin` config |
| `401` from a REST tool | token revoked/invalid | re-run `/headspin:login`; the token is not auto-rotated |
| socket.io WS returns `"Failed to decode jwt access_token."` | you passed the API token / a `/v0/jwt/permissions` lease JWT to a control WS | the control planes need the **browser-login identity JWT** — get it via `/headspin:login`, not the account token |
| `claude plugin list` doesn't show it | forgot to restart after install | restart Claude Code |
