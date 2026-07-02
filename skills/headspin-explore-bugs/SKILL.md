---
name: headspin-explore-bugs
description: Systematically explore an app on a connected HeadSpin device to discover bugs and crashes. Use for "explore app for bugs", "crawl the app on headspin", "find crashes", "automated exploratory QA on a device", "monkey-test this app", or "walk every screen and flag anomalies". Runs a bounded BFS crawl over the live control session — capture page source + screenshot, inventory interactive elements, act, detect anomalies (crash/session death, error text, stuck screen, app-not-foreground), and write a timestamped evidence bundle per anomaly. Wraps the run in a HeadSpin capture session so a video exists. Feeds headspin-bug-report.
allowed-tools: Read, Bash, Grep
---

# headspin-explore-bugs

## When to use

- User runs `/headspin:explore` or asks to "crawl the app for bugs / crashes".
- A device is already connected and you want automated exploratory QA with evidence.
- A test needs to walk every reachable screen and flag anomalies for triage.

## Scope

- **In scope:** the BFS crawl loop, anomaly detection, evidence-bundle capture,
  wrapping the run in a capture session so a video exists, bounded exploration
  (max steps, max depth, visited-screen dedup).
- **Out of scope:** logging in (`headspin-login`), locking the device
  (`headspin-session-manager`), opening the control transport
  (`headspin-connection-manager`), the tap/press/screenshot primitives
  (`headspin-control-ios` for the iOS `CONTROL_TOUCH_PATHS` channel; the
  Android socket.io `input.*` primitives), and writing the final report
  (`headspin-bug-report`).
- **Roku is doc-only / not HAR-verified in this environment** — no Roku device
  appears in any captured `devicelist`, so the crawl targets Android and iOS.

## Prerequisites

1. `headspin-login` has run; `$CLAUDE_PLUGIN_OPTION_API_HOST` and
   `$CLAUDE_PLUGIN_OPTION_API_TOKEN` are set (token in the OS keychain).
2. `headspin-session-manager` holds a live device lock (capture sessions 403 with
   "Device must be locked before capture." otherwise).
3. `headspin-connection-manager` has an open control socket; the device's
   `device_address` (`<device_id>@<hostname>`) is in
   `/tmp/headspin-control/selected-device.txt` and `device_id` is known.

## Security policy

- Token from the plugin config ONLY — read inline as
  `$CLAUDE_PLUGIN_OPTION_API_TOKEN` (keychain-backed via `sensitive: true`).
  Never hardcode, print, or write it into any evidence file. REST calls send it
  as a `Authorization: Bearer` header only.
- Evidence bundles carry screenshots and page source of the app under test. They
  must NOT contain the API token or any token-in-path `driver_url`
  (`/v0/{TOKEN}/wd/hub`) — redact before writing.

## Exploration loop (BFS)

```
headspin-login → headspin-session-manager (lock) → headspin-connection-manager (socket)
start capture session (POST /v0/sessions {session_type:"capture", device_address}) ─┐
                                                                                     │ video of the whole run
  queue = [ current screen ]                                                         ▼
  while queue and steps < max_steps and depth < max_depth:
     page_source = control dump (iOS: headspin-control-ios `dump`; Android: Appium/uiautomator2 page source)
     screen_hash = sha1(normalized page_source)     # dedup key — makes the crawl terminate
     if screen_hash in visited: continue
     visited.add(screen_hash)
     screenshot  = control screenshot
     if detect_anomaly(...): capture_evidence_bundle(); continue
     act on next unvisited interactive element (headspin-control-*), enqueue new screen
stop capture session (PATCH /v0/sessions/{id} {active:false}) → video at /v0/sessions/{id}.mp4
```

## Anomaly detection (four signals)

