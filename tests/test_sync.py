"""
Cross-device sync: the protocol rules and the client's behaviour.

Two halves, matching the code:

  * `syncproto` is pure, so it is tested directly — canonical keys, payload
    building, hostile response parsing, and the merge rule.
  * `syncclient` is tested against a fake transport. That is the only way to
    exercise a lost response, a 500, an HTML error page, or a server returning
    valid JSON with the wrong types, and those are exactly the cases where a
    sync client silently corrupts someone's totals.

The canonical-key cases here are duplicated in
`android/core/src/test/kotlin/app/protbot/core/SyncTest.kt`. They have to
agree: the key is the only thing joining "Discord.exe" on the PC to
"com.discord" on the phone, and if the two implementations disagree the user
gets two half-counted apps and no error anywhere.
"""

import json
import time
import urllib.request
from datetime import datetime

import pytest

from core import syncclient, syncproto
from core.syncclient import SyncClient


# ── Canonical app keys ────────────────────────────────────────────────────

class TestCanonicalAppKey:
    """The join between one product's names on two platforms."""

    @pytest.mark.parametrize("name,expected", [
        ("Discord.exe", "discord"),
        ("Discord", "discord"),
        ("com.discord", "discord"),
        ("DISCORD.EXE", "discord"),
        ("  Discord  ", "discord"),
    ])
    def test_one_product_one_key(self, name, expected):
        assert syncproto.canonical_app_key(name) == expected

    @pytest.mark.parametrize("package,expected", [
        # Product first, platform last.
        ("com.instagram.android", "instagram"),
        ("com.whatsapp", "whatsapp"),
        # Vendor first, product after the platform segment.
        ("com.google.android.youtube", "youtube"),
        ("com.android.chrome", "chrome"),
        # A generic type word is not the product.
        ("com.spotify.music", "spotify"),
        ("org.telegram.messenger", "telegram"),
    ])
    def test_a_package_reduces_to_its_product(self, package, expected):
        # Both Android package shapes. Taking the last segment blindly gets
        # com.instagram.android wrong; taking the first gets youtube wrong.
        assert syncproto.canonical_app_key(package) == expected

    def test_desktop_and_android_names_meet(self):
        # The whole point: these pairs must land on the same row.
        for desktop, android in [
            ("Spotify.exe", "com.spotify.music"),
            ("Telegram", "org.telegram.messenger"),
            ("Chrome.exe", "com.android.chrome"),
            ("Instagram", "com.instagram.android"),
            ("Telegram", "Telegram for Android"),
        ]:
            assert syncproto.canonical_app_key(desktop) == \
                syncproto.canonical_app_key(android), f"{desktop} != {android}"

    def test_the_join_is_best_effort_and_says_so(self):
        # A vendor-named package no string rule can resolve without a brand
        # list. Documented rather than papered over: the user links these two
        # by hand. If a future change makes this pass, update the docs with it.
        assert (syncproto.canonical_app_key("Firefox.exe")
                != syncproto.canonical_app_key("org.mozilla.firefox"))

    def test_punctuation_and_spacing_do_not_split_an_app(self):
        for name in ["VS Code", "vs-code", "VS_Code", "vscode"]:
            assert syncproto.canonical_app_key(name) == "vscode"

    def test_unusable_names_produce_no_key(self):
        # An empty key must not be used as one: it would collide every
        # unnameable app onto a single row.
        for name in ["", "   ", None, "!!!", "---"]:
            assert syncproto.canonical_app_key(name) == ""

    def test_a_name_of_nothing_but_noise_words_keeps_them(self):
        # "Free App" is a poor name, but merging it with every other poor name
        # is worse than keeping it distinct.
        assert syncproto.canonical_app_key("Free App") == "freeapp"

    def test_distinct_apps_stay_distinct(self):
        keys = {syncproto.canonical_app_key(n) for n in
                ["Discord", "Slack", "Telegram", "Signal", "WhatsApp"]}
        assert len(keys) == 5


# ── The merge rule ────────────────────────────────────────────────────────

