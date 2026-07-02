---
name: headspin-session-manager
description: Acquire (lock) a HeadSpin device for the current user, track the lock + lease expiry, release (unlock) on Stop / SessionEnd / explicit /headspin:disconnect, and surface lock conflicts when another user holds the device. REST auth is Authorization Bearer (no orgkey); the per-device lock/unlock REST routes are doc-inferred (not HAR-verified) and the only observed lock state is the socket.io devicelist. Invoke when /headspin:connect is about to lock a device, when the lease is about to expire (warn user 60s out), and when any hook needs to clean up locks on session end.
allowed-tools: Read, Bash, Grep
---

# headspin-session-manager

## When to use

- `/headspin:connect` is about to acquire an exclusive lock on a device.
- A device lock is held by the user but the lease is about to expire.
- The user runs `/headspin:disconnect` or quits Claude Code (Stop / SessionEnd hook).
- A different user already holds the device lock and the current user needs the device.

## Prerequisites

- `headspin-login` has been run; `HEADSPIN_API_HOST` and `HEADSPIN_API_KEY` are set.
- `headspin-list-devices` has resolved the candidate device (iOS `{udid}@{host}` address, or Android serial + control port).

## Auth + endpoint provenance (read first)

- **REST auth is `Authorization: Bearer <api_token>`** (header name `authorization`) — correct and proven by CORS preflight (`raw-forensics/auth-inventory.md` §1a). There is **no `orgkey:token`** header anywhere. All REST calls below keep the Bearer header.
- **The lock/unlock REST routes are LIVE-VERIFIED** (2026-07-02, `live-validation/` + `fix-matrix/LOCK-ENDPOINT-DEBUGGED.txt`). Two working forms exist:
  - **Per-device (preferred):** `POST /v0/idevice/{device_address}/lock` (no body) → `200 {"status":0,"message":"{device_address} locked."}`; `.../unlock` → `{"...":"unlocked."}`. Targets exactly this device.
  - **Account-level:** `POST /v0/devices/lock` with body `{"device_id":"<serial|udid>"}` → `200 {"status_code":200,"status":"Locked device ..."}`; unlock same body on `/v0/devices/unlock`. **DANGER: an empty body `{}` locks a RANDOM free device** — always pass an explicit `device_id`. The selector key is `device_id`, NOT `device_address` (a `device_address` body 400s).
  These were unobserved in the original HAR (the UI web app leases via the socket.io control channel) but are proven against the live api-dev.headspin.io.
- **The only lock STATE actually observed** in the capture is the socket.io `devicelist[].lockId` (UUID or null) + `owner{email,group,name,plainEmail}` (PII → redact) + boolean `using`, on the Android control ports (`API-CONTRACT.md` §2/§4). iOS lock state is NOT in any REST body and the iPhone is absent from `devicelist` (`raw-forensics/auth-inventory.md` §3). Read lock state from `devicelist` (via `headspin-list-devices`), not from a REST `info` body.
- **RESERVATION SIGNAL — LIVE-CORRECTED 2026-07-02 (load-bearing):** on the REST `/v0/devices` roster, a bare `lock_id` (UUID) is an **ambient idle marker, NOT a reservation** — 13 of 33 online devices sit at rest with a non-null `lock_id` and null owner. **A device is only actually HELD when `owner_email` / `owner.email` / `session_id` is populated.** Proven by a decisive adopt→release cycle: account `POST /v0/devices/lock {"device_id":<udid>}` set `owner_email=<user>@headspin.io`, and `POST /v0/devices/unlock {"device_id":<udid>}` cleared it back to null while `lock_id` stayed non-null throughout (`e2e-evidence/headspin-forge-260702/func-validation-260702b/05-lock-lifecycle-resolved.md`). **Detect held/free off `owner_email`/`session_id`, never off `lock_id` presence** — keying on `lock_id` yields a false HELD on every idle device. Correspondingly, the per-device `POST /v0/idevice/{addr}/unlock` returns `{"status":1,"message":"Did not unlock."}` when there is no *owned* lease to release (that is success, not failure).

## Workflow

1. **Lock the device (LIVE-VERIFIED REST route).** The lock gives the user a lease to drive the device; without it the device tunnel may reject connections. Preferred per-device form (works for iOS and, per live automation-config, every platform that exposes a `lock_url`):

   ```bash
   # device_address = {udid}@{proxy-host}.headspin.io (URL-safe segment)
   curl -sS -X POST -H "Authorization: Bearer ${HEADSPIN_API_KEY}" \
        "${HEADSPIN_API_HOST}/v0/idevice/${DEVICE_ADDRESS}/lock"
   # -> 200 {"status":0,"message":"${DEVICE_ADDRESS} locked."}
   ```

   Account-level alternative (any device_type): `POST /v0/devices/lock` with body `{"device_id":"<serial|udid>"}`. **Never send an empty body** — `{}` locks a random free device. Always capture the real status + body. Confirm the hold afterward via the socket.io `devicelist[].lockId`/`owner`/`using` (read through `headspin-list-devices`) — that is still the authoritative lock-state signal, especially for Android/Cast/Fire TV.

   Persist whatever the server returns to `/tmp/headspin-control/lock.json` so the connection-manager can reuse the resolved host and the Stop hook can release with the right device identifier. If the route 404s, treat the device as lease-via-socket.io and record the `devicelist` lock state instead.

