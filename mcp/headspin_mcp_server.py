#!/usr/bin/env python3
"""Minimal HeadSpin MCP server (stdio, JSON-RPC 2.0, stdlib only).

Exposes a small set of REST tools for the HeadSpin `api-dev.headspin.io/v0`
surface. Every tool makes a real HTTPS call with urllib — there are no stubbed or
placeholder responses. HTTP failures are returned to the caller as tool results
with isError=true carrying the HTTP status and response body, so the model can
see exactly what the server said.

Auth carrier (verified against the 2026-07-02 raw capture, see
`e2e-evidence/headspin-forge-260702/raw-forensics/auth-inventory.md` §1a):
REST `/v0/…` is guarded by an `Authorization: Bearer <api_token>` header — proven
by the CORS preflight declaring `access-control-request-headers: authorization`
and the server ACKing `access-control-allow-headers: Authorization,Content-Type`.
There is NO `orgkey:token` header and NO cookie auth anywhere in the capture. The
per-server WebSocket / Janus surfaces (socket.io control, `/d/` screen stream,
`?jwt=` iOS control, Janus long-poll) do NOT use this header — they carry the JWT
as a query param — so they are intentionally out of scope for this REST server.

Endpoint provenance:
  hs_login_details  — GET /v0/logindetails  → HAR-OBSERVED. UNAUTHENTICATED
                      org/env probe (`?org_id=&hostname=`); a 200 confirms API
                      reachability + org config, NOT token validity.
  hs_idevice_info   — GET /v0/idevice/{addr}/info?json      → HAR-OBSERVED (Bearer).
  hs_installer_list — GET /v0/idevice/{addr}/installer/list?json → HAR-OBSERVED (Bearer).
  hs_lock_device / hs_unlock_device — POST /v0/idevice/{addr}/lock|unlock →
                      DOC-INFERRED, NOT HAR-verified in this environment. The only
                      lock signal actually observed in the capture is lock STATE in
                      the socket.io `devicelist[].lockId`/`owner`/`using` fields
                      (a WebSocket surface this REST server does not reach).
Android / Cast / Fire TV inventory is NOT a REST route — it is the socket.io
`devicelist` event on the control ports; `/v0/devices*` is never called in the
capture and is not exposed here.

Config comes from the environment, wired by the plugin's .mcp.json:
  HS_API_TOKEN  Bearer token (from userConfig.api_token, keychain-backed)
  HS_API_HOST   REST base URL (default https://api-dev.headspin.io)

Transport: newline-delimited JSON-RPC 2.0 messages on stdin/stdout, per the MCP
stdio transport (one message per line, no embedded newlines).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "headspin"
SERVER_VERSION = "0.2.0"
DEFAULT_HOST = "https://api-dev.headspin.io"
HTTP_TIMEOUT = 30


class HeadSpinHTTPError(Exception):
    """Carries an HTTP status + body back to the tool-call layer."""

    def __init__(self, status, body):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def _api_host():
    return (os.environ.get("HS_API_HOST") or DEFAULT_HOST).rstrip("/")


def _api_token():
    token = os.environ.get("HS_API_TOKEN")
    if not token:
        raise HeadSpinHTTPError(
            0,
            "HS_API_TOKEN is not set. Enable the headspin-control plugin and "
            "set api_token in /plugin, or run /headspin:login.",
        )
    return token


def _request(method, path, query=None, body=None):
    """Perform a real HTTP request and return parsed JSON (or raw text)."""
    url = _api_host() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {
        "Authorization": "Bearer " + _api_token(),
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - best-effort body capture
            detail = exc.reason or ""
        raise HeadSpinHTTPError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise HeadSpinHTTPError(0, f"connection error: {exc.reason}") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


# --- Tool implementations (each makes a real REST call) --------------------
#
# REST device addressing (HAR-observed): the path segment is the iOS device
# address `{udid}@{proxy-host}.headspin.io` — the UDID joined to its physical
# proxy host with `@` (auth-inventory.md §2/§3). Android/Cast/Fire TV devices are
# NOT addressed by REST; their roster and lock state ride the socket.io
# `devicelist` event, so they are out of scope for this REST server.


def tool_login_details(args):
    # HAR-OBSERVED, UNAUTHENTICATED org/env probe. A 200 confirms API
    # reachability + org config; it does NOT prove the token is valid. Optional
    # org_id / hostname query params echo the org identifier + UI host.
    query = {}
    if args.get("org_id"):
        query["org_id"] = str(args["org_id"])
    if args.get("hostname"):
        query["hostname"] = str(args["hostname"])
    return _request("GET", "/v0/logindetails", query=query or None)


def _idevice_addr(args):
    """Resolve the REST device-address path segment `{udid}@{host}`."""
    addr = args.get("device_address")
    if not addr:
        raise HeadSpinHTTPError(
            0,
            "device_address is required, in the form {udid}@{proxy-host}.headspin.io "
            "(e.g. 00008030-001174DE2260402E@dev-ca-tor-0-proxy-3-mac.headspin.io).",
        )
    return urllib.parse.quote(str(addr), safe="@.-")


def tool_list_devices(args):
    # LIVE-VERIFIED: GET /v0/devices -> 200 {"devices":[...]} full account roster
    # (android/ios/roku/tizentv/safari), Bearer header. The base HAR never called
    # this route (the UI web app lists via the socket.io `devicelist` event), but it
    # is a real authenticated REST endpoint proven against api-dev.headspin.io on
    # 2026-07-02 (live-validation/probe1-devices.json, 34 devices).
    return _request("GET", "/v0/devices")


def tool_idevice_info(args):
    # HAR-OBSERVED: GET /v0/idevice/{addr}/info?json -> 200 flat iOS lockdownd
    # property dump. Bearer header. Contains device properties only; NO lock /
    # reservation / owner fields (auth-inventory.md §3).
    return _request("GET", "/v0/idevice/%s/info" % _idevice_addr(args), query={"json": ""})


def tool_installer_list(args):
    # HAR-OBSERVED: GET /v0/idevice/{addr}/installer/list?json -> {"data":[...]}
    # installed-app inventory (each entry = raw Info.plist). Bearer header
    # (auth-inventory.md §4).
    return _request(
        "GET", "/v0/idevice/%s/installer/list" % _idevice_addr(args), query={"json": ""}
    )


def tool_lock_device(args):
    # LIVE-VERIFIED 2026-07-02: POST /v0/idevice/{addr}/lock -> 200
    # {"status":0,"message":"{addr} locked."}. Reserves the device for exclusive
    # use; the caller MUST unlock when done (see hs_unlock_device). The account-level
    # POST /v0/devices/lock {"device_id":X} also works, but this per-device route is
    # safer — it targets exactly {addr} and never grabs a random free device.
    return _request("POST", "/v0/idevice/%s/lock" % _idevice_addr(args))


def tool_unlock_device(args):
    # LIVE-VERIFIED 2026-07-02: POST /v0/idevice/{addr}/unlock -> 200. Releases a
    # lock held by hs_lock_device. Always call after a lock, even on error paths.
    # NOTE: reservation state is carried by `owner_email`/`session_id` on the
    # /v0/devices roster, NOT by the ambient `lock_id` UUID (13/33 idle devices
    # carry a bare lock_id with null owner). A `{"status":1,"message":"Did not
    # unlock."}` response means "no owned lease to release" (success, not error).
    return _request("POST", "/v0/idevice/%s/unlock" % _idevice_addr(args))


_DEVICE_ADDR_SCHEMA = {
    "type": "string",
    "description": (
        "iOS device address `{udid}@{proxy-host}.headspin.io` — the UDID joined "
        "to its physical proxy host with `@` (e.g. "
        "00008030-001174DE2260402E@dev-ca-tor-0-proxy-3-mac.headspin.io)."
    ),
}

TOOLS = [
    {
        "name": "hs_login_details",
        "description": (
            "GET /v0/logindetails — HeadSpin org/environment probe. HAR-OBSERVED and "
            "UNAUTHENTICATED: a 200 confirms API reachability and org config, but does "
            "NOT prove the API token is valid. Optional org_id / hostname query params."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string", "description": "Org identifier (NOT a credential)."},
                "hostname": {"type": "string", "description": "UI host to echo (e.g. ui-dev.headspin.io)."},
            },
            "additionalProperties": False,
        },
        "handler": tool_login_details,
    },
    {
        "name": "hs_list_devices",
        "description": (
            "GET /v0/devices — full HeadSpin account device roster (android/ios/roku/"
            "tizentv/safari). Returns {\"devices\":[{serial, model, manufacturer, "
            "device_type, hostname, status, os_version, device_address, ...}]}. "
            "LIVE-VERIFIED against api-dev.headspin.io (Bearer). status 3 = online/ready."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "handler": tool_list_devices,
    },
    {
        "name": "hs_idevice_info",
        "description": (
            "GET /v0/idevice/{device_address}/info?json — return an iOS device's "
            "lockdownd property dump (model, iOS version, identity). Bearer-authed, "
            "HAR-OBSERVED. iOS only; Android/Cast/Fire TV inventory is the socket.io "
            "`devicelist` event, not a REST route. Contains no lock/owner state."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"device_address": _DEVICE_ADDR_SCHEMA},
            "required": ["device_address"],
            "additionalProperties": False,
        },
        "handler": tool_idevice_info,
    },
    {
        "name": "hs_installer_list",
        "description": (
            "GET /v0/idevice/{device_address}/installer/list?json — return the installed-"
            "app inventory ({\"data\":[...]}, each entry a raw Info.plist) for an iOS "
            "device. Bearer-authed, HAR-OBSERVED. iOS only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"device_address": _DEVICE_ADDR_SCHEMA},
            "required": ["device_address"],
            "additionalProperties": False,
        },
        "handler": tool_installer_list,
    },
    {
        "name": "hs_lock_device",
        "description": (
            "POST /v0/idevice/{device_address}/lock — reserve an iOS device. "
            "DOC-INFERRED / NOT HAR-verified in this environment: the only observed lock "
            "signal is state in the socket.io `devicelist` (lockId/owner/using), which "
            "this REST server does not reach. Expect this route may not exist here."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"device_address": _DEVICE_ADDR_SCHEMA},
            "required": ["device_address"],
            "additionalProperties": False,
        },
        "handler": tool_lock_device,
    },
    {
        "name": "hs_unlock_device",
        "description": (
            "POST /v0/idevice/{device_address}/unlock — release an iOS device lock. "
            "DOC-INFERRED / NOT HAR-verified in this environment (see hs_lock_device)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"device_address": _DEVICE_ADDR_SCHEMA},
            "required": ["device_address"],
            "additionalProperties": False,
        },
        "handler": tool_unlock_device,
    },
]

_TOOL_INDEX = {t["name"]: t for t in TOOLS}


# --- JSON-RPC plumbing -----------------------------------------------------


def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle_tools_call(params):
    name = params.get("name")
    tool = _TOOL_INDEX.get(name)
    if tool is None:
        return _tool_text_result(f"Unknown tool: {name}", is_error=True)
    args = params.get("arguments") or {}
    try:
        payload = tool["handler"](args)
    except HeadSpinHTTPError as exc:
        return _tool_text_result(
            json.dumps({"error": "http_error", "status": exc.status, "body": exc.body}),
            is_error=True,
        )
    except Exception as exc:  # noqa: BLE001 - surface any handler failure as tool error
        return _tool_text_result(
            json.dumps({"error": "tool_exception", "detail": str(exc)}), is_error=True
        )
    return _tool_text_result(json.dumps(payload, indent=2))


def dispatch(message):
    """Return a response dict, or None for notifications (no id)."""
    msg_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        listed = [
            {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
            for t in TOOLS
        ]
        return _result(msg_id, {"tools": listed})
    if method == "tools/call":
        return _result(msg_id, handle_tools_call(params))

    if msg_id is None:
        return None  # unknown notification: ignore
    return _error(msg_id, -32601, f"Method not found: {method}")


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            out.write(json.dumps(_error(None, -32700, "Parse error")) + "\n")
            out.flush()
            continue
        try:
            response = dispatch(message)
        except Exception as exc:  # noqa: BLE001 - never crash the loop
            response = _error(message.get("id"), -32603, f"Internal error: {exc}")
        if response is not None:
            out.write(json.dumps(response) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
