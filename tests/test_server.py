"""
The sync server (server/). Two layers, tested separately:

TestDatabase exercises server/db.py directly — the storage rules
server/models.py's four notes actually depend on (cumulative max-merge,
group-scoped app identity, staleness-filtered group totals, single-use
link keys) — the same way tests/test_database.py tests core/database.py
without going through a UI.

TestApi exercises the full HTTP contract through FastAPI's TestClient: no
real network, no real deployment, but every request and response shape a
real client would see, including the ones the audit specifically called
out (a token that does not match the device it claims — AUDIT SF-09 — and
the link-endpoint rate limit server/models.py note 4 names directly).

fastapi is not a runtime dependency of the desktop app (see
server/requirements.txt's own docstring on why it is kept separate from
requirements.txt/.lock), so a clone that only ever installed `.[dev]`
legitimately does not have it. The TestApi classes below skip in that case
— the same @needs_decoder / @needs_segno pattern tests/test_qrcode.py uses
for its own dev-only extras, and for the same reason: skipif marks
individual tests skipped without shrinking what gets *collected*, so
STATUS.md's test count stays accurate regardless of which optional extras
happen to be installed. server/db.py has no fastapi dependency at all, so
TestDatabase always runs.
"""

import time

import pytest

from server.db import ServerDatabase

try:
    from fastapi.testclient import TestClient
    from server import app as app_module
    _FASTAPI_AVAILABLE = True
except ImportError:                     # pragma: no cover - depends on the box
    TestClient = None
    app_module = None
    _FASTAPI_AVAILABLE = False

needs_fastapi = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi/httpx not installed; pip install -r server/requirements.txt to run these",
)


# ── server/db.py directly ───────────────────────────────────────────────────

@pytest.fixture
def sdb(tmp_path):
    database = ServerDatabase(str(tmp_path))
    yield database
    database.close()