2. **Track the lease.** If the DOC-INFERRED lock route exists, HeadSpin device locks carry a server-side TTL (documented; not observed in this capture). Start a background timer that re-issues the **same** per-device lock call every (TTL - 60s) so the lease is renewed before it expires. The background process is a simple `bash` loop that PID-files itself:

   ```bash
   LOCK_RENEW_INTERVAL=$((15 * 60 - 60))   # 14 minutes for a 15-minute default TTL (documented; adjust to real TTL)
   (
     while true; do
       sleep ${LOCK_RENEW_INTERVAL}
       curl -sS -X POST -H "Authorization: Bearer ${HEADSPIN_API_KEY}" \
            -H "Content-Type: application/json" \
            "${HEADSPIN_API_HOST}/v0/idevice/${DEVICE_ADDRESS}/lock" \
            >> /tmp/headspin-control/lock-renew.log 2>&1
     done
   ) &
   echo $! > /tmp/headspin-control/lease-renewer.pid
   ```

   If the lease-renewer dies (PID file gone, but lock still held), the next Stop hook will warn that another user may grab the device. If the user sets a custom TTL via plugin config in the future, adjust `LOCK_RENEW_INTERVAL` to match. (TTL value is DOC-INFERRED — not observed in this HAR.)

3. **Handle lock conflict.** When the lock POST returns a 4xx (e.g. 403/409), the device may be held by another user. Surface:

   - HTTP status code
   - The full response body (which sometimes includes the current lock owner)
   - The remediation: ask the owner to release, or pick a different device via `/headspin:devices`

   To check current holders, read the socket.io `devicelist` lock state — `lockId` (UUID or null) + `owner{email,group,name,plainEmail}` (redact PII) + `using` — via `headspin-list-devices` (Android/Cast/Fire TV). This is the only **observed** lock-holder signal in the capture (`API-CONTRACT.md` §2/§4). A documented `GET /v0/devices/locked` REST route is NOT exercised here — do not assume it exists.

4. **Release on Stop / SessionEnd.** The `hooks/hooks.json` `Stop` and `SessionEnd` hooks call this skill's release step. Use the DOC-INFERRED per-device unlock route:

   ```bash
   curl -sS -X POST -H "Authorization: Bearer ${HEADSPIN_API_KEY}" \
        -H "Content-Type: application/json" \
        "${HEADSPIN_API_HOST}/v0/idevice/${DEVICE_ADDRESS}/unlock"
   ```

   `/v0/idevice/{device}/unlock` is documented but **NOT exercised in this capture** (`API-CONTRACT.md` §8) — capture the real status + body rather than assuming a response shape. After a successful unlock, kill the lease-renewer PID and remove `/tmp/headspin-control/lock.json`. If the unlock returns a non-2xx, log the full body and tell the user the device may stay locked until the TTL expires.

5. **Force-unlock (admin escape hatch).** A `POST /v0/devices/force_unlock` (unlock any user's device in the org) is DOC-INFERRED — documented but NOT exercised in this capture (`API-CONTRACT.md` §8). If used, keep the `Authorization: Bearer` header, and do NOT call it without explicit user confirmation — the action is logged and visible to the device owner.

## Evidence

- REST auth is `Authorization: Bearer <api_token>` (no `orgkey:token`): `e2e-evidence/headspin-forge-260702/raw-forensics/auth-inventory.md` §1a.
- Lock/unlock/force-unlock REST routes are DOC-INFERRED (documented, NOT exercised in the capture): `e2e-evidence/headspin-forge-260702/har-forensics/API-CONTRACT.md` §8 (unverifiable REST/CLI endpoints list) + DL-6 (no `/v0/devices*` route observed).
- Observed lock STATE carrier = socket.io `devicelist[].lockId`/`owner`/`using`: `API-CONTRACT.md` §2 and §4.
- iOS device address form `{udid}@{proxy-host}`: `raw-forensics/auth-inventory.md` §2/§3; iOS lock state NOT in REST `info` body: same, §3.
- Hook lifecycle (Stop, SessionEnd): `headspin-docs/.../plugins-reference.md:118-150` (defines when Stop / SessionEnd fire).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `HEADSPIN_API_KEY` empty | `headspin-login` not run | Re-run `/headspin:login`. |
| 401 from a lock/unlock REST call | Token revoked or missing lock permission | Re-run `/headspin:login`; ask the org admin to grant the permission. |
| 404 from `/v0/idevice/…/lock` | The DOC-INFERRED lock route does not exist in this deployment | Treat the device as lease-via-socket.io; read/hold lock state from `devicelist[].lockId` instead of a REST lock. |
| Android device: no REST lock route at all | Android lock rides socket.io, not REST | Read `devicelist[].lockId`/`owner`/`using` via `/headspin:devices`; do not fabricate a `/v0/devices/lock` call. |
| Lock POST 4xx with an owner in the body | Another user holds the device | Surface the lock owner (redact PII); do not force-unlock without explicit confirmation. |
| Lock acquired but the renewer dies | Background bash loop killed (Ctrl-C, parent shell exit) | The next Stop hook will see the missing PID file and warn the user; the device will release on TTL expiry. |
| Unlock returns a 4xx "no such lock" | The user never locked the device (a previous run failed to record it) | Silently log and continue; nothing to release. |
| Force-unlock returns 403 | Token lacks the org-admin role | Refuse and tell the user the action requires admin. |