class TestMergeAppTotal:
    """
    The reason sync exists: one limit counting two devices.

    Every case here is a way the naive "take the larger number" gets it wrong.
    """

    def test_the_other_devices_time_is_added_to_local(self):
        # We uploaded 600s. The group says 1500s, so the other device did 900s.
        # We have since reached 700s locally.
        assert syncproto.merge_app_total(700, 1500, 600) == 1600

    def test_taking_the_maximum_would_lose_time(self):
        # max(700, 1500) is 1500 — 100 seconds of our own usage dropped,
        # because the group figure predates it.
        assert syncproto.merge_app_total(700, 1500, 600) > 1500

    def test_our_own_upload_is_not_counted_twice(self):
        # Nobody else used it: the group is entirely our own last upload.
        assert syncproto.merge_app_total(600, 600, 600) == 600

    def test_an_uningested_upload_does_not_subtract_real_time(self):
        # We uploaded 900s but the server has not stored it yet, so the group
        # still reads 0. `others` is negative and must clamp to 0, not remove
        # minutes the user really spent.
        assert syncproto.merge_app_total(900, 0, 900) == 900

    def test_after_midnight_yesterdays_group_total_cannot_bleed_through(self):
        # Local has rolled over to a new day (0s). The server still holds
        # yesterday's group total, and our recorded upload with it.
        assert syncproto.merge_app_total(0, 7200, 7200) == 0

    def test_sync_can_only_ever_add_usage(self):
        # No response of any shape may produce less than local usage — a
        # server that is empty, wrong or hostile must not loosen a limit.
        for group, uploaded in [(0, 0), (0, 5000), (10, 9999), (-5, 0)]:
            assert syncproto.merge_app_total(1200, group, uploaded) >= 1200

    def test_an_absurd_group_total_is_clamped_to_a_day(self):
        # Otherwise one bad row instantly exhausts every limit the user has.
        assert syncproto.merge_app_total(0, 10 ** 9, 0) == syncproto.MAX_PLAUSIBLE_DAILY_SEC

    def test_negatives_never_reach_the_arithmetic(self):
        assert syncproto.merge_app_total(-100, -100, -100) == 0

    def test_merge_totals_includes_apps_only_the_other_device_used(self):
        merged = syncproto.merge_totals(
            local={1: 600},
            group={1: 600, 2: 1800},
            uploaded={1: 600},
        )
        assert merged == {1: 600, 2: 1800}


# ── Freshness ─────────────────────────────────────────────────────────────

class TestFreshness:

    def test_a_recent_figure_is_fresh(self):
        now = time.time()
        assert syncproto.is_fresh(now - 60, now)

    def test_an_old_figure_is_not_enforced_against(self):
        now = time.time()
        assert not syncproto.is_fresh(now - syncproto.REMOTE_STALE_AFTER_SEC - 1, now)

    def test_never_synced_is_not_fresh(self):
        assert not syncproto.is_fresh(0)
        assert not syncproto.is_fresh(None)

    def test_a_future_timestamp_is_not_fresh(self):
        # A clock problem. Trusting it would keep a stale figure alive forever.
        now = time.time()
        assert not syncproto.is_fresh(now + 3600, now)


# ── Payloads ──────────────────────────────────────────────────────────────

class TestBuildUpload:

    def test_an_upload_carries_the_running_total_and_the_local_date(self):
        moment = datetime(2026, 6, 15, 22, 30)
        payload = syncproto.build_upload("dev123", {7: 1800, 9: 270}, now=moment)

        assert payload["d"] == "dev123"
        assert payload["z"] == "2026-06-15"
        assert payload["a"] == [[7, 1800], [9, 270]]

    def test_apps_with_no_usage_are_not_sent(self):
        payload = syncproto.build_upload("dev123", {7: 1800, 9: 0, 11: -5})
        assert payload["a"] == [[7, 1800]]

    def test_nothing_to_send_produces_no_request(self):
        # So the caller skips the request rather than posting an empty list.
        assert syncproto.build_upload("dev123", {}) == {}
        assert syncproto.build_upload("dev123", {7: 0}) == {}

    def test_no_device_id_means_no_payload(self):
        # Sync is off until the user registers. This is the last line of that.
        assert syncproto.build_upload("", {7: 1800}) == {}

    def test_unparseable_rows_are_skipped_not_raised(self):
        payload = syncproto.build_upload("dev123", {"x": 60, 7: "y", 9: 300})
        assert payload["a"] == [[9, 300]]

    def test_the_app_list_is_sent_as_canonical_keys(self):
        payload = syncproto.build_app_sync("dev123", [
            {"id": 1, "name": "Discord.exe", "category": "Social"},
            {"id": 2, "name": "VS Code", "category": "Development"},
        ])
        assert payload["a"] == [[1, "discord", "Social"], [2, "vscode", "Development"]]

    def test_an_app_with_no_usable_name_is_not_sent(self):
        payload = syncproto.build_app_sync("dev123", [{"id": 1, "name": "!!!"}])
        assert payload == {}


