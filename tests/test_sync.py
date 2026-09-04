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

import time
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


class TestManualKeyOverrides:
    """
    canonical_app_key is a best-effort guess (TestCanonicalAppKey above has
    the case it cannot resolve: Firefox.exe vs org.mozilla.firefox). This is
    the fallback — build_app_sync's half of it; core.syncclient's
    set_manual_key/manual_key_for/clear_manual_key is the other half,
    covered in TestMatchingAppsByHand below.
    """

    def test_an_override_replaces_the_computed_key(self):
        payload = syncproto.build_app_sync(
            "dev123", [{"id": 1, "name": "Firefox.exe", "category": "Web"}],
            overrides={1: "firefox"},
        )
        assert payload["a"] == [[1, "firefox", "Web"]]

    def test_a_string_keyed_override_works_the_same_as_an_int_one(self):
        # config.json round-trips int keys as strings; this must not care.
        payload = syncproto.build_app_sync(
            "dev123", [{"id": 1, "name": "Firefox.exe"}],
            overrides={"1": "firefox"},
        )
        assert payload["a"] == [[1, "firefox", ""]]

    def test_apps_with_no_override_still_use_the_computed_key(self):
        payload = syncproto.build_app_sync(
            "dev123",
            [{"id": 1, "name": "Firefox.exe"}, {"id": 2, "name": "Discord.exe"}],
            overrides={1: "firefox"},
        )
        assert payload["a"] == [[1, "firefox", ""], [2, "discord", ""]]

    def test_no_overrides_at_all_behaves_exactly_as_before(self):
        apps = [{"id": 1, "name": "Discord.exe", "category": "Social"}]
        assert (syncproto.build_app_sync("dev123", apps)
                == syncproto.build_app_sync("dev123", apps, overrides=None)
                == syncproto.build_app_sync("dev123", apps, overrides={}))

    def test_an_override_for_an_unrelated_app_id_does_nothing(self):
        payload = syncproto.build_app_sync(
            "dev123", [{"id": 1, "name": "Discord.exe"}],
            overrides={999: "something-else"},
        )
        assert payload["a"] == [[1, "discord", ""]]


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
        config.set("device_token", "secret-tok")
        syncclient.unregister_device(config)
        assert config.get("device_id") == ""
        assert config.get("device_token") == ""
        assert config.get("server_app_ids") == {}


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


class TestAuthentication:
    """
    AUDIT SF-09: the device id was the whole credential, and it travelled
    somewhere a server or proxy would log it. A token from registration, sent
    as a header, is what makes a leaked device id alone useless.
    """

    def test_the_stored_token_is_armed_onto_the_transport_before_a_cycle(
            self, db, config, synced):
        config.set("device_token", "secret-tok")
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()

        # FakeTransport does not build headers itself — this proves the
        # client hands the token to whatever transport it holds, which is
        # what the real Transport.post() then turns into the header. See
        # TestTheTransportSendsTheBearerToken for the header itself.
        assert transport.token == "secret-tok"

    def test_no_stored_token_means_none_is_armed(self, db, config, synced):
        # No registration has ever happened against the version of the
        # server that hands one out — degrade to the same unauthenticated
        # request rather than sending a garbage header.
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()
        assert transport.token == ""

    def test_a_changed_token_replaces_the_old_one_next_cycle(
            self, db, config, synced):
        # Re-registration can happen without restarting the process; the next
        # cycle must not keep sending a token that is no longer valid.
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        client = SyncClient(db, config, transport=transport)

        config.set("device_token", "first-tok")
        client.sync_once()
        assert transport.token == "first-tok"

        config.set("device_token", "second-tok")
        client.sync_once()
        assert transport.token == "second-tok"

    def test_status_reports_how_many_devices_are_in_the_group(
            self, db, config, synced):
        transport = FakeTransport({
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {"42": 600}, "devices": 3},
        })
        client = SyncClient(db, config, transport=transport)
        client.sync_once()
        assert client.status()["devices"] == 3

    def test_status_defaults_devices_to_zero_before_ever_syncing(
            self, db, config):
        assert SyncClient(db, config, transport=FakeTransport()).status()["devices"] == 0


