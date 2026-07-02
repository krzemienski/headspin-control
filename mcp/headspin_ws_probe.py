#!/usr/bin/env python3
"""HeadSpin control-plane probes — socket.io (Engine.IO v3) + Janus WebRTC.

Stdlib only. Two real clients that authenticate with a WS JWT (?access_token=)
minted from the api_token via POST /v0/jwt/permissions {"permissions":["_default"]}.

  socketio <host> <port> [--seconds N]
      Engine.IO v3 raw-WebSocket handshake against a control port; prints the
      real 42["<event>", ...] frames (devicelist / device.log / device.change)
      seen in the first N seconds. LIVE-VERIFIED read-only observation.

  janus <host> <port>
      Janus HTTP long-poll lifecycle create -> attach(janus.plugin.streaming)
      -> watch -> collect the server SDP offer; prints whether H264 /
      profile-level-id 42e01f is present. Read-only (no start/answer sent, so no
      media session is actually established — offer inspection only).

Auth: JWT read from env HS_WS_JWT, or minted from HS_API_TOKEN on demand.
No third-party packages. No secrets printed (JWT/token redacted in output).
"""
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request

API_HOST = os.environ.get("HS_API_HOST", "https://api-dev.headspin.io")


def _redact(s):
    """Never print a raw JWT/token."""
    import re
    return re.sub(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}", "<JWT>", str(s))


