---
name: headspin-capture
description: Run a full HeadSpin capture session end-to-end on an Android/Cast/FireTV device — lock, start video capture, drive the app via ADB-over-REST (launch, tap, swipe), stop, and poll to capture-complete. LIVE-VALIDATED 2026-07-03 (two parallel YouTube sessions on real Samsung devices, MP4 + report retrieved). Uses MCP tools hs_adb_lock, hs_start_capture, hs_adb_shell, hs_stop_capture, hs_session_timestamps, hs_adb_unlock. Invoke when the user wants to record a device session, capture a screen recording with a performance report, run an app-exploration capture, or produce a Waterfall session on a real device.
allowed-tools: [Read, Bash, Grep]
---

# headspin-capture

Full capture-session lifecycle on Android/Cast/FireTV over Bearer REST — no websocket needed.
The result is a real HeadSpin session with screen-recording MP4, network waterfall (HAR),
issue-card report, and device time series.

> LIVE-VALIDATED 2026-07-03: two parallel ~4.8-min YouTube captures on SM-G981U + SM-G991U
> (`e2e-evidence/headspin-forge-260703/session-validation/`), both yielding playable h264 MP4s
> and completed analyses.

## Lifecycle (order is mandatory)

```
hs_adb_lock → hs_start_capture → hs_adb_shell (drive) → hs_stop_capture
            → hs_session_timestamps (poll capture-complete) → hs_adb_unlock
```

### 1. Lock the device

```
hs_adb_lock { "device_id": "RFCN80FV2TA", "timeout": 30 }
```

`{"status":0,...}` = locked. `{"status":1,"message":"Did not lock."}` = held by someone else —
pick another device from `hs_list_devices` (status 3 = online).

### 2. Start capture (video on)

```
hs_start_capture { "device_address": "RFCN80FV2TA@dev-ca-tor-0-proxy-20-lin.headspin.io",
                   "capture_video": true }
```

Returns `{"session_id": ...}`. A 500 "Error starting session." usually means the device just
ended another capture — wait ~30 s and retry, or use a different device.

### 3. Drive the app via adb shell

```
hs_adb_shell { "device_id": "RFCN80FV2TA", "command": "input keyevent KEYCODE_WAKEUP" }
hs_adb_shell { "device_id": "RFCN80FV2TA",
  "command": "am start -a android.intent.action.VIEW -d https://www.youtube.com/shorts -n com.google.android.youtube/.UrlActivity" }
hs_adb_shell { "device_id": "RFCN80FV2TA", "command": "input swipe 400 1400 400 400 200" }
```

Prove foreground app with
`dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'` — capture the stdout in evidence.
Each swipe advances one Short; ~1 interaction / 10 s keeps the session "active".

### 4. Stop and wait for complete

```
hs_stop_capture { "session_id": "<sid>" }        # success msg cites the uploaded MP4
hs_session_timestamps { "session_id": "<sid>" }  # poll until capture-complete appears
```

### 5. ALWAYS unlock

```
hs_adb_unlock { "device_id": "RFCN80FV2TA" }
```

Run this on every exit path, including failures.

## After capture

- Report + time series: `headspin-reports` skill (`hs_analysis_status` with `timeout` to wait,
  then `hs_session_issues`, `hs_session_timeseries_info`).
- Artifacts (MP4 / HAR / device.log): `headspin-waterfall` skill (`hs_session_download`).
- Session duration check: `hs_session_timestamps` (`capture-ended − capture-started`) and
  `hs_session_video_metadata` (`video_duration_ms`).

## Pitfalls

- Locking is a PREREQUISITE for `hs_start_capture` — an unlocked device 500s.
- iOS devices use `hs_lock_device`/`hs_unlock_device` (idevice routes) instead of the adb pair;
  driving iOS needs Appium (`headspin-control-ios`), not `hs_adb_shell`.
- `video/metadata` 404s until video processing finishes (~1 min after capture-complete);
  the analysis pipeline (`hs_analysis_status`) can take several minutes more.
- An MP4 downloaded too early can be a PARTIAL upload: the container header may already
  claim the full duration while only a few hundred frames are present. Verify with
  `ffprobe -count_packets` (expect ≈ duration × fps) and re-download a few minutes later
  if the packet count is short.
- Parallel captures on DIFFERENT devices are fine; never run two captures on one device.
- **Feed-mismatch trap (found live 2026-07-03):** a device's video recorder can be wired to
  the WRONG screen farm-side — R3CR40B0M9L (an SM-G991U) records the Roku City screensaver
  while its adb shell drives a real phone. `dumpsys` proves control, never recording content.
  ALWAYS fingerprint the MP4 (`ffprobe -show_entries stream=width,height` — phone ≈ 752x1664
  portrait) and view extracted frames before declaring a capture valid.
