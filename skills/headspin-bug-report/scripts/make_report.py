#!/usr/bin/env python3
"""Turn a HeadSpin exploration run directory into standardized bug reports.

Reads a run dir produced by headspin-app-explorer (containing anomaly-*/ bundles
with meta.json + action_log.json + evidence files) and emits, per anomaly, a
BUG-{n}.md (from assets/report-template.md) and a BUG-{n}.json sidecar, plus a
bugs-index.json.

Offline: needs NO API token. Any token or token-in-path driver_url found in the
evidence is REDACTED before it reaches a report — reports are shareable artifacts.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

_TOKEN_IN_PATH = re.compile(r"/v0/[^/\s]+/wd/hub")
# Redact obvious 24-64 char hex/opaque token blobs conservatively.
_TOKEN_BLOB = re.compile(r"\b[A-Fa-f0-9]{24,64}\b")

_SEVERITY = {
    "crash_driver_death": "critical",
    "error_text_ocr": "high",
    "error_text_page_source": "high",
    "app_not_foreground": "high",
    "stuck_screen": "medium",
}
_TITLE = {
    "crash_driver_death": "App or driver crashed during exploration",
    "error_text_ocr": "Error text surfaced on screen (OCR)",
    "error_text_page_source": "Error text in UI hierarchy",
    "app_not_foreground": "App left foreground unexpectedly",
    "stuck_screen": "Screen frozen / dead-end after action",
}
_EXPECTED = "App remains responsive and on the expected screen after the action."
_ACTUAL = {
    "crash_driver_death": "The Appium session died — app or driver crashed.",
    "error_text_ocr": "An error message was visible on the device screen.",
    "error_text_page_source": "The UI hierarchy contained error/exception text.",
    "app_not_foreground": "The app under test was no longer in the foreground.",
    "stuck_screen": "The screen did not change after the action (frozen / dead-end).",
}


def redact(text: str) -> str:
    if not text:
        return text
    text = _TOKEN_IN_PATH.sub("/v0/***/wd/hub", text)
    return _TOKEN_BLOB.sub("***", text)


def _load_template() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "report-template.md")
    with open(path) as f:
        return f.read()


def _repro_from_actions(actions: list) -> list[str]:
    steps = []
    for a in actions:
        if a.get("action"):
            steps.append(f"{a.get('action')} → {a.get('target', '?')}")
        elif a.get("event"):
            steps.append(f"[{a.get('event')}] {a.get('detail', '')}")
    return steps or ["(no recorded actions before the anomaly — occurred on entry)"]


def build_report(anomaly_dir: str, idx: int, app_id: str, api: str) -> dict:
    meta = json.load(open(os.path.join(anomaly_dir, "meta.json")))
    actions_path = os.path.join(anomaly_dir, "action_log.json")
    actions = json.load(open(actions_path)) if os.path.exists(actions_path) else []
    signal = meta.get("signal", "unknown")
    sid = meta.get("session_id")
    device_address = meta.get("device_address", "")
    report = {
        "id": f"BUG-{idx}",
        "title": _TITLE.get(signal, f"Anomaly: {signal}"),
        "severity": _SEVERITY.get(signal, "medium"),
        "device": {
            "device_address": device_address,
            "device_type": meta.get("device_type", ""),
            "os_version": meta.get("os_version", ""),
        },
        "app_id": app_id or "(unknown)",
        "repro_steps": _repro_from_actions(actions),
        "expected": _EXPECTED,
        "actual": _ACTUAL.get(signal, signal),
        "evidence": {
            "screenshot": os.path.join(anomaly_dir, "screenshot.png"),
            "page_source": os.path.join(anomaly_dir, "page_source.xml"),
            "ocr": os.path.join(anomaly_dir, "ocr.txt"),
            "log_tail": os.path.join(anomaly_dir, "log_tail.txt"),
        },
        "session_url": meta.get("session_url") or (f"https://ui.headspin.io/sessions/{sid}" if sid else None),
        "video_url": f"https://{api}/v0/sessions/{sid}.mp4" if sid else None,
        "environment": {
            "timestamp": meta.get("timestamp"),
            "api_base": api,
            "run_id": os.path.basename(os.path.dirname(anomaly_dir)),
            "signal": signal,
        },
    }
    return report


def render_md(template: str, r: dict) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(r["repro_steps"], 1))
    filled = template.format(
        id=r["id"], title=r["title"], severity=r["severity"],
        device_address=r["device"]["device_address"], device_type=r["device"]["device_type"],
        os_version=r["device"]["os_version"] or "?", app_id=r["app_id"],
        session_url=r["session_url"] or "(no session)", video_url=r["video_url"] or "(no video)",
        timestamp=r["environment"]["timestamp"], repro_steps=steps,
        expected=r["expected"], actual=r["actual"],
        evidence_screenshot=r["evidence"]["screenshot"], evidence_page_source=r["evidence"]["page_source"],
        evidence_ocr=r["evidence"]["ocr"], evidence_log_tail=r["evidence"]["log_tail"],
        api_base=r["environment"]["api_base"], run_id=r["environment"]["run_id"],
        signal=r["environment"]["signal"],
    )
    return redact(filled)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="HeadSpin exploration run → bug reports.")
    p.add_argument("run_dir", help="exploration run directory (contains anomaly-*/)")
    p.add_argument("--app-id", default="", help="bundleId / appPackage under test")
    p.add_argument("--api", default=(
        (os.environ.get("CLAUDE_PLUGIN_OPTION_API_HOST") or os.environ.get("HS_API_BASE")
         or "api-dev.headspin.io").split("://", 1)[-1].rstrip("/")))
    args = p.parse_args(argv[1:])

    anomalies = sorted(glob.glob(os.path.join(args.run_dir, "anomaly-*")))
    if not anomalies:
        print(f"No anomaly-*/ dirs in {args.run_dir}", file=sys.stderr)
        return 1

    template = _load_template()
    index = []
    for i, adir in enumerate(anomalies, 1):
        r = build_report(adir, i, args.app_id, args.api)
        md = render_md(template, r)
        r_redacted = json.loads(redact(json.dumps(r)))
        md_path = os.path.join(args.run_dir, f"BUG-{i}.md")
        json_path = os.path.join(args.run_dir, f"BUG-{i}.json")
        with open(md_path, "w") as f:
            f.write(md)
        with open(json_path, "w") as f:
            json.dump(r_redacted, f, indent=2)
        index.append({"id": r["id"], "severity": r["severity"], "md": md_path, "json": json_path})

    with open(os.path.join(args.run_dir, "bugs-index.json"), "w") as f:
        json.dump(index, f, indent=2)
    print(json.dumps(index, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
