---
description: Retrieve HeadSpin performance reports for a capture session — the Waterfall issue card, analysis status, and device time series (memory, battery, network, video-quality).
argument-hint: "[session-id]"
---

# /headspin:sessions

Pull the **HeadSpin report** for a capture session: the Waterfall issue card (performance
issues), analysis status, and the device time series that back the report. All Bearer REST via
the bundled MCP server.

## Steps

1. **Find the session.** `hs_list_sessions { "include_all": true, "num_sessions": 20 }` — 
   `include_all:true` includes ended sessions (the ones with finished reports). Pick the
   `session_id` the user means.

2. **Pull the Waterfall issue card** (the core report):

   ```
   hs_session_issues { "session_id": "<sid>", "orient": "record" }
   ```

   Same data as the HeadSpin Waterfall UI issue card. Each key is an issue category (Low Frame
   Rate, Domain Sharding, …). An empty `{}`/`[]` means no issues found — a valid result, not an
   error.

3. **Check analysis status** — `hs_analysis_status { "session_id": "<sid>", "timeout": 0 }`.
   Only report issues/time series once status is `done`.

4. **Read the device time series** that back the report:

   ```
   hs_session_timeseries_info { "session_id": "<sid>" }                       # available series
   hs_session_timeseries_download { "session_id": "<sid>", "key": "memory_used" }  # CSV to disk
   ```

5. **Add report context** — `hs_session_video_metadata` (dims/fps/duration; 404 = network-only)
   and `hs_session_tls_exceptions` (hosts whose TLS pinning blocked capture — a real waterfall
   gap signal).

6. **Invoke the headspin-reports skill** for the full workflow and output format. Summarize as a
   short report, not a JSON dump. Redact device serials / owner emails to their first 8 chars.
   To download the underlying artifacts (HAR/MP4/device log), use `/headspin:waterfall`.