class TestMatchingAppsByHand:
    """
    core.syncclient's half of the manual-key fallback — see
    TestManualKeyOverrides above for build_app_sync's. STATUS.md:
    canonical_app_key cannot resolve every pair (Firefox.exe never meets
    org.mozilla.firefox on its own), and this is what closes that case —
    letting the user say "these two are the same app" on both devices
    rather than counting one app twice.
    """

    def test_no_override_by_default(self, config):
        assert syncclient.manual_key_for(config, 1) == ""

    def test_setting_one_makes_it_come_back(self, config):
        syncclient.set_manual_key(config, 1, "firefox")
        assert syncclient.manual_key_for(config, 1) == "firefox"

    def test_it_is_normalised_the_same_way_canonical_app_key_normalises_everything(
            self, config):
        # What the caller sees back is exactly what has to match on the
        # other device — not raw text that merely looks similar.
        stored = syncclient.set_manual_key(config, 1, "  Firefox.EXE  ")
        assert stored == "firefox"
        assert syncclient.manual_key_for(config, 1) == "firefox"

    def test_setting_it_to_noise_only_text_clears_it_instead(self, config):
        # An empty key is not "no override" — it is the one string every
        # other unresolved app would also collide on. See canonical_app_key.
        syncclient.set_manual_key(config, 1, "firefox")
        stored = syncclient.set_manual_key(config, 1, "   !!!   ")
        assert stored == ""
        assert syncclient.manual_key_for(config, 1) == ""

    def test_clear_manual_key_goes_back_to_automatic(self, config):
        syncclient.set_manual_key(config, 1, "firefox")
        syncclient.clear_manual_key(config, 1)
        assert syncclient.manual_key_for(config, 1) == ""

    def test_it_does_not_disturb_a_different_apps_override(self, config):
        syncclient.set_manual_key(config, 1, "firefox")
        syncclient.set_manual_key(config, 2, "chrome")
        syncclient.clear_manual_key(config, 1)
        assert syncclient.manual_key_for(config, 1) == ""
        assert syncclient.manual_key_for(config, 2) == "chrome"

    def test_setting_it_drops_the_cached_server_id(self, config, synced):
        # _ensure_app_ids only re-sends an app already missing from
        # server_app_ids — an override that did not do this would sit
        # unused until the app was untracked and retracked.
        assert config.get("server_app_ids") == {str(synced): 42}
        syncclient.set_manual_key(config, synced, "discord-alt")
        assert str(synced) not in config.get("server_app_ids")

    def test_setting_it_to_the_same_key_still_drops_the_mapping(self, config, synced):
        # No special-casing "the key did not actually change" — simpler, and
        # the cost is one redundant /apps entry, not a wrong merge.
        syncclient.set_manual_key(config, synced, "discord")
        assert str(synced) not in config.get("server_app_ids")

    def test_clearing_also_drops_the_cached_server_id(self, config, synced):
        syncclient.set_manual_key(config, synced, "discord-alt")
        config.set("server_app_ids", {str(synced): 99})   # simulate a re-sync
        syncclient.clear_manual_key(config, synced)
        assert str(synced) not in config.get("server_app_ids")

    def test_a_sync_cycle_sends_the_override_and_updates_the_mapping(
            self, db, config, synced):
        # "our-discord" normalises to "ourdiscord" (canonical_app_key drops
        # punctuation, same as everywhere else) — set_manual_key's own
        # return value is exactly this, which is what the test asserts on.
        stored_key = syncclient.set_manual_key(config, synced, "our-discord")

        transport = FakeTransport({
            syncclient.ENDPOINT_APPS: {"m": {str(synced): 77}},
            syncclient.ENDPOINT_UPLOAD: {"ok": 1},
            syncclient.ENDPOINT_SYNC: {"apps": {}},
        })
        SyncClient(db, config, transport=transport).sync_once()

        apps_payload = transport.payload_for(syncclient.ENDPOINT_APPS)
        assert apps_payload["a"] == [[synced, stored_key, "Social"]]
        # The server's answer under the new key is what gets used from here.
        assert config.get("server_app_ids") == {str(synced): 77}


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
        transport = FakeTransport({
            syncclient.ENDPOINT_REGISTER: {"id": "abc123", "tok": "secret-tok"},
        })
        assert syncclient.register_device(config, "my-pc", transport=transport) == "abc123"
        assert config.get("device_id") == "abc123"

    def test_registering_stores_the_token_too(self, config):
        # AUDIT SF-09: the token, not the device id, is the credential from
        # here on. Losing it on the way to config would silently leave every
        # later request unauthenticated.
        transport = FakeTransport({
            syncclient.ENDPOINT_REGISTER: {"id": "abc123", "tok": "secret-tok"},
        })
        syncclient.register_device(config, "my-pc", transport=transport)
        assert config.get("device_token") == "secret-tok"

    def test_an_email_is_only_sent_when_typed(self, config):
        transport = FakeTransport({
            syncclient.ENDPOINT_REGISTER: {"id": "abc123", "tok": "secret-tok"},
        })
        syncclient.register_device(config, "my-pc", transport=transport)
        assert "e" not in transport.payload_for(syncclient.ENDPOINT_REGISTER)

    def test_a_platform_is_only_sent_when_given(self, config):
        without = FakeTransport({
            syncclient.ENDPOINT_REGISTER: {"id": "abc123", "tok": "secret-tok"},
        })
        syncclient.register_device(config, "my-pc", transport=without)
        assert "p" not in without.payload_for(syncclient.ENDPOINT_REGISTER)

        with_platform = FakeTransport({
            syncclient.ENDPOINT_REGISTER: {"id": "abc123", "tok": "secret-tok"},
        })
        syncclient.register_device(config, "my-pc", platform="Windows",
                                   transport=with_platform)
        assert with_platform.payload_for(syncclient.ENDPOINT_REGISTER)["p"] == "Windows"

    @pytest.mark.parametrize("response", [
        None, {}, "not-json",
        {"id": ""},                        # no id at all
        {"id": "abc123"},                  # id but no token — see below
    ])
    def test_a_failed_registration_leaves_sync_off(self, config, response):
        # A response with an id but no token is a failure too, not a partial
        # success: continuing without a token would silently fall back to the
        # unauthenticated behaviour this exists to close.
        transport = FakeTransport({syncclient.ENDPOINT_REGISTER: response})
        assert syncclient.register_device(config, "my-pc", transport=transport) == ""
        assert config.get("device_id") == ""
        assert config.get("device_token") == ""


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


