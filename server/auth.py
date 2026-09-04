"""
auth.py - Bearer-token authentication for the sync server.

server/models.py note 4 (AUDIT SF-09): a device id says which device a
request is *about*; the bearer token is what proves *who is asking*. Every
authenticated endpoint below checks the token against the specific device
it claims to act for — a token valid for device A must not authenticate a
request claiming to be device B, even one that has correctly guessed B's
device id (ids are not secret; tokens are).

/group is the one endpoint with no device id anywhere in the request — see
require_device_by_token.
"""

import hashlib
import hmac

from fastapi import HTTPException, Request

_INVALID = "Invalid or missing credentials."


def hash_token(token: str) -> str:
    """
    A token is only ever checked, never re-issued or displayed, so this
    only needs to support equality. A fast, unsalted SHA-256 is standard
    practice for a high-entropy random secret (32 bytes from
    secrets.token_urlsafe — server/db.py's new_token()) precisely because
    it has no low-entropy space for a rainbow table to exploit. Salting is
    what protects a password a human chose; it adds nothing here.
    """
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def require_device(db, request: Request, device_id: str) -> dict:
    """
    Verify the request's bearer token belongs to `device_id`. Returns the
    device row on success; raises HTTPException(401) otherwise — the same
    response whether the device does not exist, the header is missing, or
    the token is simply wrong, so a probe cannot tell "no such device" from
    "wrong token" (server/models.py note 4).
    """
    token = bearer_token(request)
    device = db.get_device(device_id) if device_id else None
    if not token or not device or not hmac.compare_digest(
        str(device["token_hash"]), hash_token(token)
    ):
        raise HTTPException(status_code=401, detail=_INVALID)
    return device


def require_device_by_token(db, request: Request) -> dict:
    """
    /group's shape: no device id anywhere in the request, so the token
    alone has to say whose group to list. See server/models.py's note on
    GroupResp: "nothing here is a wider fix for the same class of bug SF-09
    names elsewhere" — designed not to need a device id at all, not patched
    after the fact.
    """
    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail=_INVALID)
    device = db.get_device_by_token_hash(hash_token(token))
    if not device:
        raise HTTPException(status_code=401, detail=_INVALID)
    return device
