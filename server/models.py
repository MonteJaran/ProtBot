"""
models.py — Minimal Pydantic request/response models.

Key design: single-char JSON keys to shrink every payload.
Upload cycle: every 30 minutes.

The clients are core/syncproto.py (desktop) and
android/core/.../Sync.kt (Android). Both are written against the semantics
below and tested against them; a server that implements this file differently
will produce wrong totals rather than errors, so read the four notes before
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

  4. **The device id is not a credential.** It names a device; it does not
     prove you are one. It appears in every payload, it is shown to the user
     in the Devices tab, and treating it as an access token is a textbook
     IDOR — anyone who reads one out of a log can read that user's data. See
     the section below, which is the one part of this file a server cannot
     get wrong quietly: the totals would still be right, and they would be
     right for whoever asked.

`SyncResp.apps` returns the group total per app, including the requesting
device's own last upload. Clients subtract their own contribution before
merging; see syncproto.merge_app_total for why that is not the same as taking
the larger of the two numbers.

## Authentication (AUDIT SF-09)

Every endpoint except `/register` requires:

    Authorization: Bearer <device_token>

`/register` is the exception because it issues the token. It returns both
halves of the credential — `RegisterResp.id` names the device and
`RegisterResp.t` proves it — and a client that gets an id without a token
discards both and stays unregistered, so a server that omits `t` disables
sync rather than falling back to an unauthenticated one.

What the server has to hold up:

  * **Store a hash of the token, not the token.** It is a bearer credential:
    a database dump containing them is every user's data, and the server
    never needs the original after the one response that hands it over.

  * **Check the token before the payload.** Every request also carries `d`,
    the device id. It is routing information, not proof — the token must
    resolve to a device on its own, and `d` must match the device it
    resolves to. A server that trusts `d` because the request happened to
    carry *some* valid token has rebuilt the vulnerability with extra steps.

  * **Answer 401 for a missing or unknown token and 403 for one that does
    not own the data.** Clients treat both as permanent: sync stops and the
    user is told to register the device again, rather than a rejected
    request going out every thirty minutes forever. Do not use either code
    for rate limiting or maintenance — 429 and 503 are retried, and these
    are not.

  * **Never log the header.** Nor echo it back in an error body.

  * **Rate-limit `/link/new` and `/link/join`.** The link key is eight
    characters from a 32-character alphabet, so guessing is worth trying if
    guesses are free. Both endpoints are authenticated as well, which is what
    makes rate limiting per device possible in the first place.

  * **Issue the token with a CSPRNG**, at least 128 bits, and treat
    unregistering as revoking it.
"""

from pydantic import BaseModel


# ── Registration ───────────────────────────────────────────────────────────────

class RegisterReq(BaseModel):
    e: str | None = None   # email — discarded immediately after response
    n: str | None = None   # device label, shown only in the user's device list

class RegisterResp(BaseModel):
    id: str                   # 24-char device_id — names the device
    # The secret half of the credential, sent as `Authorization: Bearer <t>`
    # on every later request. Issued once, here, and never returned again;
    # store only a hash of it. A response without this field leaves the
    # client unregistered — see the authentication section above.
    t: str


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
    d: str                    # device_id — routing only; the header authenticates
    t: int                    # period end — unix timestamp (int, not ISO string)
    z: str                    # the client's local date, "YYYY-MM-DD". Store verbatim.
    a: list[list]             # [[server_app_id, seconds], ...]  only s>0

class UploadResp(BaseModel):
    ok: int = 1


# ── Cross-device sync ─────────────────────────────────────────────────────────

class SyncReq(BaseModel):
    d: str                    # device_id — routing only; the header authenticates


class SyncResp(BaseModel):
    apps: dict                # {server_app_id: total_sec_today}
    devices: int              # number of linked devices


# ── Device linking ────────────────────────────────────────────────────────────

class LinkNewReq(BaseModel):
    d: str                    # device_id of the host device

class LinkNewResp(BaseModel):
    k: str                    # 8-char key, valid 5 minutes, single use

class LinkJoinReq(BaseModel):
    d: str                    # joining device_id
    k: str                    # key from the host device

class LinkJoinResp(BaseModel):
    ok: int = 1
    grp: str                  # shared group id


# ── The user's own device group ───────────────────────────────────────────────
# Shown in the Devices tab. A POST, not `GET /group/{device_id}`: an id in a
# path is an id in every access log between the client and the server, which
# is the concrete half of the weakness note 4 above is about.

class GroupReq(BaseModel):
    d: str                    # device_id — routing only; the header authenticates

class GroupDevice(BaseModel):
    id: str
    name: str | None = None       # the label the device gave at registration
    platform: str | None = None
    seen: int | None = None       # last upload — unix timestamp
    isOwn: bool = False           # the requesting device, which the UI hides

class GroupResp(BaseModel):
    devices: list[GroupDevice]


# ── Global anonymous stats ────────────────────────────────────────────────────

class GlobalStatsResp(BaseModel):
    # {category: {sec_today, users_today}}
    cats: dict
    total_users: int