# ── Hand-linking apps across devices ────────────────────────────────────────
#
# canonical_app_key is a best-effort join and says so: no string rule
# resolves a package named after its vendor without a brand list. The
# fallback is the user typing the same word for one app on both devices.

class TestHandLinkingApps:

    def test_an_alias_overrides_the_automatic_key(self):
        # "Firefox.exe" and "org.mozilla.firefox" do not join automatically
        # (see TestCanonicalAppKey.test_the_join_is_best_effort_and_says_so).
        # A shared alias makes them join anyway.
        payload = syncproto.build_app_sync(
            "dev123",
            [{"id": 1, "name": "Firefox.exe", "category": "Browser"}],
            aliases={"1": "browser-x"},
        )
        assert payload["a"] == [[1, "browserx", "Browser"]]

    def test_the_alias_goes_through_the_same_normaliser_as_a_real_name(self):
        # Not sent verbatim: two devices typing "Firefox" and " firefox "
        # still have to land on one key, and there is no second rule to keep
        # in sync with canonical_app_key if this were special-cased.
        assert (syncproto.canonical_app_key("Firefox")
                == syncproto.build_app_sync(
                    "dev123", [{"id": 1, "name": "x"}], aliases={"1": "Firefox"},
                )["a"][0][1])

    def test_an_alias_for_a_different_app_does_not_leak_across(self):
        payload = syncproto.build_app_sync(
            "dev123",
            [
                {"id": 1, "name": "Discord.exe", "category": "Social"},
                {"id": 2, "name": "Slack.exe", "category": "Social"},
            ],
            aliases={"1": "chatter-x"},
        )
        assert payload["a"] == [[1, "chatterx", "Social"], [2, "slack", "Social"]]

    def test_an_unusable_alias_falls_back_to_the_automatic_key(self):
        # Garbage in the alias field must drop the override, not the app.
        payload = syncproto.build_app_sync(
            "dev123", [{"id": 1, "name": "Discord.exe", "category": "Social"}],
            aliases={"1": "!!!"},
        )
        assert payload["a"] == [[1, "discord", "Social"]]

    def test_no_aliases_behaves_exactly_as_before(self):
        without = syncproto.build_app_sync("dev123", [{"id": 1, "name": "Discord.exe"}])
        with_empty = syncproto.build_app_sync(
            "dev123", [{"id": 1, "name": "Discord.exe"}], aliases={},
        )
        assert without == with_empty


# ── Hostile responses ─────────────────────────────────────────────────────

class TestParsing:
    """Everything here came off a network. Nothing about it is assumed."""

    @pytest.mark.parametrize("payload", [
        None, "", [], 0, {"apps": None}, {"apps": []}, {"apps": "nope"}, {},
    ])
    def test_a_malformed_sync_response_yields_nothing(self, payload):
        assert syncproto.parse_sync(payload) == {}

    def test_one_bad_row_does_not_cost_the_others(self):
        totals = syncproto.parse_sync(
            {"apps": {"7": 1800, "bad": 60, "9": "x", "11": -5, "12": 300}},
        )
        assert totals == {7: 1800, 12: 300}

    def test_response_values_are_clamped_to_a_day(self):
        assert syncproto.parse_sync({"apps": {"7": 10 ** 9}}) == {
            7: syncproto.MAX_PLAUSIBLE_DAILY_SEC,
        }

    def test_the_app_map_skips_what_it_cannot_read(self):
        assert syncproto.parse_app_map({"m": {"1": 42, "x": 7, "2": "y", "3": 0}}) == {1: 42}

    @pytest.mark.parametrize("payload,expected", [
        ({"devices": 3}, 3), ({"devices": "x"}, 0), ({"devices": -1}, 0), ({}, 0), (None, 0),
    ])
    def test_device_count_never_raises(self, payload, expected):
        assert syncproto.parse_device_count(payload) == expected


