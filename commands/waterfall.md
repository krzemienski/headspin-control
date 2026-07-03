---
description: Download and inspect a HeadSpin session's Waterfall network data and captured artifacts (HAR, screen-recording MP4, device event log, PCAP).
argument-hint: "[session-id] [ext=har|mp4|device.log.gz|pcap]"
---

# /headspin:waterfall

Retrieve the **Waterfall network data** and other captured artifacts for a HeadSpin capture
session, then inspect them locally. The Waterfall in the HeadSpin UI is backed by the session
HAR (network timing) plus the issue card; this command pulls the raw data to disk.

## Steps

1. **Resolve the session** from `$ARGUMENTS`. If no `session-id` is given, call
   `hs_list_sessions { "include_all": true, "num_sessions": 20 }` and let the user pick the
   session they mean (most recent, or matched by device/time).

2. **Confirm what the session captured** before pulling a large file:

   ```
   hs_session_video_metadata { "session_id": "<sid>" }    # 200 => has an MP4
   hs_session_timeseries_info { "session_id": "<sid>" }    # device signals captured
   ```

3. **Download the Waterfall network data** (default when no `ext=` given):

   ```
   hs_session_download { "session_id": "<sid>", "ext": "har", "enhanced": true }
   ```

   The file streams to disk; the tool returns `{saved_to, bytes, content_type}` — never the raw
   bytes. Summarize `log.entries[]` (count, slowest requests, non-2xx). A 404 means the session
   captured no network — report "no network waterfall".

4. **Download other artifacts on request** — `ext=mp4` (screen recording, optional `fps`),
   `ext=device.log.gz` (device event log, gunzip to read), `ext=pcap` (+ `sslkeylog.txt` to
   decrypt). Valid ext: `har, mar, csv, mp4, pcap, device.log.gz, appium.log.gz,
   selenium.log.gz, jsconsole.log.gz, sslkeylog.txt`.

5. **Offer the interactive UI Waterfall**: `https://<ui_host>/sessions/<sid>/waterfall`.

6. **Invoke the headspin-waterfall skill** for the full workflow (artifact existence checks,
   HAR summarization, redaction of tokens/serials/emails). Read-only over the device — no lock
   required. Cite the `saved_to` path; never inline a multi-MB file into chat.
