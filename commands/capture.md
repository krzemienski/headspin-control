---
description: Run a full HeadSpin capture session (lock → record → drive app → stop → report-ready) on a real Android/Cast/FireTV device
argument-hint: <device-serial-or-address> [app] [duration-minutes]
allowed-tools: ["Read", "Bash", "Grep", "Skill", "mcp__plugin_headspin-control_headspin__*"]
---

# /headspin:capture

Invoke `Skill: headspin-capture` and execute the full lifecycle against the device in `$1`:

1. `hs_adb_lock` (`timeout: 30`) — abort with the lock-holder message if `status != 0`.
2. `hs_start_capture` with `capture_video: true` on the full device address.
3. Drive the requested app (`$2`, default YouTube) via `hs_adb_shell` for `$3` minutes
   (default 3.5): launch intent, then one `input swipe` every ~10 s. Capture
   `dumpsys window | grep mCurrentFocus` before and after driving as foreground proof.
4. `hs_stop_capture`, then poll `hs_session_timestamps` until `capture-complete`.
5. `hs_adb_unlock` — ALWAYS, even after errors.
6. Report the session_id, wall-clock duration, and hand off to `/headspin:sessions` for the
   report and `/headspin:waterfall` for the MP4/HAR artifacts.

Never run two captures on the same device. Never leave a device locked.
