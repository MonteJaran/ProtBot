"""
db.py - Storage for the sync server.

Same shape as core/database.py: SQLite, one connection, one lock, thin
wrapper methods rather than an ORM — this file is small enough that an ORM
would be more code to read than it saves. The schema exists to satisfy
exactly the four notes in server/models.py's docstring; read that file
first, this one implements it.

## Devices, groups and apps

Every device gets its own `group_id` the moment it registers — initially a
freshly generated id containing just that device, so "solo" is not a
special case anywhere else in this file, just a group of one. Linking
another device in does not invent a second concept: it moves the joining
device's `group_id` to match the host's.

App identity (server/models.py note 3) is scoped to a group, not a device,
because the whole point is that two devices in one group share one row per
app. The awkward case is a device that already synced solo *before* it
linked: its already-assigned server_ids point at rows scoped to its old
solo group. `join_group()` below migrates them into the new group when
nothing there already claims the same canonical key, which is the common
case (most people link before they have both devices reporting the same
app under different ids) — see its docstring for the one case that is not
migrated, and why that is an accepted, documented gap rather than a bug.

## Usage storage and cumulative uploads

server/models.py note 1: an upload carries a running total, not a delta, so
storage is `max(stored, received)` per (device, server_app_id, date) — see
`record_usage()`. Note 2: the date is the client's own and is stored
verbatim, never recomputed from the server's clock.
"""

import os
import secrets
import sqlite3
import threading
import time

DB_FILENAME = "protbot_server.db"