| Signal | How detected | Meaning |
|--------|--------------|---------|
| **Crash / session death** | control command raises / session invalid | app or session died |
| **Error text on screen** | error keywords in page source OR `GET /v0/video/{device_id}/ocr` | error dialog / exception surfaced |
| **Stuck screen** | N consecutive identical page-source hashes after an action | frozen / dead-end UI |
| **App not foreground** | current package/bundle ≠ app under test | app was backgrounded / kicked out |

Error keywords (case-insensitive): `error`, `exception`, `crash`, `not responding`,
`something went wrong`, `unfortunately`, `force close`, `anr`, `fatal`.

The OCR endpoint (`GET /v0/video/{device_id}/ocr`) reads the LIVE screen text
left-to-right, top-to-bottom — useful when error text is rendered as an image or
a native alert that never appears in the control page source.

## Evidence bundle (per anomaly)

Written to `./headspin-exploration/{run-id}/anomaly-{n}/`:

```
screenshot.png    # control screenshot at the moment of the anomaly
page_source.xml   # UI hierarchy dump
ocr.txt           # GET /v0/video/{device_id}/ocr  (live-screen text)
log_tail.txt      # syslog (iOS) / logcat (Android) tail
action_log.json   # verbatim ordered steps that led here (repro trail)
meta.json         # timestamp, device_address, device_id, session_id, signal, screen_hash
```

`meta.json.session_id` links to the HeadSpin session video:
`https://ui.headspin.io/sessions/{session_id}` and `/v0/sessions/{session_id}.mp4`.

## Bounds (non-negotiable)

- `max_steps` (default 200) — total actions before the crawl stops.
- `max_depth` (default 25) — BFS depth cap so the crawl does not wander forever.
- **Visited-screen dedup** by normalized page-source SHA1 — never re-explore a
  screen already seen. This is what makes the crawl terminate.
- One capture session for the whole run; stop it in a `finally` block.

## Quick start

`AppExplorer` drives an **already-open** control session (login + lock + socket
established by the skills above); it does not open one itself. Drive it
programmatically with the live driver:

```python
import sys
sys.path.insert(0, f"{CLAUDE_PLUGIN_ROOT}/skills/headspin-explore-bugs/scripts")
from explore import AppExplorer

explorer = AppExplorer(driver, device_address, device_id,
                       out_dir="./headspin-exploration")
run = explorer.run(max_steps=150, max_depth=20)   # starts+stops the capture session
print(run["run_dir"])   # hand this to headspin-bug-report
```

`device_address` is `<device_id>@<hostname>` from
`/tmp/headspin-control/selected-device.txt`. Running `explore.py` directly prints
this usage and exits — it has no standalone auto-connect harness.

## Evidence

- OCR endpoint (live-screen text): `plans/260702-headspin-skills/SYNTHESIS.md` §8
  (`GET /v0/video/{device_id}/ocr`) + `headspin-docs/api-reference/`.
- Capture-session lifecycle (lock → POST /v0/sessions → timestamps → PATCH
  active:false → `.mp4`): `plans/260702-headspin-skills/SYNTHESIS.md` §9.
- Websocket control surface the crawl drives:
  `headspin-docs/ui-dev.headspin.io.har:177`.

## Related skills

- `headspin-login` — token validation if OCR/session calls return 401/403 (call FIRST).
- `headspin-session-manager` — locks the device; a capture session requires the lock.
- `headspin-connection-manager` — opens the platform-correct control transport this skill drives (Android socket.io `input.*`, iOS `:5002` `CONTROL_TOUCH_PATHS`).
- `headspin-control-ios` — the iOS tap/press/dump/screenshot primitives. (Roku control is doc-only, not exercised in this environment.)
- `headspin-bug-report` — turns this skill's evidence bundles into filed bugs.

## Resources

- `scripts/explore.py` — bounded BFS loop, anomaly detection, capture-session
  wrapping, and evidence-bundle writing. Stdlib REST; token read from
  `$CLAUDE_PLUGIN_OPTION_API_TOKEN` (env-only, never on disk).
