"""
linking.py - Pairing a phone with a PC by showing a code on one screen.

The sync protocol already had device linking: one device asks the server for a
short key, the other sends that key back with its own device id, and the two
join a group (server/models.py, LinkNewResp and LinkJoinReq). What it did not
have was a way to get the key from one screen to the other that did not
involve reading eight characters aloud and mistyping them.

So the PC shows a QR code and the phone points its camera at it. The key still
works typed — a camera that will not focus is a bad reason to be unable to link
a device — but nobody has to.

## What goes in the code

    https://protbot.app/l#1.ABCD2345
    └──────────────────┘ │ │  └─ the link key
                         │ └─ payload version
                         └─ a URL fragment

Three decisions in that one line.

**An https URL, not a `protbot://` scheme.** Custom schemes show up in a
phone camera as an unhelpful "no app can open this" when ProtBot is not
installed yet, which is exactly when someone is most likely to be scanning.
An https link opens a page that can explain what to install.

**The key sits in the fragment.** Everything after `#` stays in the browser
and is never sent to the server — so if the link is opened on a phone without
the app, the key does not travel to a web host, appear in its access log, or
sit in a proxy cache. The one place a secret can be put in a URL without
leaking it.

**A version number in front.** The payload will change; a code from an old
version has to be rejected rather than misread. It costs two characters.

## The key is a secret with a short life

Anyone who scans the code joins the device group and can see the usage totals
in it. That is what makes it useful and also what makes it worth handling
carefully:

  * The server issues it valid for five minutes (LinkNewResp).
  * It is single-use.
  * `LINK_DISPLAY_SECONDS` stops the PC displaying it past that, so a code
    left on screen while its owner goes to lunch is not still live.

None of that is a substitute for the obvious advice, which the UI gives: do
not photograph it, and do not put it in a screen share.
"""

import re
import secrets
import string
import time

from core.logging_setup import get_logger

log = get_logger("linking")

PAYLOAD_VERSION = 1

# The page a scan lands on when ProtBot is not installed. Nothing is sent
# there: the key is in the fragment, which never leaves the browser.
LINK_BASE_URL = "https://protbot.app/l"

# How long the PC keeps a code on screen. Deliberately a little under the
# server's five minutes, so the code stops being offered before it stops
# working and the user is not left staring at a key the server has forgotten.
LINK_DISPLAY_SECONDS = 4 * 60 + 30

# Uppercase letters and digits, minus the four characters people misread when
# they fall back to typing: O/0 and I/1. A shorter alphabet costs a little
# entropy and saves a support conversation.
KEY_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits
                       if c not in "OI01")
KEY_LENGTH = 8

_KEY_RE = re.compile(rf"^[{KEY_ALPHABET}]{{{KEY_LENGTH}}}$")
_PAYLOAD_RE = re.compile(r"^(\d+)\.([A-Z0-9]+)$")


class LinkError(Exception):
    """A link attempt that failed for a reason worth showing the user."""


def new_key() -> str:
    """
    A link key, for a server that has not been built yet.

    `secrets`, not `random`: this is a credential, and the difference between
    the two modules is the difference between a key an attacker cannot guess
    and one they can once they know roughly when it was issued.

    The real key comes from the server (LinkNewResp) so that it can enforce
    the expiry and the single use. This exists so the flow can be built and
    tested end to end before that endpoint is written, and so the UI has
    something to show.
    """
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))


def is_valid_key(key: str) -> bool:
    """Whether a string could be a link key at all, before any network call."""
    return bool(key) and bool(_KEY_RE.match(str(key).strip().upper()))


def build_payload(key: str, base_url: str = LINK_BASE_URL) -> str:
    """
    The text that goes in the QR code.

    Raises on an invalid key rather than encoding it: a QR containing a
    malformed key is worse than no QR, because it fails at the far end after
    the user has already done the work of scanning it.
    """
    key = str(key or "").strip().upper()
    if not is_valid_key(key):
        raise LinkError(f"{key!r} is not a valid link key")
    return f"{base_url}#{PAYLOAD_VERSION}.{key}"