class TestTheTransportSendsTheBearerToken:
    """
    One layer below TestAuthentication: this is the header actually landing
    on the wire, not just the client handing a token to its transport.
    """

    class _FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _n):
            return self._body

    def test_a_token_becomes_an_authorization_header(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return self._FakeResponse(b"{}")

        monkeypatch.setattr(syncclient.urllib.request, "urlopen", fake_urlopen)

        transport = syncclient.Transport("https://example.com", token="secret-tok")
        transport.post("/sync", {"d": "x"})

        assert captured["request"].get_header("Authorization") == "Bearer secret-tok"

    def test_no_token_means_no_authorization_header(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return self._FakeResponse(b"{}")

        monkeypatch.setattr(syncclient.urllib.request, "urlopen", fake_urlopen)

        transport = syncclient.Transport("https://example.com")
        transport.post("/sync", {"d": "x"})

        assert captured["request"].get_header("Authorization") is None

    def test_the_token_can_be_set_after_construction(self, monkeypatch):
        # SyncClient reuses one Transport for its whole life and arms the
        # token onto it fresh before each cycle rather than rebuilding it —
        # this is the attribute that makes that possible.
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return self._FakeResponse(b"{}")

        monkeypatch.setattr(syncclient.urllib.request, "urlopen", fake_urlopen)

        transport = syncclient.Transport("https://example.com")
        transport.token = "armed-later"
        transport.post("/sync", {"d": "x"})

        assert captured["request"].get_header("Authorization") == "Bearer armed-later"


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
