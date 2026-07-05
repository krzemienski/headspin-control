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
                      LIVE-VERIFIED 2026-07-05: full lock+unlock cycle on a real
                      iPhone 11 (00008030-…402E@dev-ca-tor-0-proxy-3-mac) returned
                      status:0 both directions. (Lock STATE also mirrors into the
                      socket.io `devicelist[].lockId`/`owner`/`using` fields.)
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
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def _ssl_context():
    """Default context, falling back to the system CA bundle when python's
    bundled certs can't verify (common on macOS python.org builds)."""
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs() and os.path.exists("/etc/ssl/cert.pem"):
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ctx


_SSL_CTX = None


def _ssl():
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = _ssl_context()
    return _SSL_CTX

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "headspin"
SERVER_VERSION = "1.2.0"
DEFAULT_HOST = "https://api-dev.headspin.io"
HTTP_TIMEOUT = 30


class HeadSpinHTTPError(Exception):
    """Carries an HTTP status + body back to the tool-call layer."""

    def __init__(self, status, body):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


LOGIN_ENV_FILE = "/tmp/headspin-control/secrets.env"
_login_env = None


def _env(name):
    # An unexpanded ${CLAUDE_PLUGIN_OPTION_*} placeholder (plugin option unset)
    # must count as absent, not as a literal value. Fall back to the
    # /headspin:login session file so the server works without plugin options.
    value = os.environ.get(name, "")
    if value and not value.startswith("${"):
        return value
    global _login_env
    if _login_env is None:
        _login_env = {}
        try:
            with open(LOGIN_ENV_FILE) as f:
                for line in f:
                    line = line.strip().removeprefix("export ")
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        _login_env[k.strip()] = v.strip().strip("\"'")
        except OSError:
            pass
    return _login_env.get(name, "")


def _api_host():
    return (_env("HS_API_HOST") or DEFAULT_HOST).rstrip("/")


def _api_token():
    token = _env("HS_API_TOKEN")
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
        if isinstance(body, str):
            # Raw text body (adb shell commands are posted verbatim, not JSON).
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_ssl()) as resp:
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


DOWNLOAD_DIR = os.environ.get("HS_DOWNLOAD_DIR", "/tmp/headspin-control/downloads")


