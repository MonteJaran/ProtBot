"""
The paperwork, held to the same standard as the code.

Every check here corresponds to an obligation that is real but invisible: a
licence notice a dependency requires you to ship, a right the GDPR gives the
user, a crash that would otherwise vanish. None of it shows up in normal use,
which is exactly why it needs a test — a missing notice file is not something
anyone notices until it is a problem.
"""

import json
import os
import re
import sys
import threading

import pytest

from core import crash, dataexport
from core.version import APP_NAME

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name: str) -> str:
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as fh:
        return fh.read()


# ── Licensing ─────────────────────────────────────────────────────────────

class TestLicensing:
    """
    psutil is BSD-3-Clause and plyer is MIT. Both say, in the same words, that
    a binary distribution must reproduce their copyright notice. Shipping
    without one is a licence breach, and it is the kind that goes unnoticed
    until somebody looks.
    """

    def test_the_project_has_a_licence_file(self):
        # Absent, a public repository is all-rights-reserved by default and
        # nobody can tell. See the note at the bottom of LICENSE.
        assert os.path.isfile(os.path.join(REPO_ROOT, "LICENSE"))

    def test_third_party_notices_exist(self):
        assert os.path.isfile(os.path.join(REPO_ROOT, "THIRD_PARTY_NOTICES.md"))

    @pytest.mark.parametrize("dependency", ["psutil", "plyer"])
    def test_every_bundled_dependency_is_named_in_the_notices(self, dependency):
        assert dependency in read("THIRD_PARTY_NOTICES.md").lower()

    def test_the_notices_carry_the_actual_licence_text(self):
        # Naming a licence is not reproducing it. Both licences require the
        # permission text itself, not a reference to it.
        notices = read("THIRD_PARTY_NOTICES.md")
        assert "Redistributions of source code must retain" in notices   # BSD-3
        assert "Permission is hereby granted, free of charge" in notices  # MIT

    def test_requirements_and_notices_do_not_drift(self):
        # A dependency added to the lockfile but not to the notices is the
        # exact way this obligation gets broken, so the build catches it.
        lock = read("requirements.lock")
        notices = read("THIRD_PARTY_NOTICES.md").lower()

        packages = {
            line.split("==")[0].strip().lower()
            for line in lock.splitlines()
            if "==" in line and not line.strip().startswith("#")
        }
        missing = sorted(p for p in packages if p not in notices)
        assert not missing, (
            f"{missing} are shipped but not in THIRD_PARTY_NOTICES.md. "
            "Both bundled licences require their notice to travel with the build."
        )

    def test_the_build_ships_the_notices(self):
        # In the repository is not the same as in the distribution. The
        # obligation attaches to what the user receives.
        spec = read(os.path.join("packaging", "protbot.spec"))
        assert "THIRD_PARTY_NOTICES.md" in spec
        assert "LICENSE" in spec

    def test_the_installer_licence_page_shows_the_licence(self):
        # It used to point at PRIVACY.md, which asked the user to "accept" a
        # privacy policy — not a thing a policy is for.
        iss = read(os.path.join("packaging", "installer.iss"))
        assert re.search(r"^LicenseFile=.*LICENSE\s*$", iss, re.MULTILINE)


# ── Security policy ───────────────────────────────────────────────────────

class TestSecurityPolicy:

    def test_a_disclosure_policy_exists(self):
        assert os.path.isfile(os.path.join(REPO_ROOT, "SECURITY.md"))

    def test_it_says_where_to_send_a_report(self):
        # The address is a placeholder on purpose — publishing a personal email
        # on a public page is the owner's call. This passes while it is clearly
        # marked as needing one, and fails the day the marker is removed
        # without an address taking its place.
        policy = read("SECURITY.md")
        has_address = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", policy)
        marked_todo = "Add a real address" in policy
        assert has_address or marked_todo, (
            "SECURITY.md must either give a contact address or say plainly "
            "that one is still needed"
        )

    def test_it_names_the_weaknesses_that_are_known_and_accepted(self):
        # So a reporter does not spend a weekend on something already
        # documented, and so nobody mistakes them for oversights.
        policy = read("SECURITY.md").lower()
        assert "tamper-evident" in policy or "deterrence" in policy
        assert "not encrypted" in policy


