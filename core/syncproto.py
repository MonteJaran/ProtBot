"""
syncproto.py - The cross-device sync protocol, as pure functions.

This is the half of sync that has no network in it: building an upload
payload, reading a response, matching an app on one device to the same app on
another, and combining the totals. It is separated from the transport
(core/syncclient.py) for the same reason core/activity.py is separated from the
monitor — the rules are where the bugs are, and rules can be tested without a
server, a socket, or a phone.

The wire format is defined in server/models.py and shared with the Android app
(android/core/.../Sync.kt), which carries the same three rules below and the
same test cases.

Three decisions worth reading before changing anything here.

1. Uploads are cumulative, not deltas.

   The obvious design uploads "seconds used since the last upload". It is also
   wrong: if the response is lost on the way back, the client retries and the
   server counts the same minutes twice. There is no acknowledgement scheme
   that fixes this without becoming a transaction log.

   So an upload carries today's *running total* for each app. Re-sending it
   changes nothing, out-of-order arrivals settle to the same value, and a
   client that was offline for six hours catches up in one request instead of
   twelve.

2. The day is the client's day, not the server's.

   The user's limit resets at their midnight. A server bucketing by its own
   UTC date puts a Belgrade evening into the next day, and the user watches
   their limit reset at 2am. The upload therefore carries the local date and
   the server stores it verbatim.

3. Merging is not "take the bigger number".

   The group total the server returns includes this device's own last upload,
   which is by definition stale — this device has kept using the app since.
   Taking the maximum of local and group throws away the other devices'
   minutes for as long as the upload interval. Subtracting our own contribution
   first and adding the remainder to the live local figure is exact:

       others = group_total - what_we_last_uploaded
       merged = local_total + max(0, others)

   See merge_app_total().
"""

import re
from datetime import date, datetime

# Uploads carry today's running total, so this interval trades freshness on the
# other device against request count. Missing one is harmless; the next upload
# is a full snapshot, not a gap.
UPLOAD_INTERVAL_SEC = 30 * 60

# A group total older than this is not applied. If the network has been down
# for an hour, the other device's figure is a guess, and quietly enforcing a
# limit against a guess is worse than enforcing it against local usage only.
REMOTE_STALE_AFTER_SEC = 2 * 60 * 60

# Refuse absurd values rather than trusting the server. A day holds 86400
# seconds; anything past that is a bug or a hostile response, and either way
# must not be able to instantly exhaust a user's limit.
MAX_PLAUSIBLE_DAILY_SEC = 24 * 60 * 60

