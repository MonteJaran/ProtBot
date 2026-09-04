"""
app.py - The sync server, implementing server/models.py's contract exactly.

Run locally: `uvicorn server.app:app --reload` (see server/README.md for
what a real deployment still needs — this runs, and is tested, but has
never been deployed anywhere).

Every route below exists because a client already calls it —
core/syncclient.py, core/linking.py and core/licensing.py were all written
and tested against this exact contract before any server answered it. This
file is that answer, not a redesign: where a request needed a model that
did not exist yet (SyncReq, LinkNewReq, LicenseVerifyReq/Resp) or a field
the real client already sends but the model was missing (UploadReq.z),
server/models.py gained it — additively, matching what the tested clients
already do, never the other way around.
"""

import os
import time

from fastapi import FastAPI, HTTPException, Request

from server import auth
from server import db as dbmod
from server.models import (
    AppSyncReq, AppSyncResp,
    GroupDevice, GroupResp,
    LicenseVerifyReq, LicenseVerifyResp,
    LinkJoinReq, LinkJoinResp,
    LinkNewReq, LinkNewResp,
    RegisterReq, RegisterResp,
    SyncReq, SyncResp,
    UploadReq, UploadResp,
)
from server.ratelimit import RateLimiter

DATA_DIR = os.environ.get("PROTBOT_SERVER_DATA_DIR", ".")
MAX_PLAUSIBLE_DAILY_SEC = 24 * 60 * 60   # core/syncproto.py's own clamp, mirrored

app = FastAPI(title="ProtBot Sync Server")
database = dbmod.ServerDatabase(DATA_DIR)

# server/models.py note 4 + AUDIT SF-09's other half: rate-limit the two
# link endpoints specifically, since an 8-character key is the thing
# actually worth guessing in bulk before it expires. See server/ratelimit.py
# for what this does and does not protect against.
_link_new_limiter = RateLimiter(max_requests=10, window_sec=60)
_link_join_limiter = RateLimiter(max_requests=20, window_sec=60)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ── Registration ─────────────────────────────────────────────────────────────

@app.post("/register", response_model=RegisterResp)
def register(req: RegisterReq):
    # req.e (email) is read and immediately dropped — never reaches
    # database.create_device — per server/models.py's own note: "email —
    # discarded immediately after response." Nothing here stores it, logs
    # it, or passes it anywhere.
    token = dbmod.new_token()
    result = database.create_device(
        auth.hash_token(token), name=req.n or "", platform=req.p or ""
    )
    return RegisterResp(id=result["id"], tok=token)


# ── App list sync ────────────────────────────────────────────────────────────

@app.post("/apps", response_model=AppSyncResp)
def sync_apps(req: AppSyncReq, request: Request):
    device = auth.require_device(database, request, req.d)
    database.touch_device(device["id"])

    mapping = {}
    for entry in req.a:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        local_id, canonical_key = entry[0], entry[1]
        category = entry[2] if len(entry) > 2 else ""
        canonical_key = str(canonical_key or "").strip()
        if not canonical_key:
            continue
        server_id = database.get_or_create_app(
            device["group_id"], canonical_key, str(category or "")
        )
        mapping[str(local_id)] = server_id

    return AppSyncResp(m=mapping)


# ── Usage upload ─────────────────────────────────────────────────────────────

@app.post("/upload", response_model=UploadResp)
def upload(req: UploadReq, request: Request):
    device = auth.require_device(database, request, req.d)
    database.touch_device(device["id"])

    for entry in req.a:
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        server_app_id, seconds = entry
        try:
            server_app_id = int(server_app_id)
            seconds = int(seconds)
        except (TypeError, ValueError):
            continue
        if seconds <= 0:
            continue
        # An app id has to actually belong to this device's own group —
        # accepting any id the client happens to send would let one group
        # write usage into another group's rows.
        if database.app_group(server_app_id) != device["group_id"]:
            continue
        database.record_usage(
            device["id"], server_app_id, req.z, min(seconds, MAX_PLAUSIBLE_DAILY_SEC)
        )

    return UploadResp(ok=1)


# ── Cross-device sync ────────────────────────────────────────────────────────

@app.post("/sync", response_model=SyncResp)
def sync(req: SyncReq, request: Request):
    device = auth.require_device(database, request, req.d)
    database.touch_device(device["id"])

    totals = database.group_totals(device["group_id"], device["id"])
    members = database.group_members(device["group_id"])
    return SyncResp(apps=totals, devices=max(1, len(members)))


# ── Device linking ───────────────────────────────────────────────────────────

@app.post("/link/new", response_model=LinkNewResp)
def link_new(req: LinkNewReq, request: Request):
    if not _link_new_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429,
                             detail="Too many link requests. Try again shortly.")
    device = auth.require_device(database, request, req.d)
    database.touch_device(device["id"])

    key = database.create_link_key(device["group_id"])
    return LinkNewResp(k=key)


@app.post("/link/join", response_model=LinkJoinResp)
def link_join(req: LinkJoinReq, request: Request):
    if not _link_join_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429,
                             detail="Too many join attempts. Try again shortly.")
    device = auth.require_device(database, request, req.d)
    database.touch_device(device["id"])

    group_id = database.consume_link_key(req.k)
    if not group_id:
        # Expired, already used, or never existed — core/linking.py's
        # join_link() treats any falsy "ok" as the same user-facing message
        # ("expired or already used"), so there is nothing finer-grained to
        # report here.
        return LinkJoinResp(ok=0, grp="")

    database.join_group(device["id"], group_id)
    return LinkJoinResp(ok=1, grp=group_id)


# ── Group device list ────────────────────────────────────────────────────────

@app.post("/group", response_model=GroupResp)
def group(request: Request):
    device = auth.require_device_by_token(database, request)
    database.touch_device(device["id"])

    members = database.group_members(device["group_id"])
    devices = [
        GroupDevice(
            id=m["id"],
            name=m.get("name") or None,
            platform=m.get("platform") or None,
            seen=int(m["last_seen"]) if m.get("last_seen") else None,
            isOwn=(m["id"] == device["id"]),
        )
        for m in members
    ]
    return GroupResp(devices=devices)


# ── Licence verification ─────────────────────────────────────────────────────

@app.post("/license/verify", response_model=LicenseVerifyResp)
def license_verify(req: LicenseVerifyReq):
    """
    Unauthenticated on purpose — activating a licence is how a fresh
    install without a device_id yet proves anything at all, and the key
    itself is the credential being checked. core/licensing.py treats
    HTTP 402/403/404/410 as an explicit rejection (revokes/declines the
    key) and anything else that fails as "could not check, change
    nothing" — see verify_with_server()'s docstring.

    How a key gets into license_keys at all: server/issue_license.py for
    now (a manual CLI, see its own docstring), a Paddle webhook once
    STATUS.md item 11 is set up and its payload format is known.
    """
    row = database.license_lookup(req.k)
    if not row:
        raise HTTPException(status_code=404, detail="Unknown licence key.")

    expires_at = float(row.get("expires_at") or 0)
    if row["plan"] == "premium" and expires_at and expires_at < time.time():
        raise HTTPException(status_code=410, detail="Licence has expired.")

    return LicenseVerifyResp(plan=row["plan"], expires_at=expires_at)
