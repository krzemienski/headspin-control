#!/usr/bin/env python3
"""Detect app-under-test UI/accessibility defects from an Appium uiautomator2 page_source.

This is the plugin's bug-surfacing analyzer: it judges the APPLICATION under test
(not the harness) using the a11y XML hierarchy Appium returns from
`driver.page_source`. Every predicate is package-scoped to the target app and
subtree-aware, so OS chrome (status/nav bar) and labelled containers are not
false-flagged.

Defect classes (ranked by reliability; see design notes):
  A3  unlabeled clickable control  — clickable node whose ENTIRE subtree has no
      text and no content-desc (TalkBack cannot announce it). Subtree-aware:
      a clickable row whose child carries the label is NOT flagged.
  A4  unlabeled clickable image    — clickable ImageView/ImageButton leaf with
      empty content-desc and no labelled child (icon-only control, no a11y name).
  A5  undersized touch target      — on-screen clickable node smaller than 48dp
      in either dimension (Material minimum). Gated by on-screen + non-zero-area.
  A1  crash/ANR dialog present     — a system "isn't responding"/"has stopped"
      dialog is on top of the target app.

Usage:
  a11y_defects.py <source.xml> --package <appPackage> [--density <float>]
                  [--session <id>] [--activity <name>] [--screenshot <path>]
                  [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

_ANR_RE = re.compile(
    r"isn'?t responding|not responding|has stopped|keeps stopping|close app",
    re.IGNORECASE,
)
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _bounds(node):
    m = _BOUNDS_RE.search(node.get("bounds", ""))
    if not m:
        return None
    x1, y1, x2, y2 = (int(g) for g in m.groups())
    return x1, y1, x2, y2


def _true(node, attr):
    return node.get(attr, "false") == "true"


def _labelled(node):
    """True if this node OR any descendant carries text/content-desc."""
    for n in node.iter():
        if (n.get("text") or "").strip() or (n.get("content-desc") or "").strip():
            return True
    return False


def _pkg(node):
    return node.get("package", "")


def _node_summary(node):
    return {
        "class": node.get("class"),
        "resource_id": node.get("resource-id") or None,
        "content_desc": node.get("content-desc") or "",
        "text": node.get("text") or "",
        "bounds": node.get("bounds"),
        "clickable": _true(node, "clickable"),
    }


def detect(source_xml: str, package: str, density: float, win_w: int, win_h: int):
    root = ET.fromstring(source_xml)
    findings = []

    # A1 — crash/ANR dialog (allowed cross-package: OS renders it for the app)
    for n in root.iter():
        blob = (n.get("text") or "") + " " + (n.get("content-desc") or "")
        if _ANR_RE.search(blob):
            findings.append({
                "predicate": "A1_crash_anr_dialog",
                "severity": "critical",
                "node": _node_summary(n),
            })
            break  # one dialog is enough

    min_px = 48 * density
    for n in root.iter():
        if not _true(n, "clickable"):
            continue
        if _pkg(n) != package:
            continue  # package scope: never flag OS chrome / other apps
        b = _bounds(n)
        cls = n.get("class", "")
        # Anonymous structural containers (no resource-id, no label, generic
        # *Layout class) are NOT real controls even when marked clickable — e.g.
        # edge-clipping list-row slivers. A real control has a resource-id OR a
        # content-desc OR is a known widget class. Both A3 and A5 gate on this to
        # avoid flagging layout scaffolding as an app defect.
        _CONTROL = ("Button", "ImageButton", "Switch", "CheckBox",
                    "ImageView", "RadioButton", "SeekBar")
        is_control = (
            bool(n.get("resource-id"))
            or bool((n.get("content-desc") or "").strip())
            or any(c in cls for c in _CONTROL)
        )
        # A3 — truly unlabeled clickable control (subtree-aware, real controls only)
        if is_control and not _labelled(n):
            findings.append({
                "predicate": "A3_unlabeled_clickable",
                "severity": "medium",
                "node": _node_summary(n),
            })
            # A4 — refine: leaf image control (stronger evidence)
            if ("ImageView" in cls or "ImageButton" in cls) and len(list(n)) == 0:
                findings[-1]["predicate"] = "A4_unlabeled_image_control"
                findings[-1]["severity"] = "high"
        # A5 — undersized touch target (real controls only, fully on-screen)
        if b and is_control:
            x1, y1, x2, y2 = b
            w, h = x2 - x1, y2 - y1
            # fully on-screen: not clipping any viewport edge
            fully_on = (x1 >= 0 and y1 >= 0 and x2 <= win_w and y2 <= win_h)
            if fully_on and w > 0 and h > 0 and (w < min_px or h < min_px):
                findings.append({
                    "predicate": "A5_undersized_touch_target",
                    "severity": "low",
                    "detail": f"{w}x{h}px < {min_px:.0f}px min (48dp @ density {density})",
                    "node": _node_summary(n),
                })
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--package", required=True)
    ap.add_argument("--density", type=float, default=2.75)  # Pixel 6 ~ xxhdpi
    ap.add_argument("--win-w", type=int, default=1080)
    ap.add_argument("--win-h", type=int, default=2400)
    ap.add_argument("--session", default=None)
    ap.add_argument("--activity", default=None)
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with open(a.source) as f:
        xml = f.read()
    findings = detect(xml, a.package, a.density, a.win_w, a.win_h)

    report = {
        "session_id": a.session,
        "target_app_package": a.package,
        "activity": a.activity,
        "source_path": a.source,
        "screenshot_path": a.screenshot,
        "defect_count": len(findings),
        "defects": findings,
        "verdict": "DEFECTS_FOUND" if findings else "CLEAN",
    }
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"[{report['verdict']}] {len(findings)} defect(s) in {a.package}")
        for d in findings:
            n = d["node"]
            print(f"  {d['severity'].upper():8} {d['predicate']:26} "
                  f"class={n['class']} id={n['resource_id']} bounds={n['bounds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
