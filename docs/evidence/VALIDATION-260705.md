# HeadSpin Control Plugin — Full-System Live Validation

**Run:** headspin-cook-260705 | **Date:** 2026-07-05 | **API:** api-dev.headspin.io | **Verdict: 20/20 tools PASS**

Every MCP tool exercised against the real HeadSpin API — no mocks, no fixtures. One full capture
lifecycle executed on a real Samsung SM-G973W (Galaxy S10, Android 12, Toronto proxy).

## Capture lifecycle (real device, real session)

| Step | Tool | Result | Evidence |
|------|------|--------|----------|
| 1 | `hs_login_details` | 200, org email confirmed | inline (this session transcript) |
| 2 | `hs_list_devices` | 34 devices, 33 online (20 android / 8 ios / 3 roku / 1 tizen / 1 safari) | `api/list_devices_full.json` (536 KB) |
| 3 | `hs_adb_lock` R38N70234FA | `status:0` locked | transcript |
| 4 | `hs_adb_shell` `getprop ro.product.model` | `SM-G973W` | transcript |
| 5 | `hs_start_capture` | session `e8024cb0-788e-11f1-8491-da3445a29211`, state=active | transcript |
| 6 | `hs_adb_shell` — wake, home, open youtube.com, 2× swipe, tap | rc=0, SBrowser focused | transcript |
| 7 | `hs_stop_capture` | "Video uploaded to …/e8024cb0….mp4" | transcript |
| 8 | `hs_session_timestamps` | capture-started/ended/complete epochs (79.9 s span) | transcript |
| 9 | `hs_session_video_metadata` | 512×1184 h264, 23.105 fps, 80111 ms, audio 1ch | transcript |
| 10 | `hs_session_download` mp4 | **6,899,682 bytes** saved | `artifacts/session-e8024cb0.mp4` |
| 11 | `hs_session_download` har | 404 "no HAR for session" — correct API behavior: capture ran without network-tunnel proxying; error surfaced verbatim, no crash | transcript |
| 12 | `hs_analysis_status` | `done` | transcript |
| 13 | `hs_session_issues` | Waterfall issue card: "Audio Too Quiet" −30.8 LUFS | transcript |
| 14 | `hs_session_timeseries_info` | 16 series (impact, network, mar, audio, video) | transcript |
| 15 | `hs_session_timeseries_download` screen_change | **67,767 bytes** CSV | `artifacts/screen_change.csv` |
| 16 | `hs_session_tls_exceptions` | `{}` (none) | transcript |
| 17 | `hs_list_sessions` | our session listed first, state=ended, error_code=null | transcript |
| 18 | `hs_adb_unlock` | `status:0` unlocked (device released) | transcript |

## iOS surface

| Tool | Result |
|------|--------|
| `hs_idevice_info` 00008030-…402E | Full lockdownd dump: iPhone12,1, iOS 14.4.2, Toronto TZ |
| `hs_installer_list` | 6 apps (WebDriverAgent 1.22.3, HS Test App, Tether ×2, masterhand ×2) |
| `hs_lock_device` (iOS REST) | **`status:0` locked — route EXISTS and WORKS** |
| `hs_unlock_device` (iOS REST) | `status:0` unlocked |

## Defect found & fixed

`hs_lock_device` / `hs_unlock_device` descriptions in `mcp/headspin_mcp_server.py` claimed
"DOC-INFERRED / NOT HAR-verified… Expect this route may not exist here." Both routes were
proven live this run (lock + unlock cycle on a real iPhone 11, status:0 both directions).
Descriptions corrected to LIVE-VERIFIED 2026-07-05.

## Iron-rule compliance

- No mocks, stubs, or fixtures — every result above is a real HTTP response from api-dev.headspin.io.
- Device locked → driven → capture recorded → artifacts pulled → device unlocked (clean release).
- Binary artifacts on disk: `session-e8024cb0.mp4` (6.9 MB video of the actual drive), `screen_change.csv` (67 KB), `list_devices_full.json` (536 KB).
