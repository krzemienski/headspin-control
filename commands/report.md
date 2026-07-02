---
description: Produce a standardized bug report from an exploration run directory.
argument-hint: "<run-dir>"
---

# /headspin:report

Turn an exploration run's evidence bundle into a standardized bug report.

## Steps

1. **Resolve the run directory** from `$ARGUMENTS`. If omitted, use the most recent run
   under `/tmp/headspin-control/` (or the exploration output root) and confirm with the
   user before proceeding.

2. **Verify the bundle exists** — the directory should contain the captured screenshots,
   UI hierarchies, and the anomaly log from `/headspin:explore`. If empty, tell the user to
   run `/headspin:explore` first.

3. **Invoke the headspin-bug-report skill** with the run directory. It reads the evidence,
   correlates the reproduction steps, and emits a standardized report (summary, steps to
   reproduce, expected vs actual, severity, attached evidence paths).

4. **Surface the report path** and a short summary. Note that this command is read-only over
   the device — no auth or live session is required.