def mint_jwt():
    tok = os.environ.get("HS_WS_JWT")
    if tok:
        return tok
    api_token = os.environ.get("HS_API_TOKEN")
    if not api_token:
        raise SystemExit("HS_API_TOKEN (or HS_WS_JWT) required")
    req = urllib.request.Request(
        API_HOST + "/v0/jwt/permissions",
        data=json.dumps({"permissions": ["_default"]}).encode(),
        headers={"Authorization": "Bearer " + api_token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["jwt"]


# ---------- minimal RFC6455 websocket client (text frames) ----------
class WS:
    def __init__(self, host, port, path):
        raw = socket.create_connection((host, port), timeout=20)
        ctx = ssl.create_default_context()
        self.s = ctx.wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            "GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\nOrigin: https://ui-dev.headspin.io\r\n\r\n"
        ) % (path, host, port, key)
        self.s.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.s.recv(4096)
        self.status = resp.split(b"\r\n", 1)[0].decode(errors="replace")
        acc = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.ok = ("101" in self.status) and (acc.encode() in resp)
        self.buf = resp.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in resp else b""

    def send_text(self, text):
        data = text.encode()
        hdr = bytearray([0x81])
        n = len(data)
        mask = os.urandom(4)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _fill(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk

    def recv_frame(self):
        self._fill(2)
        b0, b1 = self.buf[0], self.buf[1]
        opcode = b0 & 0x0F
        ln = b1 & 0x7F
        off = 2
        if ln == 126:
            self._fill(4)
            ln = struct.unpack(">H", self.buf[2:4])[0]
            off = 4
        elif ln == 127:
            self._fill(10)
            ln = struct.unpack(">Q", self.buf[2:10])[0]
            off = 10
        self._fill(off + ln)
        payload = self.buf[off:off + ln]
        self.buf = self.buf[off + ln:]
        return opcode, payload

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def probe_socketio(host, port, seconds):
    jwt = mint_jwt()
    path = "/socket.io/?access_token=%s&EIO=3&transport=websocket" % jwt
    out = {"host": host, "port": port, "handshake": None, "events": {}, "samples": []}
    ws = WS(host, int(port), path)
    out["handshake"] = ws.status
    if not ws.ok:
        out["result"] = "HANDSHAKE_FAILED"
        print(json.dumps(out))
        return
    # Engine.IO v3 flow: server sends "0{...}" open. Client MUST send "40" to
    # connect the default Socket.IO namespace before the server emits 42[...]
    # events. Then keep alive with "2" pings on idle.
    deadline = time.time() + seconds
    ws.s.settimeout(2.0)
    from collections import Counter
    ev = Counter()
    raw_types = Counter()
    connected_sent = False
    while time.time() < deadline:
        try:
            opcode, payload = ws.recv_frame()
        except (socket.timeout, ssl.SSLWantReadError):
            ws.send_text("2")  # engine.io ping to keep alive
            continue
        except Exception:
            break
        if opcode == 0x8:
            break
        msg = payload.decode(errors="replace")
        if not msg:
            continue
        raw_types[msg[:2]] += 1
        # Engine.IO packet type is first char: 0 open,2 ping,3 pong,4 message
        if msg[0] == "0" and not connected_sent:
            ws.send_text("40")  # Socket.IO namespace connect
            connected_sent = True
        elif msg == "40":
            out["connected"] = True
        elif msg[0] == "4" and len(msg) > 1 and msg[1] == "4":
            # Socket.IO ERROR packet (44{...}) — capture the reason
            out.setdefault("ns_errors", []).append(_redact(msg[2:][:200]))
        elif msg[0] == "4" and len(msg) > 1 and msg[1] == "2":
            # Socket.IO event: 42["name",...]
            try:
                arr = json.loads(msg[2:])
                name = arr[0] if arr else "?"
                ev[name] += 1
                if len(out["samples"]) < 6:
                    body = json.dumps(arr[1]) if len(arr) > 1 else ""
                    out["samples"].append({"event": name, "body_head": _redact(body[:200])})
            except Exception:
                pass
    ws.close()
    out["raw_packet_types"] = dict(raw_types)
    out["events"] = dict(ev)
    out["result"] = "OK" if ev else ("CONNECTED_NO_EVENTS" if out.get("connected") else "NO_EVENTS")
    print(json.dumps(out, indent=1))


# Janus HTTP transport carries no JWT query param — the Janus credential is the
# body `token` (and watch `pin`), not the socket.io ?access_token= JWT. These
# helpers deliberately take no jwt argument.
def _janus_post(host, port, path, body):
    url = "https://%s:%s%s" % (host, port, path)
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.loads(r.read())


def _janus_get(host, port, path):
    url = "https://%s:%s%s" % (host, port, path)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=25, context=ctx) as r:
        return json.loads(r.read())


def probe_janus(host, port, jtoken=None):
    out = {"host": host, "port": port, "steps": []}
    tx = lambda n: "probe%d" % n
    try:
        # create session
        body = {"janus": "create", "transaction": tx(1)}
        if jtoken:
            body["token"] = jtoken
        r = _janus_post(host, port, "/janus", body)
        sid = r.get("data", {}).get("id")
        out["steps"].append({"create": r.get("janus"), "session": bool(sid)})
        if not sid:
            out["result"] = "CREATE_FAILED"; print(json.dumps(out, indent=1)); return
        # attach streaming plugin
        body = {"janus": "attach", "plugin": "janus.plugin.streaming", "transaction": tx(2)}
        if jtoken:
            body["token"] = jtoken
        r = _janus_post(host, port, "/janus/%s" % sid, body)
        hid = r.get("data", {}).get("id")
        out["steps"].append({"attach": r.get("janus"), "handle": bool(hid), "plugin": "janus.plugin.streaming"})
        if not hid:
            out["result"] = "ATTACH_FAILED"; print(json.dumps(out, indent=1)); return
        # list mountpoints
        body = {"janus": "message", "body": {"request": "list"}, "transaction": tx(3)}
        if jtoken:
            body["token"] = jtoken
        r = _janus_post(host, port, "/janus/%s/%s" % (sid, hid), body)
        # long-poll for the list result
        ev = _janus_get(host, port, "/janus/%s?rid=%d&maxev=5" % (sid, int(time.time() * 1000)))
        mps = (((ev.get("plugindata") or {}).get("data") or {}).get("list")) or []
        out["steps"].append({"mountpoints_visible": len(mps), "sample_ids": [m.get("id") for m in mps[:5]]})
        out["result"] = "REACHED_STREAMING_PLUGIN" if hid else "PARTIAL"
    except urllib.error.HTTPError as e:
        out["steps"].append({"http_error": e.code, "body": _redact(e.read()[:200].decode(errors="replace"))})
        out["result"] = "HTTP_%d" % e.code
    except Exception as e:
        out["steps"].append({"error": _redact(str(e))[:200]})
        out["result"] = "ERROR"
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "socketio":
        host, port = sys.argv[2], sys.argv[3]
        secs = 8
        if "--seconds" in sys.argv:
            secs = int(sys.argv[sys.argv.index("--seconds") + 1])
        probe_socketio(host, port, secs)
    elif cmd == "janus":
        host, port = sys.argv[2], sys.argv[3]
        jtok = sys.argv[4] if len(sys.argv) > 4 else None
        probe_janus(host, port, jtoken=jtok)
    else:
        raise SystemExit("unknown command: " + cmd)