def parse_payload(text: str) -> str:
    """
    The key from a scanned payload, or raise LinkError.

    Accepts the full URL, and also a bare key typed by hand — someone reading
    the characters off the screen is the fallback path and should not have to
    reproduce a URL to use it.
    """
    text = str(text or "").strip()
    if not text:
        raise LinkError("Nothing was scanned.")

    # A bare key, typed rather than scanned.
    if is_valid_key(text):
        return text.upper()

    if "#" not in text:
        raise LinkError("That code is not a ProtBot link code.")

    fragment = text.rsplit("#", 1)[1].strip().upper()
    match = _PAYLOAD_RE.match(fragment)
    if not match:
        raise LinkError("That code is not a ProtBot link code.")

    version = int(match.group(1))
    if version > PAYLOAD_VERSION:
        # Forwards, not backwards: a newer phone can produce a code this build
        # has never seen, and guessing at it would be worse than saying so.
        raise LinkError(
            "That code was made by a newer version of ProtBot. "
            "Update this device and try again."
        )
    if version < PAYLOAD_VERSION:
        raise LinkError("That code was made by an old version of ProtBot.")

    key = match.group(2)
    if not is_valid_key(key):
        raise LinkError("That link code is damaged. Ask for a new one.")
    return key


def seconds_remaining(issued_at: float, now=None,
                      lifetime: int = LINK_DISPLAY_SECONDS) -> int:
    """
    How long a displayed code is still good for.

    Clamped at both ends, and both ends matter. A clock that has jumped
    *forward* produces a negative remainder, which as a countdown would render
    as a growing number and look like the code is getting more valid. A clock
    that has jumped *backwards* produces a remainder larger than the lifetime,
    which would keep a code the server has already forgotten on screen
    indefinitely — the worse of the two, because it is the one that hands
    someone a key that cannot work.

    The only acceptable failure here is expiring early.
    """
    if not issued_at:
        return 0
    moment = now if isinstance(now, (int, float)) else time.time()
    return max(0, min(int(lifetime - (moment - issued_at)), int(lifetime)))


def is_expired(issued_at: float, now=None,
               lifetime: int = LINK_DISPLAY_SECONDS) -> bool:
    return seconds_remaining(issued_at, now, lifetime) <= 0


class LinkSession:
    """
    One attempt to link another device, on the PC side.

    Holds the key, when it was issued, and nothing else. Deliberately not
    persisted: a link code that survives a restart is a link code that outlives
    the moment the user was standing in front of both screens.
    """

    def __init__(self, key: str, issued_at=None) -> None:
        if not is_valid_key(key):
            raise LinkError(f"{key!r} is not a valid link key")
        self.key = key.upper()
        self.issued_at = float(issued_at if issued_at is not None else time.time())

    @property
    def payload(self) -> str:
        return build_payload(self.key)

    def seconds_left(self, now=None) -> int:
        return seconds_remaining(self.issued_at, now)

    def expired(self, now=None) -> bool:
        return is_expired(self.issued_at, now)

    def matrix(self, ecl: str = "Q"):
        """The QR matrix for this session's payload."""
        from core import qrcode

        return qrcode.encode(self.payload, ecl)

    def formatted_key(self) -> str:
        """The key in two groups, for the person reading it aloud."""
        half = KEY_LENGTH // 2
        return f"{self.key[:half]} {self.key[half:]}"


def request_link(config, transport=None) -> LinkSession:
    """
    Ask the server for a link key and start a session.

    The endpoint does not exist yet. When it is missing, or the device is not
    registered, this raises rather than inventing a key locally: a code that
    looks real and cannot possibly work would send the user to the phone to
    find out.
    """
    from core import syncclient

    device_id = str(config.get("device_id", "") or "").strip()
    if not device_id:
        raise LinkError(
            "Register this device for sync before linking another one."
        )

    transport = transport or syncclient.Transport(config.get("server_url", ""))
    response = transport.post("/link/new", {"d": device_id})
    if not isinstance(response, dict):
        raise LinkError("Could not reach the sync server. Check your connection.")

    key = str(response.get("k", "") or "").strip().upper()
    if not is_valid_key(key):
        raise LinkError("The server returned a link code that could not be read.")

    log.info("Link code issued.")
    return LinkSession(key)


def join_link(config, key: str, transport=None) -> str:
    """
    Join the group a link code belongs to. Returns the group id.

    The joining device sends its own id with the key (LinkJoinReq), so the
    server can put the two together.
    """
    from core import syncclient

    key = parse_payload(key)

    device_id = str(config.get("device_id", "") or "").strip()
    if not device_id:
        raise LinkError(
            "Register this device for sync before joining another device."
        )

    transport = transport or syncclient.Transport(config.get("server_url", ""))
    response = transport.post("/link/join", {"d": device_id, "k": key})
    if not isinstance(response, dict):
        raise LinkError("Could not reach the sync server. Check your connection.")

    if not response.get("ok"):
        raise LinkError("That link code has expired or has already been used.")

    group = str(response.get("grp", "") or "").strip()
    if not group:
        raise LinkError("The server did not say which group this device joined.")

    log.info("Device joined a sync group.")
    return group