class TestDatabase:

    def test_create_device_gets_its_own_group(self, sdb):
        a = sdb.create_device("hash-a")
        b = sdb.create_device("hash-b")
        assert a["group_id"] != b["group_id"]

    def test_devices_table_has_no_email_column(self, sdb):
        # server/models.py: "email — discarded immediately after response."
        # Belt and suspenders: there is no column to accidentally write it
        # into even if a future change tried.
        cols = {row[1] for row in sdb._conn.execute("PRAGMA table_info(devices);")}
        assert "email" not in cols
        assert "e" not in cols

    def test_get_or_create_app_is_idempotent_within_a_group(self, sdb):
        d = sdb.create_device("hash")
        first = sdb.get_or_create_app(d["group_id"], "discord", "Social")
        second = sdb.get_or_create_app(d["group_id"], "discord", "Social")
        assert first == second

    def test_get_or_create_app_is_scoped_per_group(self, sdb):
        g1 = sdb.create_device("hash1")["group_id"]
        g2 = sdb.create_device("hash2")["group_id"]
        id1 = sdb.get_or_create_app(g1, "discord", "Social")
        id2 = sdb.get_or_create_app(g2, "discord", "Social")
        assert id1 != id2

    def test_record_usage_takes_the_larger_value_a_retry_is_a_no_op(self, sdb):
        d = sdb.create_device("hash")
        app_id = sdb.get_or_create_app(d["group_id"], "discord")
        sdb.record_usage(d["id"], app_id, "2026-09-04", 600)
        sdb.record_usage(d["id"], app_id, "2026-09-04", 600)   # retry, same value
        sdb.record_usage(d["id"], app_id, "2026-09-04", 300)   # stale/out of order
        sdb.touch_device(d["id"])
        totals = sdb.group_totals(d["group_id"], d["id"])
        assert totals[app_id] == 600

    def test_record_usage_is_per_date(self, sdb):
        d = sdb.create_device("hash")
        app_id = sdb.get_or_create_app(d["group_id"], "discord")
        sdb.record_usage(d["id"], app_id, "2026-09-03", 500)
        sdb.record_usage(d["id"], app_id, "2026-09-04", 200)
        sdb.touch_device(d["id"])
        # group_totals uses each device's most recent date only.
        totals = sdb.group_totals(d["group_id"], d["id"])
        assert totals[app_id] == 200

    def test_group_totals_sums_across_devices_in_one_group(self, sdb):
        a = sdb.create_device("hash-a")
        b = sdb.create_device("hash-b")
        sdb.join_group(b["id"], a["group_id"])

        app_id = sdb.get_or_create_app(a["group_id"], "discord")
        sdb.record_usage(a["id"], app_id, "2026-09-04", 600)
        sdb.record_usage(b["id"], app_id, "2026-09-04", 900)
        sdb.touch_device(a["id"])
        sdb.touch_device(b["id"])

        totals = sdb.group_totals(a["group_id"], a["id"])
        assert totals[app_id] == 1500

    def test_group_totals_drops_a_device_that_has_gone_stale(self, sdb):
        a = sdb.create_device("hash-a")
        b = sdb.create_device("hash-b")
        sdb.join_group(b["id"], a["group_id"])

        app_id = sdb.get_or_create_app(a["group_id"], "discord")
        sdb.record_usage(a["id"], app_id, "2026-09-04", 600)
        sdb.record_usage(b["id"], app_id, "2026-09-04", 900)

        now = time.time()
        sdb.touch_device(a["id"])
        # b "last seen" a week ago — offline, not just quiet for a bit.
        with sdb._lock, sdb._conn:
            sdb._conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?;",
                              (now - 7 * 86400, b["id"]))

        totals = sdb.group_totals(a["group_id"], a["id"], now=now)
        assert totals[app_id] == 600, "b's stale contribution must not count"

    def test_group_totals_is_empty_for_an_unknown_group(self, sdb):
        assert sdb.group_totals("no-such-group", "x") == {}

    def test_link_key_round_trip(self, sdb):
        d = sdb.create_device("hash")
        key = sdb.create_link_key(d["group_id"])
        assert len(key) == 8
        assert sdb.consume_link_key(key) == d["group_id"]

    def test_link_key_is_single_use(self, sdb):
        d = sdb.create_device("hash")
        key = sdb.create_link_key(d["group_id"])
        sdb.consume_link_key(key)
        assert sdb.consume_link_key(key) is None

    def test_link_key_expires_after_five_minutes(self, sdb):
        d = sdb.create_device("hash")
        key = sdb.create_link_key(d["group_id"])
        now = time.time()
        assert sdb.consume_link_key(key, now=now + 4 * 60) == d["group_id"]

    def test_expired_link_key_round_trip(self, sdb):
        d = sdb.create_device("hash")
        key = sdb.create_link_key(d["group_id"])
        now = time.time()
        assert sdb.consume_link_key(key, now=now + 6 * 60) is None

    def test_unknown_link_key_returns_none(self, sdb):
        assert sdb.consume_link_key("NOPE0000") is None

    def test_join_group_migrates_apps_with_no_conflict(self, sdb):
        a = sdb.create_device("hash-a")
        b = sdb.create_device("hash-b")
        # b already tracks 'code' solo, before ever linking.
        code_id = sdb.get_or_create_app(b["group_id"], "code")

        sdb.join_group(b["id"], a["group_id"])

        # The same server id is still reachable, now under a's group.
        assert sdb.get_or_create_app(a["group_id"], "code") == code_id

    def test_join_group_does_not_clobber_an_existing_app_in_the_target(self, sdb):
        a = sdb.create_device("hash-a")
        b = sdb.create_device("hash-b")
        a_discord = sdb.get_or_create_app(a["group_id"], "discord")
        b_discord = sdb.get_or_create_app(b["group_id"], "discord")
        assert a_discord != b_discord

        sdb.join_group(b["id"], a["group_id"])

        # a's row wins for the shared key; a fresh lookup in a's group
        # returns a's id, not b's orphaned one.
        assert sdb.get_or_create_app(a["group_id"], "discord") == a_discord

    def test_join_group_updates_the_devices_own_row(self, sdb):
        a = sdb.create_device("hash-a")
        b = sdb.create_device("hash-b")
        sdb.join_group(b["id"], a["group_id"])
        assert sdb.get_device(b["id"])["group_id"] == a["group_id"]

    def test_license_issue_and_lookup(self, sdb):
        sdb.license_issue("KEY1", "premium", expires_at=123.0)
        row = sdb.license_lookup("KEY1")
        assert row == {"plan": "premium", "expires_at": 123.0}

    def test_license_issue_overwrites_on_reissue(self, sdb):
        sdb.license_issue("KEY1", "premium", expires_at=100.0)
        sdb.license_issue("KEY1", "free", expires_at=0)
        row = sdb.license_lookup("KEY1")
        assert row["plan"] == "free"

    def test_license_lookup_unknown_key_is_none(self, sdb):
        assert sdb.license_lookup("NOPE") is None


# ── The full HTTP API ────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    fresh_db = ServerDatabase(str(tmp_path))
    monkeypatch.setattr(app_module, "database", fresh_db)
    # Fresh limiter state per test too, so one test's rate-limit hits do not
    # bleed into the next (the limiter is otherwise a module-level singleton).
    from server.ratelimit import RateLimiter
    monkeypatch.setattr(app_module, "_link_new_limiter", RateLimiter(10, 60))
    monkeypatch.setattr(app_module, "_link_join_limiter", RateLimiter(20, 60))
    return TestClient(app_module.app)