# ── The client ────────────────────────────────────────────────────────────

class FakeTransport:
    """
    Records requests and replays canned responses.

    `responses` maps endpoint to a value, or to an Exception to raise. None
    stands for a failed request, which is what the real transport returns for a
    timeout, a 500, or a body that is not JSON.
    """

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests = []

    def post(self, path, payload):
        self.requests.append((path, payload))
        response = self.responses.get(path)
        if isinstance(response, Exception):
            raise response
        return response

    def paths(self):
        return [path for path, _ in self.requests]

    def payload_for(self, path):
        for sent_path, payload in self.requests:
            if sent_path == path:
                return payload
        return None


@pytest.fixture
def synced(db, config):
    """A registered device with one tracked app already mapped to a server id."""
    from core import consent

    consent.record_consent(config, True)
    config.set("device_id", "device-abc")
    app_id = db.add_tracked_app("Discord", "discord.exe", "", "", "Social")
    config.set("server_app_ids", {str(app_id): 42})
    return app_id


class TestSyncIsOffUntilTheUserTurnsItOn:

    def test_no_device_id_means_no_requests(self, db, config):
        from core import consent
        consent.record_consent(config, True)

        transport = FakeTransport()
        client = SyncClient(db, config, transport=transport)

        assert not client.enabled
        assert client.sync_once() is False
        assert transport.requests == []

    def test_no_consent_means_no_requests(self, db, config):
        # PRIVACY.md says nothing leaves the machine before the policy is
        # accepted. A device id alone must not be enough.
        config.set("device_id", "device-abc")

        transport = FakeTransport()
        client = SyncClient(db, config, transport=transport)

        assert not client.enabled
        assert client.sync_once() is False
        assert transport.requests == []

    def test_unregistering_forgets_the_mapping_too(self, config, synced):
        config.set("device_token", "tok-abc")
        syncclient.unregister_device(config)
        assert config.get("device_id") == ""
        assert config.get("server_app_ids") == {}
        assert config.get("device_token") == ""


