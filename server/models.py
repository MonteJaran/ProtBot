"""
models.py — Minimal Pydantic request/response models.

Key design: single-char JSON keys to shrink every payload.
Upload cycle: every 30 minutes.

The clients are core/syncproto.py (desktop) and
android/core/.../Sync.kt (Android). Both are written against the semantics
below and tested against them; a server that implements this file differently
will produce wrong totals rather than errors, so read the three notes before
building one.

  1. **Uploads are cumulative, not deltas.** `UploadReq.a` carries each app's
     running total for the day named in `z`, not the seconds since the last
     upload. Store it with `max(stored, received)` per (device, app, date).
     That makes a retry after a lost response a no-op, makes out-of-order
     arrivals settle correctly, and lets a device that was offline for six
     hours catch up in one request. Adding deltas instead double-counts every
     retried upload, and there is no acknowledgement scheme that fixes it
     without becoming a transaction log.

  2. **The date is the client's, not the server's.** `UploadReq.z` is the
     device's local date and must be stored verbatim. A server bucketing by
     its own UTC date puts a Belgrade evening into tomorrow, and the user
     watches their daily limit reset at 2am.

  3. **App identity is the canonical key.** `AppSyncReq.a` sends
     `syncproto.canonical_app_key(name)`, not the display name — the desktop
     knows the app as "Discord.exe" and the phone as "com.discord", and they
     have to land in one row. The server matches on that key within a device
     group and assigns one server id.

`SyncResp.apps` returns the group total per app, including the requesting
device's own last upload. Clients subtract their own contribution before
merging; see syncproto.merge_app_total for why that is not the same as taking
the larger of the two numbers.

  4. **`id` names a device; `tok` authenticates the request.** AUDIT SF-09:
     an earlier draft of this protocol used `device_id` alone as the
     credential on every request, and it travels in request bodies (and, in
     one client that predated this file, a URL path) where it lands in
     server and proxy logs — anyone who obtains one can read and pollute
     that device's data. `RegisterResp.tok` is a second, higher-entropy
     secret returned once, at registration, and never again. Every request
     after that MUST carry it as `Authorization: Bearer <tok>` and the
     server MUST reject (401) a request whose token does not match the `d`
     it claims — a bare device id in a body or path is no longer sufficient
     on its own. `/link/new` and `/link/join` need it too, and the audit's
     other half of this finding — rate-limiting the link-code endpoint —
     is still open; nothing in the client can substitute for that.
     Both clients (`core/syncclient.py`, `android/app/.../SyncClient.kt`)
     send this header on every authenticated request once they hold a
     token; this file records the contract they were built against; the
     server that checks it does not exist yet — see STATUS.md.
"""

from pydantic import BaseModel


# ── Registration ───────────────────────────────────────────────────────────────

class RegisterReq(BaseModel):
    e: str | None = None   # email — discarded immediately after response
    n: str | None = None   # device label, shown only in the user's device list
    p: str | None = None   # platform ("Windows", "Android"), for the device list's icon

class RegisterResp(BaseModel):
    id: str                   # 24-char device_id
    tok: str                  # secret bearer token — returned once, store it, never send it back


# ── App list sync (sent once, or when tracked apps change) ────────────────────
# Each entry: [local_db_id, name, category]
# Example: [[1,"Discord","Social"],[2,"VS Code","Development"]]

class AppSyncReq(BaseModel):
    d: str                    # device_id
    a: list[list]             # [[local_id, name, category], ...]

class AppSyncResp(BaseModel):
    m: dict                   # {"local_id": server_id, ...}


# ── 30-minute usage upload ────────────────────────────────────────────────────
# "a" contains only apps that had usage > 0 in this window.
# Each entry: [server_app_id, seconds_used]
# Example: [[42,1800],[43,270]]

class UploadReq(BaseModel):
    d: str                    # device_id
    t: int                    # period end — unix timestamp (int, not ISO string)
    z: str                    # the client's own local date (note 2) — the
                               # field this class was missing until the server
                               # implementation was written against
                               # core/syncproto.py's actual build_upload(),
                               # which has always sent it. Stored verbatim.
    a: list[list]             # [[server_app_id, seconds], ...]  only s>0

class UploadResp(BaseModel):
    ok: int = 1


# ── Cross-device sync ──────────────────────────────────────────────────────────
# POST body is just the device id — core/syncclient.py's _sync_once() sends
# {"d": self.device_id} and nothing else. No date travels with this request;
# the group total is built from each device's own most recently *uploaded*
# date, not a date supplied here — see server/db.py's group_totals().

class SyncReq(BaseModel):
    d: str                    # device_id

class SyncResp(BaseModel):
    apps: dict                # {server_app_id: total_sec_today}
    devices: int              # number of linked devices


# ── Device linking ────────────────────────────────────────────────────────────
#
# /link/new and /link/join both require the Authorization header like every
# other endpoint below this point — the `d` field they carry is which device
# the request is about, not proof of who is asking. See note 4 above. The
# audit's fix also calls for rate-limiting /link/new and /link/join: an
# 8-character key is guessable in bulk without one, however short its life.

class LinkNewReq(BaseModel):
    d: str                    # the host device_id the new key's group is for

class LinkNewResp(BaseModel):
    k: str                    # 8-char key, valid 5 minutes

class LinkJoinReq(BaseModel):
    d: str                    # joining device_id
    k: str                    # key from the host device

class LinkJoinResp(BaseModel):
    ok: int = 1
    grp: str                  # shared group id


# ── Group device list (Devices tab) ───────────────────────────────────────────
#
# GET /group, Authorization header only — no device id in the request at all,
# path or body. The token alone says which group to list, which is the point:
# nothing here is a wider fix for the same class of bug SF-09 names elsewhere.

class GroupDevice(BaseModel):
    id: str
    name: str | None = None
    platform: str | None = None       # "Windows" / "Android", for the icon
    seen: int | None = None           # unix timestamp, last successful /sync
    isOwn: bool = False

class GroupResp(BaseModel):
    devices: list[GroupDevice]


# ── Licence verification (STATUS.md item 10) ────────────────────────────────
#
# core/licensing.py's verify_with_server() sends this and reads this back
# already — it was written and tested against this exact shape before a
# server existed to answer it. Unauthenticated on purpose: activating a
# licence is how a fresh install without a device_id yet proves anything at
# all, and the key itself is the credential being checked.

class LicenseVerifyReq(BaseModel):
    k: str                    # licence key
    d: str = ""                # device_id, for binding/telemetry — optional,
                               # core/licensing.py sends it whenever a device
                               # is registered but activation does not require one

class LicenseVerifyResp(BaseModel):
    plan: str                 # "free" or "premium"
    expires_at: float = 0     # unix timestamp; 0 means no expiry recorded


# ── Global anonymous stats ────────────────────────────────────────────────────
#
# Not called by any client yet — core/syncclient.py and core/licensing.py
# define every endpoint they actually use, and neither of them requests
# this. Kept as a model because a caller may exist later; server/app.py does
# not implement an endpoint for it, so there is nothing here to drift out of
# sync with in the meantime.

class GlobalStatsResp(BaseModel):
    # {category: {sec_today, users_today}}
    cats: dict
    total_users: int