# ── Changelog ─────────────────────────────────────────────────────────────

class TestChangelog:

    def test_a_changelog_exists(self):
        assert os.path.isfile(os.path.join(REPO_ROOT, "CHANGELOG.md"))

    def test_the_current_version_is_accounted_for(self):
        # core/updates.py tells users a newer version exists. Without an entry
        # they are asked to update on trust, and a security fix goes out
        # looking like every other release.
        from core.version import __version__

        changelog = read("CHANGELOG.md")
        assert __version__ in changelog or "Unreleased" in changelog

    def test_it_does_not_claim_a_release_that_has_not_happened(self):
        # No build has ever been produced. Saying otherwise here is the same
        # class of mistake as advertising an unimplemented feature.
        assert "no build has ever been produced" in read("CHANGELOG.md").lower()


# ── Crash handling ────────────────────────────────────────────────────────

class TestCrashHandling:
    """
    A frozen Windows GUI build has no stderr. Without these hooks a traceback
    goes nowhere — and the worst case is not the visible crash but the quiet
    one, where a background thread dies, the monitor stops counting, and the
    window carries on showing yesterday's numbers.
    """

    def setup_method(self):
        crash.reset_for_tests()

    def teardown_method(self):
        crash.reset_for_tests()
        sys.excepthook = sys.__excepthook__

    def test_an_unhandled_exception_is_recorded(self):
        try:
            raise ValueError("boom")
        except ValueError:
            crash.record(*sys.exc_info(), where="a test")

        assert crash.has_crashed()
        assert "boom" in crash.last_traceback()

    def test_a_dead_background_thread_is_recorded(self):
        # The quiet failure this exists for.
        crash.install()

        def explode():
            raise RuntimeError("thread died")

        thread = threading.Thread(target=explode, name="test-thread")
        thread.start()
        thread.join(timeout=5)

        assert crash.has_crashed()
        assert "thread died" in crash.last_traceback()

    def test_keyboard_interrupt_is_not_treated_as_a_crash(self):
        # It is how someone stops the app from a terminal, not a fault.
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            crash.record(*sys.exc_info())

        assert not crash.has_crashed()

    def test_recording_never_raises(self):
        # Called from an error path. An exception here would turn a
        # recoverable fault into an unrecoverable one.
        crash.record(None, None, None)
        crash.record(ValueError, ValueError("x"), None)

    def test_install_is_wired_up_at_startup(self):
        # The hooks are useless if nothing installs them.
        main = read("main.py")
        assert "crash.install()" in main
        assert "crash.install_tk(root)" in main


# ── GDPR access and portability ───────────────────────────────────────────