class TestOneSyncCycle:

    def test_a_successful_cycle_uploads_then_fetches(self, db, config, synced):
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 900)

        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 2400}, "devices": 2},
        })
        client = SyncClient(db, config, transport=transport)

        assert client.sync_once() is True
        assert transport.paths() == [syncclient.ENDPOINT_UPLOAD, syncclient.ENDPOINT_SYNC]

        upload = transport.payload_for(syncclient.ENDPOINT_UPLOAD)
        assert upload["a"] == [[42, 900]]
        assert upload["z"] == syncproto.local_date()

    def test_the_other_devices_time_becomes_available_to_the_limit_check(
            self, db, config, synced):
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 900)

        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            # 2400 total, 900 of which is ours: 1500 on the other device.
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 2400}},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()

        assert client.remote_seconds_for(synced) == 1500

    def test_a_failed_upload_is_not_recorded_as_sent(self, db, config, synced):
        # If it were, the merge would subtract a contribution the group total
        # does not contain, and this device's own minutes would go missing.
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 900)

        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: None,        # lost
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 900}},
        })
        client = SyncClient(db, config, transport=transport)

        assert client.sync_once() is False
        assert syncclient.ENDPOINT_SYNC not in transport.paths()
        assert client.remote_seconds_for(synced) == 0

    def test_a_failed_fetch_leaves_the_previous_totals_alone(self, db, config, synced):
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 1800}},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()
        assert client.remote_seconds_for(synced) == 1800

        transport.responses[syncclient.ENDPOINT_SYNC] = None
        assert client.sync_once() is False
        assert client.remote_seconds_for(synced) == 1800

    def test_a_transport_that_raises_does_not_escape(self, db, config, synced):
        # sync_once runs on a background thread. An exception escaping it would
        # kill the thread and stop sync for the rest of the session.
        transport = FakeTransport({syncclient.ENDPOINT_UPLOAD: RuntimeError("boom")})
        client = SyncClient(db, config, transport=transport)

        assert client.sync_once() is False
        assert client.status()["last_error"]

    def test_an_app_with_no_server_id_is_not_uploaded(self, db, config, synced):
        unmapped = db.add_tracked_app("Slack", "slack.exe", "", "", "Social")
        db.start_session(unmapped, datetime.now().isoformat())
        db.update_session_duration(1, 600)

        transport = FakeTransport({
            syncclient.ENDPOINT_APPS: {"m": {}},
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()

        assert client.remote_seconds_for(unmapped) == 0

    def test_the_app_list_is_sent_only_when_something_is_unmapped(
            self, db, config, synced):
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()
        assert syncclient.ENDPOINT_APPS not in transport.paths()

        db.add_tracked_app("Slack", "slack.exe", "", "", "Social")
        client.sync_once()
        assert syncclient.ENDPOINT_APPS in transport.paths()


class TestStaleDataIsNotEnforcedAgainst:

    def test_a_figure_older_than_the_stale_window_is_dropped(self, db, config, synced):
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 1800}},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()
        assert client.remote_seconds_for(synced) == 1800

        client._group_fetched_at = time.time() - syncproto.REMOTE_STALE_AFTER_SEC - 10
        assert client.remote_seconds_for(synced) == 0

    def test_never_synced_reports_nothing(self, db, config, synced):
        client = SyncClient(db, config, transport=FakeTransport())
        assert client.remote_seconds_for(synced) == 0

    def test_yesterdays_group_total_is_not_applied_to_today(self, db, config, synced):
        # The subtle one. A sync at 23:50 is still inside the two-hour
        # freshness window at 00:30, so freshness alone would let yesterday's
        # figure through — and the user would start the day with a limit
        # already spent. Only the date check catches this.
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 5400}},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()
        assert client.remote_seconds_for(synced) == 5400

        # Same totals, same timestamp, different day.
        client._group_date = "1999-12-31"
        assert client.remote_seconds_for(synced) == 0
        assert client.status()["fresh"] is False


class TestRegistration:

    def test_registering_stores_the_id_the_server_gave(self, config):
        transport = FakeTransport({syncclient.ENDPOINT_REGISTER: {"id": "abc123"}})
        assert syncclient.register_device(config, "my-pc", transport=transport) == "abc123"
        assert config.get("device_id") == "abc123"

    def test_an_email_is_only_sent_when_typed(self, config):
        transport = FakeTransport({syncclient.ENDPOINT_REGISTER: {"id": "abc123"}})
        syncclient.register_device(config, "my-pc", transport=transport)
        assert "e" not in transport.payload_for(syncclient.ENDPOINT_REGISTER)

    @pytest.mark.parametrize("response", [None, {}, {"id": ""}, "not-json"])
    def test_a_failed_registration_leaves_sync_off(self, config, response):
        transport = FakeTransport({syncclient.ENDPOINT_REGISTER: response})
        assert syncclient.register_device(config, "my-pc", transport=transport) == ""
        assert config.get("device_id") == ""


class TestAppAliasHelpers:
    """
    core.syncclient.app_alias / set_app_alias: the storage half of hand-
    linking apps across devices (STATUS.md). The dialog is
    ui/files_page.py's "Sync Name" field; this is what it calls.
    """

    def test_setting_and_reading_an_alias(self, config):
        syncclient.set_app_alias(config, 5, "shared-name")
        assert syncclient.app_alias(config, 5) == "shared-name"

    def test_blank_text_clears_the_alias(self, config):
        syncclient.set_app_alias(config, 5, "shared-name")
        syncclient.set_app_alias(config, 5, "   ")
        assert syncclient.app_alias(config, 5) == ""

    def test_reading_an_unset_alias_is_empty(self, config):
        assert syncclient.app_alias(config, 999) == ""

    def test_setting_an_alias_drops_the_cached_server_id(self, config):
        # The point of the whole feature: a stale match must not survive a
        # corrected alias, or the correction never takes effect.
        config.set("server_app_ids", {"5": 42})
        syncclient.set_app_alias(config, 5, "shared-name")
        assert "5" not in config.get("server_app_ids")

    def test_setting_an_alias_does_not_touch_other_apps_mappings(self, config):
        config.set("server_app_ids", {"7": 99})
        syncclient.set_app_alias(config, 5, "shared-name")
        assert config.get("server_app_ids") == {"7": 99}