_EXE_SUFFIX = re.compile(r"\.(exe|app|apk)$", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Package prefixes carry no product identity: com.<vendor>.android.<product>
# and <product> are the same thing to a user with a limit on it.
_PACKAGE_PREFIXES = frozenset({
    "com", "org", "net", "io", "app", "co", "me", "tv", "dev",
})

# Platform segments. Their position in a package tells you where the product
# name is: com.<vendor>.android.<product> puts it after, com.<product>.android
# puts it before.
_PLATFORM_SEGMENTS = frozenset({"android", "ios", "mobile", "desktop", "windows"})

# Generic product-type words. Deliberately no brand names here: a list of those
# would need constant maintenance, and core/apps_list.py is the one file in
# this project that carries them.
_GENERIC_SEGMENTS = frozenset({"app", "apps", "client", "music", "messenger"})

# Words vendors append that the same product does not carry on the other
# platform. "<Product>.exe" and "<Product> for Android" must land on one key.
_NOISE_WORDS = frozenset({
    "for", "android", "ios", "mobile", "desktop", "app", "beta", "free",
    "lite", "pro", "plus", "premium", "the", "inc", "llc", "ltd",
    "windows", "pc", "x64", "x86", "32bit", "64bit",
})


def _product_segment(package: str) -> str:
    """
    The segment of a package name that identifies the product.

    Not simply the last one. Android packages come in two shapes and taking
    either end blindly gets half of them wrong:

        com.<product>.android           product first, platform last
        com.<vendor>.android.<product>  vendor first, product after the platform

    So the platform segment is used as the marker it is. When one appears with
    something after it, the product is what follows; when it trails, the
    product is what came before. Generic type words ("music", "messenger") are
    dropped either way, which is what makes com.<product>.music meet
    <Product>.exe on the desktop.

    Falls back to the first segment whenever the rules leave nothing, because
    returning "" here would silently drop the app from sync.
    """
    segments = [s for s in package.split(".") if s]
    if not segments:
        return package

    if len(segments) > 1 and segments[0] in _PACKAGE_PREFIXES:
        segments = segments[1:]

    for index, segment in enumerate(segments):
        if segment in _PLATFORM_SEGMENTS and index + 1 < len(segments):
            segments = segments[index + 1:]
            break

    meaningful = [s for s in segments
                  if s not in _PLATFORM_SEGMENTS and s not in _GENERIC_SEGMENTS]
    return (meaningful or segments)[0]


def canonical_app_key(name: str) -> str:
    """
    A stable identity for one app across platforms.

    The desktop knows apps by executable ("<Product>.exe"); Android knows them
    by package ("com.<product>") and label ("<Product>"). Sync joins them on the
    result of this function, so the two implementations — here and in
    Sync.kt — have to agree exactly. They are held to the same test cases.

    This is a best-effort join, and it is worth being plain about that: no
    string rule reliably resolves a package named after its vendor rather than
    its product without a list of brand names to consult. It gets the common
    shapes right, and where it does not, the answer is the user linking the two
    apps by hand — not a cleverer regex. See STATUS.md.

    Returns "" for anything with no usable content, which callers must treat as
    "do not sync this app" rather than as a key: an empty key would collide
    every unnameable app onto one row.
    """
    if not name:
        return ""

    text = str(name).strip().lower()
    if not text:
        return ""

    if "." in text and " " not in text and not _EXE_SUFFIX.search(text):
        text = _product_segment(text)

    text = _EXE_SUFFIX.sub("", text)
    words = [w for w in _NON_ALNUM.split(text) if w]
    kept = [w for w in words if w not in _NOISE_WORDS]

    # If every word was noise the name was noise-only ("app", "for windows").
    # Fall back to the unfiltered words rather than returning "", which would
    # merge it with every other such app.
    return "".join(kept or words)


def local_date(now=None) -> str:
    """Today, in the user's timezone, as the server stores it."""
    if now is None:
        return date.today().isoformat()
    if isinstance(now, datetime):
        return now.date().isoformat()
    return now.isoformat()


def build_upload(device_id: str, totals: dict, now=None) -> dict:
    """
    An upload request: today's running total for every app with usage.

    `totals` maps server app id to seconds used today. Apps with no usage are
    dropped — sending zeroes doubles the payload to say nothing — and so are
    negative or unusable values, which can only come from a corrupt row.

    Returns {} when there is nothing to send, so callers can skip the request
    entirely instead of posting an empty list.
    """
    if not device_id:
        return {}

    entries = []
    for app_id, seconds in (totals or {}).items():
        try:
            app_id = int(app_id)
            seconds = int(seconds)
        except (TypeError, ValueError):
            continue
        if app_id <= 0 or seconds <= 0:
            continue
        entries.append([app_id, min(seconds, MAX_PLAUSIBLE_DAILY_SEC)])

    if not entries:
        return {}

    entries.sort()   # deterministic payloads make request logs comparable
    moment = now if isinstance(now, datetime) else datetime.now()
    return {
        "d": device_id,
        "t": int(moment.timestamp()),
        "z": local_date(moment),
        "a": entries,
    }


def build_app_sync(device_id: str, apps, overrides: dict = None) -> dict:
    """
    The app-list request that gets local database ids mapped to server ids.

    Each app contributes [local_id, canonical_key, category]. The canonical key
    goes on the wire rather than the display name, because the server's job is
    to put the same product from two devices in one row and it cannot do that
    if one device says "<Product>.exe" and the other says "com.<product>".

    `overrides` is {local_id: key}, already-normalised keys a user typed by
    hand (core/syncclient.py's set_manual_key — see STATUS.md: this function
    cannot always guess right, and the fix for when it does not is letting
    someone say so, not a cleverer regex). An override wins over the
    computed key outright rather than merely being a tie-breaker, which is
    the whole point of it existing.
    """
    if not device_id:
        return {}

    overrides = overrides or {}
    entries = []
    for app in apps or ():
        try:
            local_id = int(app.get("id", 0))
        except (TypeError, ValueError):
            continue
        override_key = str(overrides.get(local_id) or overrides.get(str(local_id)) or "").strip()
        key = override_key or canonical_app_key(app.get("name", "") or app.get("exe_name", ""))
        if local_id <= 0 or not key:
            continue
        entries.append([local_id, key, str(app.get("category", "") or "")])

    if not entries:
        return {}

    entries.sort()
    return {"d": device_id, "a": entries}


def parse_app_map(payload) -> dict:
    """
    The {local_id: server_id} mapping from an app-sync response.

    Everything here came off the network, so nothing is assumed about it. A
    malformed entry is skipped rather than raising: one bad row must not cost
    the mapping for every other app.
    """
    if not isinstance(payload, dict):
        return {}

    raw = payload.get("m")
    if not isinstance(raw, dict):
        return {}

    mapping = {}
    for local_id, server_id in raw.items():
        try:
            local_id = int(local_id)
            server_id = int(server_id)
        except (TypeError, ValueError):
            continue
        if local_id > 0 and server_id > 0:
            mapping[local_id] = server_id
    return mapping


def parse_sync(payload) -> dict:
    """
    Group totals from a sync response: {server_app_id: seconds_today}.

    Same posture as parse_app_map — hostile input, skip what does not parse.
    Values are clamped to a day, so a server bug cannot hand back a number that
    instantly exhausts every limit the user has.
    """
    if not isinstance(payload, dict):
        return {}

    raw = payload.get("apps")
    if not isinstance(raw, dict):
        return {}

    totals = {}
    for app_id, seconds in raw.items():
        try:
            app_id = int(app_id)
            seconds = int(seconds)
        except (TypeError, ValueError):
            continue
        if app_id <= 0 or seconds < 0:
            continue
        totals[app_id] = min(seconds, MAX_PLAUSIBLE_DAILY_SEC)
    return totals


def parse_device_count(payload) -> int:
    """How many devices are in the group, or 0 if the response did not say."""
    if not isinstance(payload, dict):
        return 0
    try:
        return max(0, int(payload.get("devices", 0)))
    except (TypeError, ValueError):
        return 0


def merge_app_total(local_sec: int, group_sec: int, uploaded_sec: int) -> int:
    """
    This app's usage across every linked device, for the limit check.

    `group_sec` is the server's figure for all devices including this one, but
    it only knows about this device up to `uploaded_sec` — our last upload. So
    our stale contribution is removed and the live local figure used instead:

        others = group_sec - uploaded_sec      (the other devices' minutes)
        merged = local_sec + max(0, others)

    The clamp matters. `others` goes negative whenever our latest upload has
    not been ingested yet, and also right after midnight, when this device has
    rolled over to a new day and the server still holds yesterday's group
    total. Negative would mean subtracting minutes the user really did spend.

    The result is never below `local_sec`: sync can only ever add usage. A
    server that is wrong, empty, or hostile cannot talk a limit into being
    looser than what this device measured itself.
    """
    local = max(0, int(local_sec or 0))
    group = max(0, int(group_sec or 0))
    uploaded = max(0, int(uploaded_sec or 0))
    others = max(0, group - uploaded)
    return min(local + others, MAX_PLAUSIBLE_DAILY_SEC)


def merge_totals(local: dict, group: dict, uploaded: dict) -> dict:
    """
    merge_app_total over every app, keyed by server app id.

    Apps present only in the group total are included: another device may be
    using an app this one has never opened today, and that time still counts
    against a shared limit.
    """
    local = local or {}
    group = group or {}
    uploaded = uploaded or {}

    merged = {}
    for app_id in set(local) | set(group):
        merged[app_id] = merge_app_total(
            local.get(app_id, 0), group.get(app_id, 0), uploaded.get(app_id, 0),
        )
    return merged


def is_fresh(fetched_at, now=None, max_age_sec: int = REMOTE_STALE_AFTER_SEC) -> bool:
    """
    Whether a group total is recent enough to enforce a limit against.

    A missing timestamp is not fresh. A timestamp in the future is not fresh
    either — that is a clock problem, and trusting it would keep a stale figure
    alive indefinitely.
    """
    if not fetched_at:
        return False
    try:
        fetched = float(fetched_at)
    except (TypeError, ValueError):
        return False

    moment = now if isinstance(now, (int, float)) else (now or datetime.now()).timestamp()
    age = moment - fetched
    return 0 <= age <= max_age_sec