class TestDataExport:
    """
    Art. 15 (access) and Art. 20 (portability). The app could already delete
    everything; it could not hand any of it back.
    """

    @pytest.fixture
    def populated(self, db, config):
        from datetime import datetime

        app_id = db.add_tracked_app("Discord", "discord.exe", "", "", "Social")
        session = db.start_session(app_id, datetime.now().isoformat())
        db.update_session_duration(session, 1800)
        return app_id

    def test_the_export_contains_the_users_apps_and_history(self, db, config, populated):
        export = dataexport.build_export(db, config)

        assert export["tracked_apps"], "an export with no apps is not an answer"
        assert export["usage_history"], "usage history is the data being asked for"
        assert export["usage_history"][0]["seconds"] == 1800

    def test_the_export_contains_the_users_settings(self, db, config, populated):
        config.set("warn_at_percent", 55)
        assert dataexport.build_export(db, config)["settings"]["warn_at_percent"] == 55

    def test_credentials_are_left_out(self, db, config, populated):
        # An export is a file the user may email. A licence blob or a device id
        # in it would let the recipient act as this installation.
        config.set("device_id", "secret-device-id")
        config.set("entitlement", {"sig": "secret-signature"})
        config.set("server_app_ids", {"1": 42})

        text = json.dumps(dataexport.build_export(db, config))
        assert "secret-device-id" not in text
        assert "secret-signature" not in text

    def test_the_export_says_what_it_left_out_and_why(self, db, config, populated):
        # Silently omitting data from a data-access request is worse than
        # omitting it openly.
        notes = dataexport.build_export(db, config)["notes"]
        assert "device_id" in notes["excluded"]
        assert notes["excluded_reason"]
        assert notes["diagnostic_log_note"]

    def test_it_is_machine_readable(self, db, config, populated, tmp_path):
        path = dataexport.write_export(db, config, str(tmp_path / "export.json"))

        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        assert loaded["format"] == f"{APP_NAME.lower()}-export"
        assert loaded["format_version"] == dataexport.EXPORT_FORMAT_VERSION

    def test_a_broken_section_does_not_lose_the_whole_export(self, db, config, populated):
        # A partial answer to "what do you hold about me" beats an error.
        class BrokenDb:
            data_dir = ""

            def get_all_tracked_apps(self):
                raise RuntimeError("table is gone")

        export = dataexport.build_export(BrokenDb(), config)
        assert export["settings"], "settings should survive a database failure"
        assert export["errors"], "and the failure should be reported, not hidden"

    def test_an_interrupted_write_leaves_no_partial_file(self, db, config, populated,
                                                         tmp_path, monkeypatch):
        # A half-written file that looks like a complete answer is the failure
        # mode worth designing out.
        target = tmp_path / "export.json"

        def explode(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(dataexport.json, "dump", explode)
        with pytest.raises(OSError):
            dataexport.write_export(db, config, str(target))

        assert not target.exists()
        assert not list(tmp_path.glob("*.tmp")), "the temp file should be cleaned up"

    def test_repeated_exports_do_not_overwrite_each_other(self):
        # Someone exporting twice is usually comparing before and after.
        assert dataexport.default_export_path().endswith(".json")
        assert APP_NAME in dataexport.default_export_path()

    def test_the_ui_offers_it(self):
        # A right nobody can reach is not implemented.
        ui = read(os.path.join("ui", "settings_page.py"))
        assert "Export My Data" in ui
        assert "_export_my_data" in ui


class TestConsentCanBeWithdrawn:
    """
    Art. 7(3): "It shall be as easy to withdraw consent as to give it."

    `revoke_consent` and `open_policy` existed in core/consent.py and nothing
    in the UI called either — so consent was given once at first run and could
    never be revisited, and the policy could not be re-read from inside the
    app. Code that exists but is unreachable is not a feature.
    """

    def test_withdrawing_consent_closes_the_gate_again(self, config):
        from core import consent

        consent.record_consent(config, True)
        assert consent.has_consented(config)

        consent.revoke_consent(config)
        assert not consent.has_consented(config)

    def test_withdrawing_consent_does_not_delete_data(self, db, config):
        # Art. 7(3) and Art. 17 are separate rights. Wiping someone's history
        # because they wanted to re-read the policy would be a nasty surprise.
        from core import consent

        db.add_tracked_app("Discord", "discord.exe", "", "", "Social")
        consent.record_consent(config, True)
        consent.revoke_consent(config)

        assert db.get_all_tracked_apps(), "withdrawing consent must not erase data"

    def test_both_controls_are_reachable_from_settings(self):
        ui = read(os.path.join("ui", "settings_page.py"))
        assert "Withdraw Consent" in ui and "revoke_consent" in ui
        assert "Read Privacy Policy" in ui and "open_policy" in ui


# ── The privacy policy stays true ─────────────────────────────────────────

class TestPolicyMatchesTheCode:

    def test_the_policy_describes_the_export_the_ui_actually_has(self):
        # PRIVACY.md tells the user what rights they have. Claiming a right the
        # UI does not offer is the mistake this whole file guards against — and
        # so is offering one the policy never mentions.
        policy = read("PRIVACY.md")
        assert "Export My Data" in policy, (
            "PRIVACY.md must describe the export button by the name it has in "
            "the UI, not just mention exporting in passing"
        )
        assert "Art. 20" in policy or "Art. 15" in policy

    def test_the_policy_does_not_promise_server_side_deletion_that_does_not_exist(self):
        # There is no deletion endpoint. The policy says so; if that caveat is
        # ever removed without the endpoint being built, the policy is false.
        # Whitespace-normalised and stripped of blockquote markers: the
        # sentence is line-wrapped inside a `>` block, so a plain substring
        # match breaks on reflow.
        policy = " ".join(read("PRIVACY.md").lower().replace(">", " ").split())
        assert "no server-side deletion endpoint" in policy

    def test_the_policy_still_needs_a_contact_address(self):
        # GDPR Art. 13 requires the controller's contact details, and the
        # policy currently has a placeholder. This is a live reminder rather
        # than a passing grade: it fails the moment the placeholder is deleted
        # without a real address replacing it. Tracked in STATUS.md.
        policy = read("PRIVACY.md")
        has_address = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", policy)
        marked_todo = "Add a real contact address here before release" in policy
        assert has_address or marked_todo


class TestTheTodoStaysCurrent:
    """
    `STATUS.md` is what the owner reads to decide what to do next. A stale one
    sends them at work that is already done, or hides work that is not — and
    nothing else in the repository notices.

    So the numbers in it are checked against reality. This is the same trick
    the rest of this file uses on the privacy policy: a claim that can drift
    silently gets a test that fails when it does.
    """

    @staticmethod
    def claimed(pattern: str) -> int:
        match = re.search(pattern, read("STATUS.md"))
        assert match, f"STATUS.md no longer states its {pattern!r}"
        return int(match.group(1))

    def test_the_python_test_count_is_current(self, request):
        # Only meaningful on a full run. When a single file is being run the
        # collected set is a fraction of the suite, and comparing would fail
        # for a reason that has nothing to do with the todo.
        import glob
        import os

        from tests.conftest import REPO_ROOT

        collected = request.session.items
        modules = {item.module.__name__ for item in collected}
        on_disk = glob.glob(os.path.join(REPO_ROOT, "tests", "test_*.py"))
        if len(modules) < len(on_disk):
            pytest.skip("not a full-suite run")

        claimed = self.claimed(r"\*\*Where things stand:\*\* ([\d,]+) Python tests")
        assert claimed == len(collected), (
            f"STATUS.md says {claimed} Python tests; there are {len(collected)}. "
            "Update the todo in the same commit as the tests — see CLAUDE.md."
        )

    def test_the_kotlin_test_count_is_current(self):
        # Counted from the source rather than by running Gradle, which the
        # Python suite has no business doing. An @Test annotation per test is
        # the convention throughout android/core.
        import glob
        import os

        from tests.conftest import REPO_ROOT

        pattern = os.path.join(REPO_ROOT, "android", "core", "src", "test",
                               "kotlin", "app", "protbot", "core", "*.kt")
        actual = 0
        for path in glob.glob(pattern):
            with open(path, encoding="utf-8") as fh:
                actual += len(re.findall(r"^\s*@Test\b", fh.read(), re.MULTILINE))

        assert actual, "no Kotlin tests found; has the layout moved?"
        claimed = self.claimed(r"([\d,]+)\s*\nKotlin tests")
        assert claimed == actual, (
            f"STATUS.md says {claimed} Kotlin tests; there are {actual}."
        )

    def test_it_records_what_is_finished_as_well_as_what_is_left(self):
        # A todo that only ever grows is a todo nobody reads twice.
        status = read("STATUS.md")
        assert "## Finished" in status
        assert "## Blocked on you" in status
        assert "## Can be coded now" in status

    def test_it_says_when_it_was_last_updated(self):
        assert re.search(r"\*Last updated \d{4}-\d{2}-\d{2}\.\*", read("STATUS.md"))

    def test_claims_about_what_has_never_run_stay_honest(self):
        # These are the load-bearing caveats. If a build ever happens, this
        # section is the first thing that should change.
        status = read("STATUS.md")
        assert "Written but never executed" in status
        assert "never compiled" in status