class TestSyncClientSendsAliases:

    def test_an_alias_is_sent_for_an_unmapped_app(self, db, config):
        from core import consent

        consent.record_consent(config, True)
        config.set("device_id", "device-abc")
        app_id = db.add_tracked_app("Firefox", "firefox.exe", "", "", "Browser")
        syncclient.set_app_alias(config, app_id, "browser-x")

        transport = FakeTransport({
            syncclient.ENDPOINT_APPS: {"m": {}},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()

        assert transport.payload_for(syncclient.ENDPOINT_APPS)["a"] == \
            [[app_id, "browserx", "Browser"]]


class TestNothingUndisclosedLeavesTheMachine:
    """
    A build-enforced check on PRIVACY.md.

    The policy lists exactly what an upload contains. Adding a field to the
    payload is a one-line change and makes the policy false, which is the kind
    of thing nobody notices until it matters. So the shape is pinned here.
    """

    def test_an_upload_carries_only_the_documented_fields(self, db, config, synced):
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 900)

        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()

        payload = transport.payload_for(syncclient.ENDPOINT_UPLOAD)
        # device id, timestamp, local date, usage rows. Nothing else.
        assert set(payload) == {"d", "t", "z", "a"}

    def test_an_upload_carries_no_names_paths_or_window_titles(
            self, db, config, synced):
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 900)

        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()

        # Usage rows are [server_app_id, seconds] — two integers, no strings.
        for row in transport.payload_for(syncclient.ENDPOINT_UPLOAD)["a"]:
            assert len(row) == 2
            assert all(isinstance(value, int) for value in row)

    def test_the_app_list_carries_no_executable_paths(self, db, config):
        from core import consent

        consent.record_consent(config, True)
        config.set("device_id", "device-abc")
        db.add_tracked_app("Discord", "discord.exe",
                           r"C:\Users\dejan\AppData\Discord\app.exe", "", "Social")

        transport = FakeTransport({
            syncclient.ENDPOINT_APPS: {"m": {}},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()

        sent = str(transport.payload_for(syncclient.ENDPOINT_APPS))
        # A path leaks the Windows username, which the policy does not disclose.
        assert "dejan" not in sent
        assert "AppData" not in sent

    def test_the_policy_still_says_sync_is_off_until_registration(self):
        import os

        from tests.conftest import REPO_ROOT

        policy = open(os.path.join(REPO_ROOT, "PRIVACY.md"),
                      encoding="utf-8").read().lower()
        assert "device sync is off until" in policy


class TestTheTransportRefusesPlainHttp:

    def test_http_is_not_downgraded_to(self):
        # Usage data leaves the machine here; clear text is not an option.
        transport = syncclient.Transport("http://example.com")
        assert transport.post("/upload", {"d": "x"}) is None

    def test_an_empty_url_sends_nothing(self):
        assert syncclient.Transport("").post("/upload", {"d": "x"}) is None


# ── The monitor's side ────────────────────────────────────────────────────

class TestTheLimitCheckCountsBothDevices:
    """
    The end of the chain. Everything above exists so that this holds: an hour
    on the phone plus an hour on the PC reaches a two-hour limit.
    """

    def _monitor(self, db, config, remote_sec):
        from core.monitor import Monitor

        class StubSync:
            def remote_seconds_for(self, app_id):
                return remote_sec

        return Monitor(db, config, sync_client=StubSync())

    def test_remote_time_is_added_to_the_local_total(self, db, config, synced):
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 1800)

        monitor = self._monitor(db, config, remote_sec=1800)
        assert monitor._usage_today_sec(synced) == 3600

    def test_without_a_sync_client_nothing_changes(self, db, config, synced):
        from core.monitor import Monitor

        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 1800)

        monitor = Monitor(db, config)
        assert monitor._usage_today_sec(synced) == 1800

    def test_a_sync_client_that_raises_falls_back_to_local_usage(
            self, db, config, synced):
        from core.monitor import Monitor

        class BrokenSync:
            def remote_seconds_for(self, app_id):
                raise RuntimeError("boom")

        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 1800)

        monitor = Monitor(db, config, sync_client=BrokenSync())
        # Local usage only — never zero, and never an exception into the poll
        # loop that enforces limits.
        assert monitor._usage_today_sec(synced) == 1800

    def test_a_limit_is_reached_by_two_devices_together(self, db, config, synced):
        # 40 minutes here, 25 minutes on the phone, 60-minute limit.
        db.start_session(synced, datetime.now().isoformat())
        db.update_session_duration(1, 40 * 60)

        local_only = self._monitor(db, config, remote_sec=0)
        assert local_only._usage_today_sec(synced) < 3600

        both = self._monitor(db, config, remote_sec=25 * 60)
        assert both._usage_today_sec(synced) >= 3600


