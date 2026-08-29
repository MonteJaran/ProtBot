"""
Device linking by QR code.

The PC builds the payload and the phone parses it, and there is nothing in
between to absorb a disagreement. So every case here has a twin in
`android/core/src/test/kotlin/app/protbot/core/LinkingTest.kt`. If the two
implementations drift, linking stops working with no error on either side
pointing at why — the payload just does not parse, on a device that is not the
one being changed.
"""

import time

import pytest

from core import linking
from core.linking import LinkError, LinkSession

KEY = "ABCD2345"


class FakeTransport:
    """Canned responses; None stands for a request that did not come back."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests = []

    def post(self, path, payload):
        self.requests.append((path, payload))
        return self.responses.get(path)


# ── The round trip ────────────────────────────────────────────────────────

class TestThePayload:

    def test_a_payload_parses_back_to_the_same_key(self):
        assert linking.parse_payload(linking.build_payload(KEY)) == KEY

    def test_the_payload_is_the_exact_string_the_phone_expects(self):
        # Pinned literally, and pinned identically in LinkingTest.kt. Changing
        # the shape of this string has to be a deliberate act with a version
        # bump, not a quiet edit on one side.
        assert linking.build_payload(KEY) == "https://protbot.app/l#1.ABCD2345"

    def test_the_key_travels_in_the_fragment_never_the_path_or_query(self):
        # Everything after "#" stays in the browser. Opening the link on a
        # phone that does not have the app must not put the key in a web
        # server's access log or a proxy cache.
        payload = linking.build_payload(KEY)
        before_fragment = payload.split("#", 1)[0]

        assert KEY not in before_fragment
        assert "?" not in payload
        assert payload.split("#", 1)[1] == f"1.{KEY}"

    def test_it_is_an_https_url_not_a_custom_scheme(self):
        # A protbot:// code shows up in a phone camera as "no app can open
        # this" exactly when ProtBot is not installed yet — which is when
        # someone is most likely to be scanning it.
        assert linking.build_payload(KEY).startswith("https://")

    def test_the_payload_fits_a_small_qr_code(self):
        # A dense code is a code that will not scan off a screen at arm's
        # length. This one should stay well inside the encoder's range.
        from core import qrcode

        version = qrcode.smallest_version(len(linking.build_payload(KEY)), "Q")
        assert version <= 4, f"the link payload needs a version-{version} code"


# ── Keys ──────────────────────────────────────────────────────────────────

class TestKeys:

    def test_a_generated_key_is_valid(self):
        for _ in range(50):
            assert linking.is_valid_key(linking.new_key())

    def test_generated_keys_are_not_predictable(self):
        # `secrets`, not `random`. Fifty draws from a 32-character alphabet
        # should not repeat; if they do, something is seeding badly.
        keys = {linking.new_key() for _ in range(50)}
        assert len(keys) == 50

    @pytest.mark.parametrize("char", ["O", "I", "0", "1"])
    def test_the_confusable_characters_are_not_in_the_alphabet(self, char):
        # These are what people transcribe wrongly when the camera will not
        # focus and they fall back to typing the key.
        assert char not in linking.KEY_ALPHABET

    @pytest.mark.parametrize("key", ["ABCD234O", "ABCD2341", "ABCD234", "ABCD23456",
                                     "abcd-234", "", None, "!!!!!!!!"])
    def test_invalid_keys_are_rejected(self, key):
        assert not linking.is_valid_key(key)

    def test_an_unusable_key_never_becomes_a_qr_code(self):
        # A QR carrying a malformed key is worse than no QR: it fails at the
        # far end, after the user has already done the work of scanning it.
        for key in ("nope", "", None, "ABCD234O"):
            with pytest.raises(LinkError):
                linking.build_payload(key)


# ── Parsing ───────────────────────────────────────────────────────────────

class TestParsing:

    def test_a_bare_key_typed_by_hand_is_accepted(self):
        # The fallback when a camera will not focus. Nobody should have to
        # reproduce a URL by hand to link a device.
        assert linking.parse_payload(KEY) == KEY
        assert linking.parse_payload("  abcd2345  ") == KEY

    def test_a_lowercase_scan_is_accepted(self):
        assert linking.parse_payload("https://protbot.app/l#1.abcd2345") == KEY

    def test_a_code_from_a_newer_version_is_refused_not_guessed_at(self):
        with pytest.raises(LinkError, match="newer version"):
            linking.parse_payload("https://protbot.app/l#99.ABCD2345")

    def test_a_code_from_an_older_version_is_refused(self):
        with pytest.raises(LinkError, match="old version"):
            linking.parse_payload("https://protbot.app/l#0.ABCD2345")

    def test_a_damaged_key_inside_a_valid_payload_is_refused(self):
        with pytest.raises(LinkError, match="damaged"):
            linking.parse_payload("https://protbot.app/l#1.ABCD")

    @pytest.mark.parametrize("text", [
        "https://example.com/", "just some text", "", "   ", None,
        "https://protbot.app/l", "https://protbot.app/l#",
        "https://protbot.app/l#nope", "#", "##", "#1.",
    ])
    def test_anything_that_is_not_a_link_code_is_refused(self, text):
        with pytest.raises(LinkError):
            linking.parse_payload(text)

    def test_a_very_long_scan_does_not_hang_or_crash(self):
        # A scanner hands over whatever it read, including a wall of text off
        # a poster. It must fail as a rejection, not as an exception nobody
        # catches.
        with pytest.raises(LinkError):
            linking.parse_payload("a" * 100000)


# ── Expiry ────────────────────────────────────────────────────────────────

class TestExpiry:

    def test_a_fresh_code_has_its_full_lifetime(self):
        assert linking.seconds_remaining(1000, now=1000) == linking.LINK_DISPLAY_SECONDS

    def test_the_countdown_runs_down(self):
        assert linking.seconds_remaining(1000, now=1060) == \
            linking.LINK_DISPLAY_SECONDS - 60

    def test_an_expired_code_reports_zero_never_a_negative(self):
        # A negative remainder rendered as a countdown looks like the code is
        # getting more valid, not less.
        assert linking.seconds_remaining(
            1000, now=1000 + linking.LINK_DISPLAY_SECONDS + 99) == 0
        assert linking.is_expired(1000, now=1000 + linking.LINK_DISPLAY_SECONDS + 1)

    def test_a_clock_jumping_backwards_cannot_extend_a_code(self):
        # The worse of the two clock failures: it would keep a code the server
        # has already forgotten on screen indefinitely, handing someone a key
        # that cannot work.
        assert linking.seconds_remaining(1000, now=500) <= linking.LINK_DISPLAY_SECONDS

    def test_a_code_never_issued_is_already_expired(self):
        assert linking.seconds_remaining(0) == 0
        assert linking.is_expired(0)

    def test_the_display_lifetime_is_under_the_servers_five_minutes(self):
        # So the code stops being offered before it stops working, rather than
        # leaving the user staring at a key the server has forgotten.
        assert linking.LINK_DISPLAY_SECONDS < 5 * 60


# ── The session on the PC ─────────────────────────────────────────────────

class TestLinkSession:

    def test_a_session_produces_a_scannable_matrix(self):
        session = LinkSession(KEY)
        matrix = session.matrix()

        assert len(matrix) == len(matrix[0])
        assert matrix[0][0] is True          # the top-left finder

    def test_the_matrix_encodes_this_sessions_payload(self):
        pytest.importorskip("cv2")
        pytest.importorskip("numpy")

        import cv2
        import numpy as np

        session = LinkSession(KEY)
        matrix = session.matrix()

        scale, quiet = 8, 4
        size = (len(matrix) + quiet * 2) * scale
        image = np.full((size, size), 255, np.uint8)
        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                if dark:
                    top, left = (r + quiet) * scale, (c + quiet) * scale
                    image[top:top + scale, left:left + scale] = 0

        decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
        assert decoded == session.payload
        assert linking.parse_payload(decoded) == KEY

    def test_a_session_refuses_an_invalid_key(self):
        with pytest.raises(LinkError):
            LinkSession("nope")

    def test_the_key_is_grouped_for_reading_aloud(self):
        assert LinkSession(KEY).formatted_key() == "ABCD 2345"

    def test_a_session_expires(self):
        session = LinkSession(KEY, issued_at=time.time() - 10_000)
        assert session.expired()
        assert session.seconds_left() == 0

    def test_a_fresh_session_is_not_expired(self):
        session = LinkSession(KEY)
        assert not session.expired()
        assert session.seconds_left() > 0


# ── Talking to a server that does not exist yet ───────────────────────────

class TestRequestingALink:

    def test_it_refuses_before_the_device_is_registered(self, config):
        # Linking joins a group on the server. Without a device id there is
        # nothing to join it to, and a code that cannot work would send the
        # user to the phone to find out.
        with pytest.raises(LinkError, match="Register this device"):
            linking.request_link(config, transport=FakeTransport())

    def test_a_server_key_becomes_a_session(self, config):
        config.set("device_id", "device-abc")
        transport = FakeTransport({"/link/new": {"k": KEY}})

        session = linking.request_link(config, transport=transport)
        assert session.key == KEY
        assert transport.requests[0][0] == "/link/new"

    def test_an_unreachable_server_says_so(self, config):
        config.set("device_id", "device-abc")
        with pytest.raises(LinkError, match="Could not reach"):
            linking.request_link(config, transport=FakeTransport({"/link/new": None}))

    @pytest.mark.parametrize("response", [{}, {"k": ""}, {"k": "nope"}, {"k": "ABCD234O"}])
    def test_a_key_the_server_mangled_is_not_displayed(self, config, response):
        # Better to fail here than to draw a QR code that cannot work.
        config.set("device_id", "device-abc")
        with pytest.raises(LinkError):
            linking.request_link(config,
                                 transport=FakeTransport({"/link/new": response}))


class TestJoiningALink:

    def test_joining_sends_this_devices_id_with_the_key(self, config):
        config.set("device_id", "phone-xyz")
        transport = FakeTransport({"/link/join": {"ok": 1, "grp": "group-1"}})

        assert linking.join_link(config, linking.build_payload(KEY),
                                 transport=transport) == "group-1"
        path, payload = transport.requests[0]
        assert path == "/link/join"
        assert payload == {"d": "phone-xyz", "k": KEY}

    def test_an_expired_code_is_reported_as_such(self, config):
        config.set("device_id", "phone-xyz")
        with pytest.raises(LinkError, match="expired"):
            linking.join_link(config, KEY,
                              transport=FakeTransport({"/link/join": {"ok": 0}}))

    def test_joining_refuses_before_registration(self, config):
        with pytest.raises(LinkError, match="Register this device"):
            linking.join_link(config, KEY, transport=FakeTransport())

    def test_a_bad_code_never_reaches_the_network(self, config):
        # Parse first, then send. No point spending a request on a code that
        # cannot possibly be right.
        config.set("device_id", "phone-xyz")
        transport = FakeTransport()
        with pytest.raises(LinkError):
            linking.join_link(config, "not a code", transport=transport)
        assert transport.requests == []


# ── The two implementations must agree ────────────────────────────────────

class TestTheKotlinSideMatches:
    """
    Read the Kotlin constants out of the source and compare them.

    Not a substitute for the shared test cases, but it catches the specific
    way this breaks: someone changes the alphabet, the length or the base URL
    on one side, every test on that side still passes, and linking quietly
    stops working across devices.
    """

    @staticmethod
    def kotlin_source() -> str:
        import os

        from tests.conftest import REPO_ROOT

        path = os.path.join(REPO_ROOT, "android", "core", "src", "main",
                            "kotlin", "app", "protbot", "core", "Linking.kt")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_the_alphabet_matches(self):
        assert f'KEY_ALPHABET = "{linking.KEY_ALPHABET}"' in self.kotlin_source()

    def test_the_key_length_matches(self):
        assert f"KEY_LENGTH = {linking.KEY_LENGTH}" in self.kotlin_source()

    def test_the_payload_version_matches(self):
        assert f"PAYLOAD_VERSION = {linking.PAYLOAD_VERSION}" in self.kotlin_source()

    def test_the_base_url_matches(self):
        assert f'BASE_URL = "{linking.LINK_BASE_URL}"' in self.kotlin_source()

    def test_the_display_lifetime_matches(self):
        # Written as an expression on both sides, so compare the value.
        source = self.kotlin_source()
        assert "DISPLAY_SECONDS = 4 * 60 + 30" in source
        assert linking.LINK_DISPLAY_SECONDS == 4 * 60 + 30


class TestTheAndroidSideCanBeReached:
    """
    A link code is useless if scanning it does nothing on the phone.

    The manifest is the only part of that path this machine can check — the
    app module has never been compiled — so what is verified here is that the
    filter exists and matches the URL the PC actually produces.
    """

    @staticmethod
    def manifest() -> str:
        import os

        from tests.conftest import REPO_ROOT

        path = os.path.join(REPO_ROOT, "android", "app", "src", "main",
                            "AndroidManifest.xml")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_the_manifest_handles_the_link_url(self):
        from urllib.parse import urlparse

        parsed = urlparse(linking.LINK_BASE_URL)
        manifest = self.manifest()

        assert f'android:host="{parsed.hostname}"' in manifest
        assert 'android:scheme="https"' in manifest
        assert f'android:pathPrefix="{parsed.path}"' in manifest

    def test_the_filter_is_browsable_or_a_camera_cannot_open_it(self):
        # Without BROWSABLE the stock camera app will not offer to open the
        # link, which is the entire point of using an https URL.
        assert "android.intent.category.BROWSABLE" in self.manifest()