_CREATE_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    token_hash  TEXT NOT NULL,
    name        TEXT,
    platform    TEXT,
    group_id    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    last_seen   REAL
);
"""

_CREATE_APPS = """
CREATE TABLE IF NOT EXISTS apps (
    server_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       TEXT NOT NULL,
    canonical_key  TEXT NOT NULL,
    category       TEXT,
    UNIQUE (group_id, canonical_key)
);
"""

_CREATE_USAGE = """
CREATE TABLE IF NOT EXISTS usage (
    device_id      TEXT NOT NULL,
    server_app_id  INTEGER NOT NULL,
    date           TEXT NOT NULL,
    seconds        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (device_id, server_app_id, date)
);
"""

_CREATE_LINK_KEYS = """
CREATE TABLE IF NOT EXISTS link_keys (
    key         TEXT PRIMARY KEY,
    group_id    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
"""

# license_keys is deliberately separate from anything Paddle-specific: this
# table is "what the server currently believes a key is worth", filled in
# by hand today (server/issue_license.py) and by a Paddle webhook once one
# is written — see STATUS.md item 11 and this table's own docstring below.
_CREATE_LICENSE_KEYS = """
CREATE TABLE IF NOT EXISTS license_keys (
    key         TEXT PRIMARY KEY,
    plan        TEXT NOT NULL,
    expires_at  REAL NOT NULL DEFAULT 0,
    issued_at   REAL NOT NULL
);
"""

_CREATE_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_devices_group ON devices(group_id);",
    "CREATE INDEX IF NOT EXISTS idx_usage_device ON usage(device_id);",
    "CREATE INDEX IF NOT EXISTS idx_usage_app ON usage(server_app_id);",
    "CREATE INDEX IF NOT EXISTS idx_apps_group ON apps(group_id);",
]

# A device's contribution to a group total only counts if its most recent
# upload for that app is within this many seconds — otherwise an offline
# device's last-known total would sit in every /sync response forever,
# quietly inflating a live device's limit for as long as the other one
# stayed off. Not specified in server/models.py; two days is deliberately
# generous rather than tight, so a real timezone difference (note 2: dates
# are the client's own, never rebucketed by the server) is never mistaken
# for staleness — this is about catching "offline for days", not
# "on the other side of the world".
GROUP_CONTRIBUTION_MAX_AGE_SEC = 2 * 24 * 60 * 60

LINK_KEY_LIFETIME_SEC = 5 * 60   # server/models.py: "valid 5 minutes"


def _row_to_dict(cursor, row):
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row, strict=True))


def new_device_id() -> str:
    """A 24-character device id — matches server/models.py's comment on
    RegisterResp.id. Not a credential (the token is); collision-resistant
    is all it needs to be."""
    return secrets.token_hex(12)


def new_token() -> str:
    """The bearer token returned once at registration. High-entropy: this,
    not the device id, is what proves a request (AUDIT SF-09)."""
    return secrets.token_urlsafe(32)


def new_group_id() -> str:
    return secrets.token_hex(12)


class ServerDatabase:
    def __init__(self, data_dir: str = "") -> None:
        self._dir = data_dir or "."
        os.makedirs(self._dir, exist_ok=True)
        self._db_path = os.path.join(self._dir, DB_FILENAME)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._create_tables()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _create_tables(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(_CREATE_DEVICES)
            self._conn.execute(_CREATE_APPS)
            self._conn.execute(_CREATE_USAGE)
            self._conn.execute(_CREATE_LINK_KEYS)
            self._conn.execute(_CREATE_LICENSE_KEYS)
            for statement in _CREATE_INDICES:
                self._conn.execute(statement)

    def _fetchone(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            return _row_to_dict(cur, row) if row else None

    def _fetchall(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            return [_row_to_dict(cur, r) for r in rows] if rows else []

    # ── Devices ──────────────────────────────────────────────────────────────

    def create_device(self, token_hash: str, name: str = "", platform: str = "") -> dict:
        """
        Register a new device. Returns {"id", "group_id"}.

        Every device is given its own fresh group at birth — see this
        module's docstring — so nothing downstream has to treat "not yet
        linked to anyone" as a null case.
        """
        device_id = new_device_id()
        group_id = new_group_id()
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO devices (id, token_hash, name, platform, group_id, created_at, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?);""",
                (device_id, token_hash, name or "", platform or "", group_id, now, now),
            )
        return {"id": device_id, "group_id": group_id}

    def get_device(self, device_id: str):
        return self._fetchone("SELECT * FROM devices WHERE id = ?;", (device_id,))

    def get_device_by_token_hash(self, token_hash: str):
        """For /group, the one endpoint with no device id anywhere in the
        request — see server/auth.py's require_device_by_token."""
        return self._fetchone("SELECT * FROM devices WHERE token_hash = ?;", (token_hash,))

    def touch_device(self, device_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE devices SET last_seen = ? WHERE id = ?;", (time.time(), device_id)
            )

    def group_members(self, group_id: str) -> list:
        return self._fetchall(
            "SELECT id, name, platform, last_seen FROM devices WHERE group_id = ? ORDER BY created_at;",
            (group_id,),
        )

    # ── App identity (server/models.py note 3) ──────────────────────────────

    def get_or_create_app(self, group_id: str, canonical_key: str, category: str = "") -> int:
        """The server_id for one app within one group, creating the row on
        first sight. Returns the same id every time this (group, key) pair
        is seen again — the whole point of note 3."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT server_id FROM apps WHERE group_id = ? AND canonical_key = ?;",
                (group_id, canonical_key),
            ).fetchone()
            if row:
                return int(row[0])
            cur = self._conn.execute(
                "INSERT INTO apps (group_id, canonical_key, category) VALUES (?, ?, ?);",
                (group_id, canonical_key, category or ""),
            )
            return int(cur.lastrowid)

    def app_group(self, server_id: int):
        row = self._fetchone("SELECT group_id FROM apps WHERE server_id = ?;", (server_id,))
        return row["group_id"] if row else None

    # ── Usage (server/models.py note 1: cumulative, max-merged) ─────────────

    def record_usage(self, device_id: str, server_app_id: int, date: str, seconds: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO usage (device_id, server_app_id, date, seconds)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (device_id, server_app_id, date)
                   DO UPDATE SET seconds = MAX(seconds, excluded.seconds);""",
                (device_id, server_app_id, date, max(0, int(seconds))),
            )

    def group_totals(self, group_id: str, requesting_device_id: str, now=None) -> dict:
        """
        {server_app_id: summed_seconds} across every device in the group —
        each device's own *most recent* row per app, and only if that row
        is recent enough (GROUP_CONTRIBUTION_MAX_AGE_SEC) to still count as
        current. See this module's docstring for why "most recent", not
        "today by the server's clock".

        Deliberately keyed by this group's own server_ids throughout — the
        requesting device already knows its own server_ids (it assigned
        them via /apps), so no translation happens here. What is not
        handled: a device whose apps are scoped to a *different* group
        because it has not synced since joining — see join_group().
        """
        moment = now if now is not None else time.time()
        cutoff = moment - GROUP_CONTRIBUTION_MAX_AGE_SEC

        rows = self._fetchall(
            """SELECT device_id, server_app_id, date, seconds
               FROM usage
               WHERE server_app_id IN (SELECT server_id FROM apps WHERE group_id = ?);""",
            (group_id,),
        )

        # Keep only each (device, app)'s most recent date, the same
        # "cumulative total for the freshest known day" reasoning as the
        # client's own local storage — a device only ever has one date's
        # total that matters: the last one it reported.
        latest = {}   # (device_id, server_app_id) -> (date, seconds)
        for row in rows:
            k = (row["device_id"], row["server_app_id"])
            if k not in latest or row["date"] > latest[k][0]:
                latest[k] = (row["date"], row["seconds"])

        # Age is checked by device (last_seen), after picking each device's
        # most-recent row, not per-row before it — a device that last
        # uploaded 10 days ago still has its most-recent row be that one; it
        # needs to be dropped for staleness, not kept because nothing newer
        # exists to replace it. last_seen is refreshed by the /upload
        # handler alongside every row it writes, so it tracks the same
        # freshness the rows themselves do.
        seen = {d["id"]: d["last_seen"] for d in self.group_members(group_id)}
        totals: dict = {}
        for (device_id, server_app_id), (_date, seconds) in latest.items():
            last_seen = seen.get(device_id) or 0
            if last_seen < cutoff:
                continue
            totals[server_app_id] = totals.get(server_app_id, 0) + seconds

        return totals

    # ── Linking ──────────────────────────────────────────────────────────────

    def create_link_key(self, group_id: str) -> str:
        key = _new_link_key()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO link_keys (key, group_id, created_at, used) VALUES (?, ?, ?, 0);",
                (key, group_id, time.time()),
            )
        return key

    def consume_link_key(self, key: str, now=None):
        """
        Redeem a link key: valid, unused, not expired. Returns the group_id
        it points to, or None. Marks it used in the same call — "single
        use" (server/models.py) means a key that fails validation here for
        any reason must not still be usable on a second attempt with the
        right code and worse luck.
        """
        moment = now if now is not None else time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT group_id, created_at, used FROM link_keys WHERE key = ?;", (key,)
            ).fetchone()
            if not row:
                return None
            group_id, created_at, used = row
            if used or (moment - created_at) > LINK_KEY_LIFETIME_SEC:
                return None
            self._conn.execute("UPDATE link_keys SET used = 1 WHERE key = ?;", (key,))
            return group_id

    def join_group(self, device_id: str, new_group_id: str) -> None:
        """
        Move `device_id` into `new_group_id`, carrying its existing app
        rows along where that does not collide with an app the new group
        already knows.

        The one case this does not fix: `device_id` and some other member
        of `new_group_id` had already synced the *same* app, under their
        own separate groups, before ever linking. Both rows exist and
        neither is deleted — `device_id`'s old row is simply not reachable
        through its new group_id any more, so that one app stops
        contributing to the shared total until `device_id` happens to
        re-sync it (removing and re-adding it, for instance). Narrow and
        pre-existing in spirit: this project already treats cross-device
        app matching as best-effort (core/syncproto.canonical_app_key's own
        docstring, and the Devices tab's manual "Match Apps…" override).
        """
        with self._lock, self._conn:
            old_group_row = self._conn.execute(
                "SELECT group_id FROM devices WHERE id = ?;", (device_id,)
            ).fetchone()
            if not old_group_row:
                return
            old_group_id = old_group_row[0]
            if old_group_id == new_group_id:
                return

            self._conn.execute(
                """UPDATE apps SET group_id = ?
                   WHERE group_id = ?
                     AND canonical_key NOT IN (
                         SELECT canonical_key FROM apps WHERE group_id = ?
                     );""",
                (new_group_id, old_group_id, new_group_id),
            )
            self._conn.execute(
                "UPDATE devices SET group_id = ? WHERE id = ?;", (new_group_id, device_id)
            )

    # ── Licensing (server/models.py is silent on this; see STATUS.md #10) ───

    def license_lookup(self, key: str):
        return self._fetchone(
            "SELECT plan, expires_at FROM license_keys WHERE key = ?;", (key,)
        )

    def license_issue(self, key: str, plan: str, expires_at: float = 0) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO license_keys (key, plan, expires_at, issued_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (key) DO UPDATE SET plan = excluded.plan,
                                                   expires_at = excluded.expires_at;""",
                (key, plan, float(expires_at or 0), time.time()),
            )


def _new_link_key() -> str:
    """
    Same alphabet and length as core/linking.py's KEY_ALPHABET/KEY_LENGTH —
    excludes O/0 and I/1, the characters people misread when they fall back
    to typing a code instead of scanning it. Duplicated rather than
    imported: the server has no dependency on the desktop client package,
    and an 8-character alphanumeric-minus-four-characters generator is a
    small enough rule to keep in sync by inspection.
    """
    alphabet = "".join(c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if c not in "OI01")
    return "".join(secrets.choice(alphabet) for _ in range(8))
