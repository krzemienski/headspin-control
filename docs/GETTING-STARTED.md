# Getting Started: Log in and see the value in a week

A guide for a HeadSpin customer who just installed the plugin. It answers two
questions: **how do I log in?** and **why is this actually useful?** Every example is
from a real run against `api-dev.headspin.io` on 2026-07-02.

---

## Day 0 — Log in (2 minutes)

```
/headspin:login
```

What happens:

1. The command opens your environment's HeadSpin UI (`ui-<env>.headspin.io`) in a browser.
2. You sign in normally and copy your **API token** (User Settings → API Tokens).
3. The plugin stores it in your OS keychain and surfaces it to every tool as a Bearer
   credential. For the interactive control/streaming planes it also captures the
   **browser-login identity JWT** (see "Two credentials" below).

Confirm you're connected:

```
/headspin:devices
```

Real result: a roster of **34 devices** across `android, ios, roku, safari, tizentv`,
each with its online status, model, and address. That roster is your whole lab in one
list — no VPN, no per-device SSH, no manual reservation spreadsheet.

---

## Day 1 — Inspect a real device (no reservation needed)

Ask for an iOS device's identity:

```
/headspin:connect <pick an iOS device>
```

Behind the scenes the `hs_idevice_info` tool returns the device's live lockdownd dump.
Real sample from validation (`00008140-0004156A21D3001C`):

```
DeviceName:     iPhone
ProductVersion: 26.4.1
ProductType:    iPhone17,1
UniqueDeviceID: 00008140-0004156A21D3001C
```

And its installed apps (`hs_installer_list`) — 11 apps including the WebDriverAgent
runner (`io.headspin.webdriveragent`), so you know the device is automation-ready.

**Why this matters:** in five seconds you confirmed a real device, its OS version, and
that the automation stack is installed — the three things that usually cost a support
ticket.

---

## Day 2 — Reserve, drive, release (the core loop)

```
/headspin:connect <device>     # locks the device for you
/headspin:control <input>      # drive it (iOS: Appium/xcuitest; Android: socket.io input.*)
/headspin:disconnect           # releases the lock
```

The lock lifecycle is real and safe:

- Locking attaches **you** as owner (`owner_email` becomes your address).
- The plugin's Stop / SessionEnd hooks **auto-release** your lock when your session
  ends — so you never strand a device.
- A device is only "held" when it has an `owner_email` / `session_id`. (A bare `lock_id`
  UUID is just an ambient idle marker — 13 of 33 online devices carry one at rest with
  no owner. The plugin keys reservation off the owner, not the marker, so it never
  false-reports a free device as busy.)

**Why this matters:** the #1 lab pain is stranded reservations. The plugin makes
lock/unlock a guaranteed round-trip with automatic cleanup.

---

## Day 3–4 — Autonomous exploration + bug reports

```
/headspin:explore <app or device>
```

The `device-explorer` agent drives an already-locked session, captures logs and
screenshots, and flags anomalies. When it finds one:

```
/headspin:report
```

The `bug-reporter` agent produces a standardized report — summary, severity,
environment, device context, repro steps, expected vs actual, screenshots, logs,
timestamps, and cleanup state — so the bug is filable without you retyping context.

**Why this matters:** a device farm's value is finding real bugs on real hardware. This
turns "I saw something weird" into a complete, evidence-backed report in one command.

---

## Day 5–7 — Realizing it's actually useful

By the end of week one you have, without leaving Claude Code:

- **One-command lab visibility** — the full 34-device roster, live status, on demand.
- **Zero-friction inspection** — device identity + installed apps in seconds.
- **Safe reservations** — lock/drive/release with automatic cleanup, no stranded devices.
- **Real automation** — Appium (iOS xcuitest, token-in-path) and socket.io input for
  Android/Cast/Fire TV, all against real hardware.
- **Filable bugs** — autonomous exploration → standardized report, evidence attached.

Everything is against the **real** API. There are no mocks anywhere in the plugin — the
2026-07-05 validation exercised all 20 MCP tools live: a full capture lifecycle on a real
Galaxy S10 (lock → record → drive → 6.9 MB MP4 + issue card + 16 time series), a live
iOS lock/unlock cycle on a real iPhone 11, and the control/streaming planes characterized
end to end (`e2e-evidence/headspin-cook-260705/VALIDATION-REPORT.md`).

---

## Two credentials (the one thing worth understanding)

HeadSpin uses **two different credentials**, and the plugin handles both — but knowing
which is which saves you the one confusing error you might hit:

| Plane | Credential | How you get it | Carrier |
|---|---|---|---|
| REST (`/v0/…`), Appium | your **API token** | User Settings → API Tokens | `Authorization: Bearer` (REST) / token-in-path (Appium) |
| socket.io control, `/d/` screen, iOS `:5002`, Janus | **browser-login identity JWT** (+ Janus secret) | obtained during `/headspin:login` browser sign-in | `?access_token=` / `?jwt=` query param / Janus body `token` |

If you ever see **`"Failed to decode jwt access_token."`** on a control WebSocket, it
means the API token (or a `/v0/jwt/permissions` lease JWT) was used where the
**identity JWT** is required. Fix: re-run `/headspin:login` so the browser-minted
identity JWT is captured. This is a real, verified boundary — not a plugin bug
(`e2e-evidence/headspin-forge-260702/ws-live-probe/VERDICT.md`).

---

## Quick command reference

| Command | Does |
|---|---|
| `/headspin:setup` | first-run onboarding (config, hosts, token) |
| `/headspin:login` | browser sign-in; stores token + identity JWT |
| `/headspin:devices` | list the live device roster |
| `/headspin:connect` | resolve + lock a device, open its control session |
| `/headspin:control` | send input to the locked device |
| `/headspin:explore` | autonomous exploration (device-explorer agent) |
| `/headspin:report` | standardized bug report (bug-reporter agent) |
