# BUG-1: Capture recorder wired to wrong device — MP4 records a different device's screen

- **Severity:** high
- **Defect class:** farm infrastructure (recorder/screen-rig assignment), not app or API
- **Environment:** api-dev.headspin.io / ui-dev.headspin.io (org "YouTube Benchmarking")
- **Detected:** 2026-07-05 (repro 2); first observed 2026-07-03 (repro 1)
- **Reproductions:** 2 independent devices, both on the `dev-ca-tor-0` Toronto proxy cluster

## Summary

`POST /v0/sessions` capture sessions started against a locked Android device upload an
MP4 whose frames show a **different physical device's screen**. The adb control plane
targets the correct device (shell commands verifiably execute on the locked serial),
but the video recorder rig assigned to that serial is cross-wired to another device's
screen. All downstream video-based analyses (issue cards, video time series,
video_quality_mos) silently run against the wrong screen.

## Reproduction 2 — R38N70234FA records an iPhone (2026-07-05)

- **Device driven:** `R38N70234FA@dev-ca-tor-0-proxy-2-lin.headspin.io` (Samsung SM-G973W / Galaxy S10, Android 12)
- **Session:** `e8024cb0-788e-11f1-8491-da3445a29211`
- **Session UI:** https://ui-dev.headspin.io/sessions/e8024cb0-788e-11f1-8491-da3445a29211
- **Video:** https://api-dev.headspin.io/v0/sessions/e8024cb0-788e-11f1-8491-da3445a29211.mp4

Steps (all via REST, `Authorization: Bearer` redacted):
1. `POST /v0/adb/R38N70234FA/lock` → `{"status": 0, "... locked."}`
2. `POST /v0/sessions` `{session_type: capture, device_address: R38N70234FA@..., capture_video: true}` → session active
3. `POST /v0/adb/R38N70234FA/shell` `getprop ro.product.model` → **`SM-G973W`** (adb targeting CORRECT)
4. `POST /v0/adb/R38N70234FA/shell` — wake, open `https://www.youtube.com`, swipes; `dumpsys window` shows SBrowser foreground on the Samsung
5. `PATCH /v0/sessions/{sid}` `{active: false}` → "Video uploaded" (6,899,682 bytes, 512×1184 h264, 80.1 s)
6. Extract frames (`ffmpeg select=eq(n,200|900|1500)`)

**Expected:** frames show the Galaxy S10 running the browser that was driven.

**Actual:** frames show an **iPhone home screen** (iOS 14 springboard). Attribution is
conclusive: the visible app set — Tether, Tether2, masterhand ×2, WebDriverAgentRunner,
"iDevice Test APP" — exactly matches the `installer/list` inventory of iPhone 11
`00008030-001174DE2260402E@dev-ca-tor-0-proxy-3-mac.headspin.io`, and the on-screen
clock (12:31) matches that device's America/Toronto timezone. Frame evidence:
`session-e8024cb0-frame900.jpg`.

Corroborating platform data from the same session: Waterfall issue card returned
"Audio Too Quiet −30.8 LUFS" and 16 video/network time series — all computed from the
wrong device's screen.

## Reproduction 1 — R3CR40B0M9L records a Roku screensaver (2026-07-03)

- **Device driven:** `R3CR40B0M9L@dev-ca-tor-0-proxy-1-lin.headspin.io` (Samsung SM-G991U / Galaxy S21, Android 14)
- **Example session:** `54095810-76b2-11f1-9519-da3445a29211` (3 sessions affected)
- **Video:** https://api-dev.headspin.io/v0/sessions/54095810-76b2-11f1-9519-da3445a29211.mp4

Same lifecycle; MP4 frames show the **Roku City screensaver**, not the phone. The
phone's own recordings fingerprint at ≈752×1664 portrait; the delivered video shows
TV-aspect screensaver content across all three sessions on this serial.

## Impact

- Any customer capture on an affected serial produces a recording of the wrong device
  with no error, warning, or mismatched status — sessions end `state: ended, error_code: null`.
- Video-derived analyses (issue cards, blurriness/brightness/screen_change series,
  video MOS) are silently invalid for those sessions.
- Detection currently requires the customer to frame-fingerprint every MP4 manually.

## Suggested triage

- Audit recorder→device rig assignments on `dev-ca-tor-0` proxies 1 and 2 (both
  confirmed cases sit on this cluster).
- Consider a platform-side sanity check: compare recorder frame dimensions/content
  against the device's expected display fingerprint at capture start.

## Evidence bundle

- `VALIDATION-260705.md` — full 20-tool validation run containing repro 2 (public:
  https://github.com/krzemienski/headspin-control/blob/main/docs/evidence/VALIDATION-260705.md)
- `session-e8024cb0-frame900.jpg` — extracted frame showing the iPhone springboard
  (public: https://github.com/krzemienski/headspin-control/blob/main/docs/evidence/session-e8024cb0-frame900.jpg)
- Sessions remain retrievable via `GET /v0/sessions/{sid}.mp4` for independent verification.