# ── Authentication (AUDIT SF-09) ────────────────────────────────────────────
#
# A device id alone is not a credential: it travels in request bodies (and,
# before this fix, in one URL path) and lands in server, proxy and log lines.
# Every request after registration must carry the bearer token the server
# issues alongside the id.

class _FakeHTTPResponse:
    """Stands in for the object urlopen()'s context manager yields."""

    def __init__(self, status=200, body=b'{"ok": 1}'):
        self.status = status
        self._body = body

    def read(self, *_args, **_kwargs):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False


class TestAuthentication:

    def test_transport_sends_the_token_as_a_bearer_header(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return _FakeHTTPResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = syncclient.Transport("https://example.com", token="secret-token") \
            .post("/upload", {"d": "x"})

        assert result == {"ok": 1}
        assert captured["request"].get_header("Authorization") == "Bearer secret-token"

    def test_transport_sends_no_authorization_header_without_a_token(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return _FakeHTTPResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        # Backward compatible: a device that has never registered, or a
        # server that has not deployed token issuance yet, still works.
        syncclient.Transport("https://example.com").post("/upload", {"d": "x"})
        assert captured["request"].get_header("Authorization") is None

    def test_build_transport_reads_the_server_url_and_token_from_config(self, config):
        config.set("server_url", "https://sync.protbot.app")
        config.set("device_token", "tok-123")

        transport = syncclient.build_transport(config)

        assert transport.base_url == "https://sync.protbot.app"
        assert transport.token == "tok-123"

    def test_registering_stores_the_token_the_server_gave(self, config):
        transport = FakeTransport({
            syncclient.ENDPOINT_REGISTER: {"id": "abc123", "t": "tok-abc"},
        })
        syncclient.register_device(config, "my-pc", transport=transport)
        assert config.get("device_token") == "tok-abc"

    def test_a_server_with_no_token_issuance_yet_still_registers(self, config):
        # Today's real behaviour: there is no server, so no response ever
        # carries "t". Registration must not fail because of that.
        transport = FakeTransport({syncclient.ENDPOINT_REGISTER: {"id": "abc123"}})
        assert syncclient.register_device(config, "my-pc", transport=transport) == "abc123"
        assert config.get("device_token") == ""

    def test_sync_client_uses_the_stored_token_by_default(self, db, config, synced):
        config.set("device_token", "tok-xyz")
        client = SyncClient(db, config)
        assert client._transport.token == "tok-xyz"

    def test_authed_request_attaches_the_token(self, monkeypatch, config):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return _FakeHTTPResponse(body=b'{"devices": []}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        config.set("server_url", "https://sync.protbot.app")
        config.set("device_token", "tok-xyz")
        status, data = syncclient.authed_request(config, "POST", "/group", {"d": "dev-1"})

        assert status == 200
        assert data == {"devices": []}
        assert captured["request"].get_header("Authorization") == "Bearer tok-xyz"
        # The device id travelled in the body, never string-interpolated
        # into the URL -- the point of this whole finding.
        assert "dev-1" not in captured["request"].full_url

    def test_authed_request_sends_the_body_as_json(self, monkeypatch, config):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return _FakeHTTPResponse(body=b"{}")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        config.set("server_url", "https://sync.protbot.app")

        syncclient.authed_request(config, "POST", "/group", {"d": "dev-1"})
        assert json.loads(captured["request"].data) == {"d": "dev-1"}

    def test_authed_request_refuses_plain_http(self, config):
        config.set("server_url", "http://example.com")
        with pytest.raises(ValueError):
            syncclient.authed_request(config, "POST", "/group", {"d": "dev-1"})

    def test_authed_request_requires_a_server_url(self, config):
        config.set("server_url", "")
        with pytest.raises(ValueError):
            syncclient.authed_request(config, "GET", "/group")


# ── The device id must never travel in a URL (AUDIT SF-09) ─────────────────
#
# The audit's literal citations: `ui/processes_page.py` and
# `ui/devices_page.py` each hand-rolled their own request instead of going
# through Transport/authed_request, and one of them string-interpolated the
# device id straight into the URL path. Read as text, like the rest of this
# suite's checks on the UI modules it cannot import (no display in CI).

class TestDeviceIdNeverTravelsInAUrl:

    @staticmethod
    def _ui_source(name: str) -> str:
        import os

        from tests.conftest import REPO_ROOT

        with open(os.path.join(REPO_ROOT, "ui", name), encoding="utf-8") as fh:
            return fh.read()

    def test_processes_page_has_no_hand_rolled_request(self):
        text = self._ui_source("processes_page.py")
        assert "urllib.request" not in text
        assert "/sync/{device_id}" not in text
        assert "from core import syncclient" in text

    def test_devices_page_api_helper_delegates_to_syncclient(self):
        text = self._ui_source("devices_page.py")
        assert "urlopen" not in text
        assert "syncclient.authed_request" in text
        assert "/group/{dev_id}" not in text
        assert '"/r"' not in text, \
            "the register endpoint must match syncclient.ENDPOINT_REGISTER"


class TestTheHandLinkDialog:
    """
    ui/files_page.py's "Sync Name" field on the app-edit dialog. Read as
    text, like the rest of this section -- Tk has no display in CI.
    """

    def test_the_edit_dialog_reads_and_writes_the_alias(self):
        import os

        from tests.conftest import REPO_ROOT

        with open(os.path.join(REPO_ROOT, "ui", "files_page.py"), encoding="utf-8") as fh:
            text = fh.read()
        assert "from core.syncclient import app_alias, set_app_alias" in text
        assert "set_app_alias(self.config, app_id, e_alias.get())" in text


# ── The wire contract records the fix (AUDIT SF-09) ─────────────────────────
#
# server/models.py is the spec a real server is built against (#8/#9 in
# STATUS.md); it cannot be imported here without pydantic, which is a known,
# accepted gap (AUDIT ST-05) -- read as text like the rest of this section.

class TestTheWireContractRequiresTheToken:

    @staticmethod
    def _models_source() -> str:
        import os

        from tests.conftest import REPO_ROOT

        with open(os.path.join(REPO_ROOT, "server", "models.py"), encoding="utf-8") as fh:
            return fh.read()

    def test_register_resp_carries_a_token(self):
        import re

        match = re.search(r"class RegisterResp\(BaseModel\):(.*?)\n\n",
                          self._models_source(), re.DOTALL)
        assert match, "RegisterResp not found in server/models.py"
        assert re.search(r"^\s*t:\s*str", match.group(1), re.MULTILINE), (
            "RegisterResp must carry the bearer token every later request "
            "authenticates with"
        )

    def test_the_group_endpoint_is_specified(self):
        # ui/devices_page.py's "list linked devices" call had no model at
        # all before this fix -- undocumented and, worse, a GET with the
        # device id in the URL.
        text = self._models_source()
        assert "class GroupReq" in text
        assert "class GroupResp" in text