def _request_download(path, save_path=None, query=None):
    """Stream a real binary/text artifact to disk (mp4/har/device.log/pcap/csv).

    Returns metadata (saved path, byte size, content-type) rather than the bytes
    themselves — MCP tool results are text, so a 40 MB video must not be inlined.
    """
    url = _api_host() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Authorization": "Bearer " + _api_token()}
    req = urllib.request.Request(url, headers=headers, method="GET")
    if not save_path:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        save_path = os.path.join(DOWNLOAD_DIR, os.path.basename(path) or "download.bin")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)) or ".", exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=max(HTTP_TIMEOUT, 120), context=_ssl()) as resp:
            ctype = resp.headers.get("Content-Type", "")
            total = 0
            with open(save_path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    total += len(chunk)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = exc.reason or ""
        raise HeadSpinHTTPError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise HeadSpinHTTPError(0, f"connection error: {exc.reason}") from exc
    return {"saved_to": save_path, "bytes": total, "content_type": ctype, "path": path}


def _session_id(args):
    """Resolve the required session_id path segment (a UUID string)."""
    sid = args.get("session_id")
    if not sid:
        raise HeadSpinHTTPError(
            0, "session_id is required (a session UUID, e.g. from hs_list_sessions)."
        )
    return urllib.parse.quote(str(sid), safe="-")


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


def _adb_device_id(args):
    """Resolve the ADB REST path segment — bare serial or full device address."""
    dev = args.get("device_id") or args.get("device_address")
    if not dev:
        raise HeadSpinHTTPError(
            0, "device_id is required (Android serial, e.g. RFCN80FV2TA, or full "
               "device address serial@proxy-host).")
    return urllib.parse.quote(str(dev), safe="@.-")


def tool_adb_lock(args):
    # DOC + LIVE-VERIFIED 2026-07-03: POST /v0/adb/{device_id}/lock ->
    # {"status":0,"message":"<addr> locked."}. Android/Cast/FireTV counterpart of
    # hs_lock_device. Optional timeout (retry window, seconds).
    query = {"timeout": str(args["timeout"])} if args.get("timeout") else None
    return _request("POST", "/v0/adb/%s/lock" % _adb_device_id(args), query=query)


def tool_adb_unlock(args):
    # POST /v0/adb/{device_id}/unlock — release an Android device lease. Always
    # call after hs_adb_lock, even on error paths.
    return _request("POST", "/v0/adb/%s/unlock" % _adb_device_id(args))


def tool_adb_shell(args):
    # LIVE-VERIFIED 2026-07-03: POST /v0/adb/{device_id}/shell with the raw shell
    # command as the request body -> {"stdout": "..."}. Device must be locked by
    # the caller first. This is how Android devices are DRIVEN over REST
    # (input tap/swipe/keyevent, am start, dumpsys ...).
    cmd = args.get("command")
    if not cmd:
        raise HeadSpinHTTPError(0, "command is required (an adb shell command string).")
    return _request("POST", "/v0/adb/%s/shell" % _adb_device_id(args), body=str(cmd))


def tool_start_capture(args):
    # LIVE-VERIFIED 2026-07-03: POST /v0/sessions {"session_type":"capture",
    # "device_address":...} -> {"session_id":...}. Device must be locked first
    # (hs_lock_device / hs_adb_lock). capture_video defaults true here because the
    # screen-recording MP4 is the point of a capture session.
    dev = args.get("device_address")
    if not dev:
        raise HeadSpinHTTPError(0, "device_address is required ({serial|udid}@proxy-host).")
    body = {"session_type": "capture", "device_address": str(dev),
            "capture_video": bool(args.get("capture_video", True))}
    if args.get("nowait") is not None:
        body["nowait"] = bool(args["nowait"])
    return _request("POST", "/v0/sessions", body=body)


def tool_stop_capture(args):
    # LIVE-VERIFIED 2026-07-03: PATCH /v0/sessions/{sid} {"active":false} ->
    # {"msg":"Video uploaded to .../{sid}.mp4"}. Poll hs_session_timestamps for
    # the capture-complete mark before downloading artifacts.
    return _request("PATCH", "/v0/sessions/%s" % _session_id(args), body={"active": False})


def tool_list_sessions(args):
    # HAR-DOC + LIVE-VERIFIED (2026-07-02): GET /v0/sessions -> 200
    # {"sessions":[...], "next_token":...}. Capture sessions in the org, newest
    # first. `include_all=true` returns ended sessions too (default false = live
    # only); `num_sessions` caps the page (max 100); `next_token` paginates.
    query = {}
    if args.get("include_all") is not None:
        query["include_all"] = "true" if args.get("include_all") else "false"
    if args.get("num_sessions"):
        query["num_sessions"] = str(args["num_sessions"])
    if args.get("next_token"):
        query["next_token"] = str(args["next_token"])
    return _request("GET", "/v0/sessions", query=query or None)


def tool_session_timestamps(args):
    # GET /v0/sessions/{sid}/timestamps -> capture-started/-ended/-complete epoch
    # marks. 404 if the session has no timestamps yet (still capturing) or is
    # unknown. Used to poll a nowait capture to ready/complete.
    return _request("GET", "/v0/sessions/%s/timestamps" % _session_id(args))


def tool_session_issues(args):
    # GET /v0/sessions/analysis/issues/{sid} -> the SAME data shown in the
    # Waterfall UI issue card (Low Frame Rate, Domain Sharding, etc.) — the core
    # of a HeadSpin report. `orient=column` (default) or `record`.
    query = {"orient": args["orient"]} if args.get("orient") in ("column", "record") else None
    return _request("GET", "/v0/sessions/analysis/issues/%s" % _session_id(args), query=query)


def tool_analysis_status(args):
    # GET /v0/sessions/analysis/status/{sid}?timeout=N -> {status: done|timeout|
    # error}. timeout=0 checks current state without blocking (the safe default
    # here); optional `track` narrows to a specific analysis.
    query = {"timeout": str(args.get("timeout", 0))}
    if args.get("track"):
        query["track"] = str(args["track"])
    return _request("GET", "/v0/sessions/analysis/status/%s" % _session_id(args), query=query)


def tool_session_timeseries_info(args):
    # GET /v0/sessions/timeseries/{sid}/info -> dict of available time series
    # (impact, memory_used, frame_rate, ...) each with name/category/units. This
    # is "what occurred on the device" as measurable signals.
    return _request("GET", "/v0/sessions/timeseries/%s/info" % _session_id(args))


def tool_session_timeseries_download(args):
    # GET /v0/sessions/timeseries/{sid}/download?key=K -> CSV of one time series
    # over the session timeline. Saved to disk (CSV can be large); the tool
    # returns the saved path + byte size, not the CSV body.
    key = args.get("key")
    if not key:
        raise HeadSpinHTTPError(0, "key is required (a time_series_key from hs_session_timeseries_info).")
    save = args.get("save_path") or os.path.join(DOWNLOAD_DIR, "%s-%s.csv" % (args.get("session_id"), key))
    return _request_download(
        "/v0/sessions/timeseries/%s/download" % _session_id(args),
        save_path=save, query={"key": str(key)},
    )


def tool_session_video_metadata(args):
    # GET /v0/sessions/{sid}/video/metadata -> dimensions/fps/duration/codec/audio.
    return _request("GET", "/v0/sessions/%s/video/metadata" % _session_id(args))


def tool_session_download(args):
    # GET /v0/sessions/{sid}.{ext} -> stream a captured artifact to disk. ext is
    # the device-event / waterfall raw data: har (network waterfall), mar, csv,
    # device.log.gz (device events), appium.log.gz, mp4 (screen recording), pcap.
    # Saved to disk; returns path + size, never the bytes.
    ext = args.get("ext")
    allowed = {"har", "mar", "csv", "mp4", "pcap", "device.log.gz", "device.log",
               "appium.log.gz", "appium.log", "selenium.log.gz", "jsconsole.log.gz",
               "sslkeylog.txt"}
    if ext not in allowed:
        raise HeadSpinHTTPError(0, "ext must be one of: %s" % ", ".join(sorted(allowed)))
    sid = args.get("session_id")
    if not sid:
        raise HeadSpinHTTPError(0, "session_id is required.")
    query = {}
    if ext == "har" and args.get("enhanced"):
        query["enhanced"] = "True"
    if ext == "mp4" and args.get("fps"):
        query["fps"] = str(args["fps"])
    save = args.get("save_path") or os.path.join(DOWNLOAD_DIR, "%s.%s" % (sid, ext))
    return _request_download("/v0/sessions/%s.%s" % (urllib.parse.quote(str(sid), safe="-"), ext),
                             save_path=save, query=query or None)


def tool_session_tls_exceptions(args):
    # GET /v0/sessions/{sid}/tlsexceptions -> {host: exception_count}. Surfaces
    # hosts whose TLS pinning broke network capture (a real waterfall gap signal).
    return _request("GET", "/v0/sessions/%s/tlsexceptions" % _session_id(args))


_DEVICE_ADDR_SCHEMA = {
    "type": "string",
    "description": (
        "iOS device address `{udid}@{proxy-host}.headspin.io` — the UDID joined "
        "to its physical proxy host with `@` (e.g. "
        "00008030-001174DE2260402E@dev-ca-tor-0-proxy-3-mac.headspin.io)."
    ),
}

_SESSION_ID_SCHEMA = {
    "type": "string",
    "description": "A HeadSpin capture session UUID (from hs_list_sessions).",
}

_ADB_DEVICE_SCHEMA = {
    "type": "string",
    "description": (
        "Android device serial (e.g. RFCN80FV2TA) or full device address "
        "serial@proxy-host.headspin.io."
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
            "LIVE-VERIFIED 2026-07-05: lock+unlock cycle on a real iPhone 11 returned "
            "status:0 both directions. Counterpart of hs_adb_lock (Android). Always "
            "pair with hs_unlock_device on exit."
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
            "LIVE-VERIFIED 2026-07-05 (see hs_lock_device). Always call after a lock, "
            "even on error paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"device_address": _DEVICE_ADDR_SCHEMA},
            "required": ["device_address"],
            "additionalProperties": False,
        },
        "handler": tool_unlock_device,
    },
    # --- v1.1 session / waterfall / report / device-event surface (Bearer REST) ---
    {
        "name": "hs_adb_lock",
        "description": (
            "POST /v0/adb/{device_id}/lock — reserve an Android/Cast/FireTV device by "
            "serial. LIVE-VERIFIED 2026-07-03. Optional timeout = retry window in "
            "seconds. Counterpart of hs_lock_device (iOS)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": _ADB_DEVICE_SCHEMA,
                "timeout": {"type": "integer", "description": "Retry window in seconds (0 = single attempt)."},
            },
            "required": ["device_id"],
            "additionalProperties": False,
        },
        "handler": tool_adb_lock,
    },
    {
        "name": "hs_adb_unlock",
        "description": (
            "POST /v0/adb/{device_id}/unlock — release an Android device lease held by "
            "hs_adb_lock. Always call after a lock, even on error paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"device_id": _ADB_DEVICE_SCHEMA},
            "required": ["device_id"],
            "additionalProperties": False,
        },
        "handler": tool_adb_unlock,
    },
    {
        "name": "hs_adb_shell",
        "description": (
            "POST /v0/adb/{device_id}/shell — run an adb shell command on a locked "
            "Android device (raw command string as body -> {\"stdout\": ...}). "
            "LIVE-VERIFIED 2026-07-03. This is how Android devices are driven over "
            "REST: input tap/swipe/keyevent, am start, dumpsys, pm list packages."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": _ADB_DEVICE_SCHEMA,
                "command": {"type": "string", "description": "adb shell command, e.g. 'input swipe 400 1400 400 400 200'."},
            },
            "required": ["device_id", "command"],
            "additionalProperties": False,
        },
        "handler": tool_adb_shell,
    },
    {
        "name": "hs_start_capture",
        "description": (
            "POST /v0/sessions {session_type:capture, device_address, capture_video} — "
            "start a capture session on a LOCKED device. Returns {session_id}. "
            "LIVE-VERIFIED 2026-07-03. capture_video defaults true (screen-recording MP4)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_address": {"type": "string", "description": "Full device address {serial|udid}@proxy-host.headspin.io."},
                "capture_video": {"type": "boolean", "description": "Record the screen (default true)."},
                "nowait": {"type": "boolean", "description": "Return immediately; poll timestamps for readiness."},
            },
            "required": ["device_address"],
            "additionalProperties": False,
        },
        "handler": tool_start_capture,
    },
    {
        "name": "hs_stop_capture",
        "description": (
            "PATCH /v0/sessions/{session_id} {active:false} — stop a capture session. "
            "Success msg cites the uploaded MP4. Poll hs_session_timestamps for the "
            "capture-complete mark before downloading artifacts. LIVE-VERIFIED 2026-07-03."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": _SESSION_ID_SCHEMA},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_stop_capture,
    },
    {
        "name": "hs_list_sessions",
        "description": (
            "GET /v0/sessions — list capture sessions in the org, newest first. "
            "LIVE-VERIFIED. Returns {\"sessions\":[{session_id, device_id, device_address, "
            "session_type, state, start_time, error_code}], \"next_token\":...}. Each "
            "session_id feeds the waterfall / report / device-event tools below. "
            "include_all=true adds ended sessions (default false=live only)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_all": {"type": "boolean", "description": "Include ended sessions (default false = live only)."},
                "num_sessions": {"type": "integer", "description": "Max sessions per page (1-100, default 10)."},
                "next_token": {"type": "string", "description": "Pagination token from a prior response."},
            },
            "additionalProperties": False,
        },
        "handler": tool_list_sessions,
    },
    {
        "name": "hs_session_issues",
        "description": (
            "GET /v0/sessions/analysis/issues/{session_id} — the WATERFALL UI issue card "
            "data (Low Frame Rate, Domain Sharding, etc.): the core of a HeadSpin "
            "performance report. orient=column (default) or record."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": _SESSION_ID_SCHEMA,
                "orient": {"type": "string", "enum": ["column", "record"], "description": "Output shape (default column)."},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_session_issues,
    },
    {
        "name": "hs_session_timestamps",
        "description": (
            "GET /v0/sessions/{session_id}/timestamps — capture-started/-ended/-complete "
            "epoch marks. Poll this to know when a nowait capture is ready or done. "
            "404 = no timestamps yet / unknown session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": _SESSION_ID_SCHEMA},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_session_timestamps,
    },
    {
        "name": "hs_analysis_status",
        "description": (
            "GET /v0/sessions/analysis/status/{session_id} — whether report analyses are "
            "done. timeout=0 (default here) checks current state without blocking; "
            "optional track narrows to one analysis (e.g. video-quality-mos, page-load)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": _SESSION_ID_SCHEMA,
                "timeout": {"type": "integer", "description": "Seconds to wait for completion (0 = check now, default)."},
                "track": {"type": "string", "description": "Optional analysis key to track (e.g. page-load, video-quality-mos)."},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_analysis_status,
    },
    {
        "name": "hs_session_timeseries_info",
        "description": (
            "GET /v0/sessions/timeseries/{session_id}/info — the device time series "
            "available for this session (impact, memory_used, frame_rate, ...), each with "
            "name/category/units. 'What occurred on the device' as measurable signals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": _SESSION_ID_SCHEMA},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_session_timeseries_info,
    },
    {
        "name": "hs_session_timeseries_download",
        "description": (
            "GET /v0/sessions/timeseries/{session_id}/download?key=K — download one time "
            "series as CSV over the session timeline (key from hs_session_timeseries_info). "
            "Saved to disk; returns {saved_to, bytes}, not the CSV body."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": _SESSION_ID_SCHEMA,
                "key": {"type": "string", "description": "A time_series_key from hs_session_timeseries_info."},
                "save_path": {"type": "string", "description": "Optional destination path (defaults under HS_DOWNLOAD_DIR)."},
            },
            "required": ["session_id", "key"],
            "additionalProperties": False,
        },
        "handler": tool_session_timeseries_download,
    },
    {
        "name": "hs_session_video_metadata",
        "description": (
            "GET /v0/sessions/{session_id}/video/metadata — screen-recording dimensions, "
            "fps, duration, codec, and audio channels for the session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": _SESSION_ID_SCHEMA},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_session_video_metadata,
    },
    {
        "name": "hs_session_download",
        "description": (
            "GET /v0/sessions/{session_id}.{ext} — download a captured artifact to disk: "
            "har (NETWORK WATERFALL), mar, csv, device.log.gz (DEVICE EVENTS), appium.log.gz, "
            "mp4 (screen recording), pcap. Saved to disk; returns {saved_to, bytes, "
            "content_type}, never the bytes. har supports enhanced=true; mp4 supports fps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": _SESSION_ID_SCHEMA,
                "ext": {"type": "string", "description": "har | mar | csv | mp4 | pcap | device.log.gz | appium.log.gz | selenium.log.gz | jsconsole.log.gz | sslkeylog.txt"},
                "enhanced": {"type": "boolean", "description": "har only: include HTTP bodies (default false)."},
                "fps": {"type": "integer", "description": "mp4 only: resample to a constant frame rate."},
                "save_path": {"type": "string", "description": "Optional destination path (defaults under HS_DOWNLOAD_DIR)."},
            },
            "required": ["session_id", "ext"],
            "additionalProperties": False,
        },
        "handler": tool_session_download,
    },
    {
        "name": "hs_session_tls_exceptions",
        "description": (
            "GET /v0/sessions/{session_id}/tlsexceptions — {host: exception_count} for "
            "hosts whose TLS pinning broke network capture (a real waterfall-gap signal)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": _SESSION_ID_SCHEMA},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "handler": tool_session_tls_exceptions,
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
