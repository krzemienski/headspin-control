#!/usr/bin/env python3
"""Bounded BFS app-exploration + bug discovery for a connected HeadSpin device.

Drives an EXISTING Appium driver (open one via headspin-connection-manager). At
each screen it captures page source + screenshot, inventories interactive
elements, taps the next unvisited one, and watches for anomalies. On an anomaly
it writes an evidence bundle that headspin-bug-report consumes. The whole run is
wrapped in a capture session so a video exists.

Token is read from the environment ONLY (CLAUDE_PLUGIN_OPTION_API_TOKEN, with
HS_API_TOKEN / HS_API_KEY as fallbacks) and is never written into any evidence
file. REST calls use stdlib urllib.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "api-dev.headspin.io"
ERROR_KEYWORDS = (
    "error", "exception", "crash", "not responding", "something went wrong",
    "unfortunately", "force close", "anr", "fatal",
)


def _token() -> str:
    tok = (
        os.environ.get("CLAUDE_PLUGIN_OPTION_API_TOKEN")
        or os.environ.get("HS_API_TOKEN")
        or os.environ.get("HS_API_KEY")
    )
    if not tok:
        raise SystemExit("CLAUDE_PLUGIN_OPTION_API_TOKEN not set (run /headspin:login).")
    return tok


def _default_base() -> str:
    # Plugin config is a full URL (https://api-dev.headspin.io); strip scheme
    # since _Rest re-adds https://. Fall back to HS_API_BASE, then the constant.
    host = os.environ.get("CLAUDE_PLUGIN_OPTION_API_HOST") or os.environ.get("HS_API_BASE")
    if host:
        return host.split("://", 1)[-1].rstrip("/")
    return DEFAULT_BASE


class _Rest:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self._token = _token()

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"https://{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            return {"_http_error": e.code, "_detail": e.read().decode(errors="replace")[:200]}
        return json.loads(raw) if raw.strip() else {}


def _hash(text: str) -> str:
    # Normalize volatile attrs (coords/indices) so the same screen dedups stably.
    norm = re.sub(r'(x|y|index|bounds|value)="[^"]*"', "", text or "")
    return hashlib.sha1(norm.encode()).hexdigest()


class AppExplorer:
    def __init__(self, driver, device_address: str, device_id: str,
                 out_dir: str = "./headspin-exploration", base: str | None = None,
                 app_package: str | None = None) -> None:
        self.driver = driver
        self.device_address = device_address
        self.device_id = device_id
        self.app_package = app_package  # app under test; None disables foreground check
        self.base = base or _default_base()
        self.rest = _Rest(self.base)
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = os.path.join(out_dir, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)
        self.action_log: list[dict] = []
        self.visited: set[str] = set()
        self.anomalies: list[str] = []
        self.session_id: str | None = None
        self._anomaly_n = 0

    # ---- capture session wrap -----------------------------------------
    def _start_session(self) -> None:
        r = self.rest.call("POST", "/v0/sessions",
                           {"session_type": "capture", "device_address": self.device_address})
        self.session_id = r.get("session_id")

    def _stop_session(self) -> None:
        if self.session_id:
            self.rest.call("PATCH", f"/v0/sessions/{self.session_id}", {"active": False})

    # ---- primitives ----------------------------------------------------
    def _ocr(self) -> str:
        r = self.rest.call("POST", f"/v0/video/{self.device_id}/ocr")
        if "_http_error" in r:
            return ""
        return r.get("text") or r.get("ocr") or json.dumps(r)

    def _log_tail(self) -> str:
        # iOS syslog; Android callers can swap to logcat. Best-effort only.
        r = self.rest.call("GET", f"/v0/idevice/{self.device_id}/syslog")
        return r.get("syslog", "") if isinstance(r, dict) else str(r)

    @staticmethod
    def _inventory(page_source: str) -> list:
        # Placeholder inventory: real callers use driver.find_elements by class.
        # Kept dependency-free here; explore() below uses the live driver.
        return []

    # ---- anomaly detection --------------------------------------------
    def _detect(self, page_source: str, prev_hash: str | None, cur_hash: str) -> str | None:
        low = (page_source or "").lower()
        if any(k in low for k in ERROR_KEYWORDS):
            return "error_text_page_source"
        if self.app_package:
            try:
                cur_pkg = getattr(self.driver, "current_package", None)
                if cur_pkg and cur_pkg != self.app_package:
                    return "app_not_foreground"
            except Exception:  # noqa: BLE001 — package query failed; not itself an anomaly
                pass
        ocr = self._ocr().lower()
        if any(k in ocr for k in ERROR_KEYWORDS):
            return "error_text_ocr"
        # App-UI/accessibility defect analysis on the live a11y tree. This is the
        # bug-in-the-app-under-test path: package-scoped, subtree-aware predicates
        # over driver.page_source (see a11y_defects.py). Reported as an anomaly so
        # _capture_bundle saves the offending screen for the bug report.
        a11y = self._a11y_defects(page_source)
        if a11y:
            self.a11y_findings = a11y  # surfaced into the evidence bundle
            return "a11y_defect:" + a11y[0]["predicate"]
        if prev_hash is not None and prev_hash == cur_hash:
            return "stuck_screen"
        return None

    def _a11y_defects(self, page_source: str) -> list:
        """Run the package-scoped a11y defect predicates on the current a11y tree."""
        try:
            import a11y_defects
        except ImportError:
            import os as _os
            import sys as _sys
            _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            import a11y_defects
        if not (self.app_package and page_source):
            return []
        density = getattr(self, "density", 2.5688)
        wr = getattr(self, "window_rect", None) or {}
        return a11y_defects.detect(
            page_source, self.app_package, density,
            wr.get("width", 1080), wr.get("height", 2240))

    def _capture_bundle(self, signal: str, page_source: str) -> str:
        self._anomaly_n += 1
        d = os.path.join(self.run_dir, f"anomaly-{self._anomaly_n}")
        os.makedirs(d, exist_ok=True)
        try:
            with open(os.path.join(d, "screenshot.png"), "wb") as f:
                f.write(self.driver.get_screenshot_as_png())
        except Exception:  # noqa: BLE001
            pass
        with open(os.path.join(d, "page_source.xml"), "w") as f:
            f.write(page_source or "")
        with open(os.path.join(d, "ocr.txt"), "w") as f:
            f.write(self._ocr())
        with open(os.path.join(d, "log_tail.txt"), "w") as f:
            f.write(self._log_tail()[-8000:])
        with open(os.path.join(d, "action_log.json"), "w") as f:
            json.dump(self.action_log, f, indent=2)
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump({
                "timestamp": time.time(),
                "device_address": self.device_address,
                "device_id": self.device_id,
                "session_id": self.session_id,
                "session_url": f"https://ui.headspin.io/sessions/{self.session_id}" if self.session_id else None,
                "signal": signal,
            }, f, indent=2)
        self.anomalies.append(d)
        return d

    # ---- main loop -----------------------------------------------------
    def run(self, max_steps: int = 200, max_depth: int = 25) -> dict:
        self._start_session()
        steps = 0
        prev_hash = None
        try:
            queue = [0]  # BFS by depth level; screens discovered via live driver
            depth = 0
            while queue and steps < max_steps and depth < max_depth:
                depth = queue.pop(0)
                try:
                    page_source = self.driver.page_source
                except Exception as e:  # noqa: BLE001 — driver death = crash anomaly
                    self.action_log.append({"step": steps, "event": "driver_exception", "detail": str(e)[:200]})
                    self._capture_bundle("crash_driver_death", "")
                    break
                cur_hash = _hash(page_source)
                # Anomaly check BEFORE visited-dedup: a frozen screen re-hashes
                # identically, so the stuck_screen compare must see it first.
                signal = self._detect(page_source, prev_hash, cur_hash)
                if signal:
                    self._capture_bundle(signal, page_source)
                    prev_hash = cur_hash
                    continue
                if cur_hash in self.visited:
                    continue
                self.visited.add(cur_hash)

                # Inventory + act via the live driver (Appium clients only).
                try:
                    from appium.webdriver.common.appiumby import AppiumBy
                    els = self.driver.find_elements(AppiumBy.XPATH,
                        "//*[@clickable='true' or @enabled='true' or self::XCUIElementTypeButton]")
                except Exception:  # noqa: BLE001
                    els = []
                acted = False
                for el in els:
                    try:
                        el.click()
                        acted = True
                        steps += 1
                        self.action_log.append({"step": steps, "action": "click",
                                                "target": (el.get_attribute("name") or el.tag_name)})
                        queue.append(depth + 1)
                        time.sleep(0.6)
                        break
                    except Exception:  # noqa: BLE001 — element went stale; try next
                        continue
                if not acted:
                    steps += 1
                prev_hash = cur_hash
        finally:
            self._stop_session()

        summary = {
            "run_id": self.run_id, "run_dir": self.run_dir,
            "steps": steps, "screens_visited": len(self.visited),
            "anomalies": self.anomalies, "session_id": self.session_id,
        }
        with open(os.path.join(self.run_dir, "run_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)
        return summary


_USAGE = """\
headspin-explore-bugs: AppExplorer drives an ALREADY-OPEN control session; it does
not open one itself. In this plugin the control session is established by the
headspin-connect-ios / headspin-connect-roku + headspin-connection-manager skills,
so drive AppExplorer programmatically with a live driver object:

    from explore import AppExplorer
    explorer = AppExplorer(driver, device_address, device_id,
                           out_dir="./headspin-exploration")
    run = explorer.run(max_steps=150, max_depth=20)   # starts+stops capture session
    print(run["run_dir"])   # hand this to headspin-bug-report

Prerequisites (see SKILL.md): /headspin:login, headspin-session-manager lock,
headspin-connection-manager socket. Token is read from
CLAUDE_PLUGIN_OPTION_API_TOKEN (env-only, never on disk).
"""


def _main(argv: list[str]) -> int:
    sys.stderr.write(_USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