def _register(client, name="Device", platform="Windows", email=None):
    body = {"n": name, "p": platform}
    if email:
        body["e"] = email
    r = client.post("/register", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@needs_fastapi
class TestRegister:

    def test_returns_an_id_and_a_token(self, client):
        d = _register(client)
        assert len(d["id"]) == 24
        assert len(d["tok"]) > 20

    def test_two_registrations_get_different_ids_and_tokens(self, client):
        a = _register(client)
        b = _register(client)
        assert a["id"] != b["id"]
        assert a["tok"] != b["tok"]

    def test_email_is_accepted_but_not_echoed_back(self, client):
        d = _register(client, email="user@example.com")
        assert "e" not in d
        assert "email" not in d


@needs_fastapi
class TestAuth:

    def test_missing_token_is_rejected(self, client):
        d = _register(client)
        r = client.post("/apps", json={"d": d["id"], "a": []})
        assert r.status_code == 401

    def test_wrong_token_is_rejected(self, client):
        d = _register(client)
        r = client.post("/apps", json={"d": d["id"], "a": []}, headers=_auth("not-the-real-token"))
        assert r.status_code == 401

    def test_a_token_does_not_authenticate_a_different_device(self, client):
        a = _register(client)
        b = _register(client)
        r = client.post("/apps", json={"d": b["id"], "a": []}, headers=_auth(a["tok"]))
        assert r.status_code == 401

    def test_unknown_device_id_is_rejected(self, client):
        r = client.post("/apps", json={"d": "x" * 24, "a": []}, headers=_auth("whatever"))
        assert r.status_code == 401


@needs_fastapi
class TestAppsAndUpload:

    def test_apps_assigns_ids_and_upload_stores_usage(self, client):
        d = _register(client)
        r = client.post("/apps", json={"d": d["id"], "a": [[1, "discord", "Social"]]},
                        headers=_auth(d["tok"]))
        server_id = r.json()["m"]["1"]

        r = client.post("/upload", json={"d": d["id"], "t": 1, "z": "2026-09-04",
                                         "a": [[server_id, 600]]},
                        headers=_auth(d["tok"]))
        assert r.json() == {"ok": 1}

        r = client.post("/sync", json={"d": d["id"]}, headers=_auth(d["tok"]))
        assert r.json()["apps"][str(server_id)] == 600

    def test_upload_to_another_groups_app_id_is_silently_ignored(self, client):
        a = _register(client)
        b = _register(client)
        r = client.post("/apps", json={"d": a["id"], "a": [[1, "discord", "Social"]]},
                        headers=_auth(a["tok"]))
        a_app_id = r.json()["m"]["1"]

        # b has never seen this app id — it belongs to a's group.
        r = client.post("/upload", json={"d": b["id"], "t": 1, "z": "2026-09-04",
                                         "a": [[a_app_id, 999]]},
                        headers=_auth(b["tok"]))
        assert r.status_code == 200   # not an error — just nothing written

        r = client.post("/sync", json={"d": a["id"]}, headers=_auth(a["tok"]))
        assert r.json()["apps"].get(str(a_app_id), 0) == 0

    def test_negative_or_zero_seconds_are_dropped(self, client):
        d = _register(client)
        r = client.post("/apps", json={"d": d["id"], "a": [[1, "discord", "Social"]]},
                        headers=_auth(d["tok"]))
        server_id = r.json()["m"]["1"]

        client.post("/upload", json={"d": d["id"], "t": 1, "z": "2026-09-04",
                                     "a": [[server_id, -50], [server_id, 0]]},
                    headers=_auth(d["tok"]))
        r = client.post("/sync", json={"d": d["id"]}, headers=_auth(d["tok"]))
        assert r.json()["apps"].get(str(server_id), 0) == 0


@needs_fastapi
class TestSyncEndToEnd:

    def test_solo_device_sees_only_its_own_total(self, client):
        d = _register(client)
        r = client.post("/apps", json={"d": d["id"], "a": [[1, "discord", "Social"]]},
                        headers=_auth(d["tok"]))
        server_id = r.json()["m"]["1"]
        client.post("/upload", json={"d": d["id"], "t": 1, "z": "2026-09-04",
                                     "a": [[server_id, 300]]},
                    headers=_auth(d["tok"]))
        r = client.post("/sync", json={"d": d["id"]}, headers=_auth(d["tok"]))
        assert r.json() == {"apps": {str(server_id): 300}, "devices": 1}

    def test_linking_and_merging_two_devices(self, client):
        a = _register(client, name="PC")
        b = _register(client, name="Phone")

        r = client.post("/apps", json={"d": a["id"], "a": [[1, "discord", "Social"]]},
                        headers=_auth(a["tok"]))
        a_server_id = r.json()["m"]["1"]
        client.post("/upload", json={"d": a["id"], "t": 1, "z": "2026-09-04",
                                     "a": [[a_server_id, 600]]},
                    headers=_auth(a["tok"]))

        r = client.post("/link/new", json={"d": a["id"]}, headers=_auth(a["tok"]))
        key = r.json()["k"]

        r = client.post("/link/join", json={"d": b["id"], "k": key}, headers=_auth(b["tok"]))
        assert r.json()["ok"] == 1

        r = client.post("/apps", json={"d": b["id"], "a": [[7, "discord", "Social"]]},
                        headers=_auth(b["tok"]))
        b_server_id = r.json()["m"]["7"]
        assert b_server_id == a_server_id, "same app, one id, across the group"

        client.post("/upload", json={"d": b["id"], "t": 1, "z": "2026-09-04",
                                     "a": [[b_server_id, 400]]},
                    headers=_auth(b["tok"]))

        r = client.post("/sync", json={"d": a["id"]}, headers=_auth(a["tok"]))
        body = r.json()
        assert body["apps"][str(a_server_id)] == 1000
        assert body["devices"] == 2

    def test_a_link_key_cannot_be_reused(self, client):
        a = _register(client)
        b = _register(client)
        c = _register(client)

        key = client.post("/link/new", json={"d": a["id"]}, headers=_auth(a["tok"])).json()["k"]
        first = client.post("/link/join", json={"d": b["id"], "k": key}, headers=_auth(b["tok"]))
        second = client.post("/link/join", json={"d": c["id"], "k": key}, headers=_auth(c["tok"]))

        assert first.json()["ok"] == 1
        assert second.json()["ok"] == 0

    def test_an_invalid_link_key_is_rejected_not_a_server_error(self, client):
        d = _register(client)
        r = client.post("/link/join", json={"d": d["id"], "k": "NOPE0000"},
                        headers=_auth(d["tok"]))
        assert r.status_code == 200
        assert r.json()["ok"] == 0


@needs_fastapi
class TestGroupList:

    def test_group_lists_every_member_with_correct_is_own(self, client):
        a = _register(client, name="PC")
        b = _register(client, name="Phone")
        key = client.post("/link/new", json={"d": a["id"]}, headers=_auth(a["tok"])).json()["k"]
        client.post("/link/join", json={"d": b["id"], "k": key}, headers=_auth(b["tok"]))

        r = client.post("/group", json={}, headers=_auth(a["tok"]))
        devices = {row["id"]: row["isOwn"] for row in r.json()["devices"]}
        assert devices == {a["id"]: True, b["id"]: False}

    def test_group_needs_no_device_id_in_the_body(self, client):
        d = _register(client)
        r = client.post("/group", json={}, headers=_auth(d["tok"]))
        assert r.status_code == 200
        assert len(r.json()["devices"]) == 1

    def test_group_with_no_token_is_rejected(self, client):
        r = client.post("/group", json={})
        assert r.status_code == 401


@needs_fastapi
class TestLicenseVerify:

    def test_unknown_key_is_404(self, client):
        r = client.post("/license/verify", json={"k": "NOPE", "d": ""})
        assert r.status_code == 404

    def test_a_valid_premium_key(self, client):
        app_module.database.license_issue("GOODKEY", "premium", expires_at=0)
        r = client.post("/license/verify", json={"k": "GOODKEY", "d": ""})
        assert r.status_code == 200
        assert r.json() == {"plan": "premium", "expires_at": 0}

    def test_an_expired_premium_key_is_410(self, client):
        app_module.database.license_issue("OLDKEY", "premium", expires_at=1.0)
        r = client.post("/license/verify", json={"k": "OLDKEY", "d": ""})
        assert r.status_code == 410

    def test_no_device_id_is_accepted(self, client):
        # core/licensing.py's activate() can be called before a device is
        # ever registered for sync — the key alone is the credential.
        app_module.database.license_issue("SOLOKEY", "premium", expires_at=0)
        r = client.post("/license/verify", json={"k": "SOLOKEY"})
        assert r.status_code == 200


@needs_fastapi
class TestRateLimiting:

    def test_link_new_is_rate_limited(self, client):
        d = _register(client)
        codes = []
        for _ in range(15):
            r = client.post("/link/new", json={"d": d["id"]}, headers=_auth(d["tok"]))
            codes.append(r.status_code)
        assert 429 in codes
        assert codes.count(200) <= 10

    def test_link_join_is_rate_limited_independently_of_link_new(self, client):
        d = _register(client)
        codes = []
        for _ in range(25):
            r = client.post("/link/join", json={"d": d["id"], "k": "NOPE0000"},
                            headers=_auth(d["tok"]))
            codes.append(r.status_code)
        assert 429 in codes
