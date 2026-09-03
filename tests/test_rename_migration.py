"""
The FocusGuard → ProtBot data migration.

The app shipped as FocusGuard and stored everything in
%LOCALAPPDATA%\\FocusGuard. Renaming without moving that data would silently
abandon a user's entire history behind a folder they have no reason to look in
— the app would start empty and they would assume it broke.
"""

import json
import os

from core import paths
from core.config import Config
from core.database import DB_FILENAME, LEGACY_DB_FILENAME, Database
from core.version import APP_NAME


def make_legacy(root, filename="focusguard.db", content=b"legacy"):
    legacy = os.path.join(root, "FocusGuard")
    os.makedirs(legacy, exist_ok=True)
    with open(os.path.join(legacy, filename), "wb") as fh:
        fh.write(content)
    return legacy


# ── Naming ────────────────────────────────────────────────────────────────────

def test_the_app_is_named_protbot():
    assert APP_NAME == "ProtBot"


def test_the_legacy_name_is_preserved():
    """
    This constant is historical. Renaming it along with the app would silently
    break the only path by which existing data is found.
    """
    assert paths.LEGACY_APP_NAME == "FocusGuard"
    assert Database and LEGACY_DB_FILENAME == "focusguard.db"
    assert DB_FILENAME == "protbot.db"


def test_the_data_directory_uses_the_new_name():
    assert paths.data_dir().endswith("ProtBot")
    assert paths.legacy_data_dir().endswith("FocusGuard")


# ── Moving the directory ──────────────────────────────────────────────────────

def test_legacy_data_is_moved(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = make_legacy(str(tmp_path))

    assert paths.migrate_legacy_data() == "migrated"

    target = os.path.join(str(tmp_path), "ProtBot")
    assert os.path.isfile(os.path.join(target, "focusguard.db"))
    assert not os.path.exists(legacy)


def test_every_file_comes_across(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = make_legacy(str(tmp_path))
    for name in ("config.json", "focusguard.log", "focusguard.log.1"):
        with open(os.path.join(legacy, name), "w", encoding="utf-8") as fh:
            fh.write("data")

    paths.migrate_legacy_data()

    target = os.path.join(str(tmp_path), "ProtBot")
    for name in ("focusguard.db", "config.json", "focusguard.log",
                 "focusguard.log.1"):
        assert os.path.isfile(os.path.join(target, name)), name


def test_nothing_to_migrate_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.migrate_legacy_data() == "nothing-to-do"


def test_existing_protbot_data_is_never_overwritten(tmp_path, monkeypatch):
    """
    If the user has already run the renamed build, that data is newer and must
    win. Merging the old folder over it would lose their recent history.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(str(tmp_path), content=b"old")

    target = os.path.join(str(tmp_path), "ProtBot")
    os.makedirs(target)
    with open(os.path.join(target, "protbot.db"), "wb") as fh:
        fh.write(b"new")

    assert paths.migrate_legacy_data() == "skipped"
    with open(os.path.join(target, "protbot.db"), "rb") as fh:
        assert fh.read() == b"new"
    assert os.path.isdir(os.path.join(str(tmp_path), "FocusGuard"))


def test_an_empty_protbot_directory_does_not_block_migration(tmp_path, monkeypatch):
    """A previous launch may have created the folder before anything ran."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(str(tmp_path))
    os.makedirs(os.path.join(str(tmp_path), "ProtBot"), exist_ok=True)

    assert paths.migrate_legacy_data() == "migrated"


def test_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(str(tmp_path))

    assert paths.migrate_legacy_data() == "migrated"
    assert paths.migrate_legacy_data() == "nothing-to-do"


def test_a_failed_rename_falls_back_to_copying(tmp_path, monkeypatch):
    """
    os.rename fails across filesystems, and on Windows if a file is still open.
    The old data must survive that.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = make_legacy(str(tmp_path))

    def no_rename(*_a, **_kw):
        raise OSError("cross-device link")

    monkeypatch.setattr(paths.os, "rename", no_rename)

    assert paths.migrate_legacy_data() == "renamed-failed-copied"
    target = os.path.join(str(tmp_path), "ProtBot")
    assert os.path.isfile(os.path.join(target, "focusguard.db"))
    assert os.path.isdir(legacy), "the original must be left intact"


def test_migration_never_raises(tmp_path, monkeypatch):
    """A failed migration must not stop the app from launching."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    make_legacy(str(tmp_path))

    def boom(*_a, **_kw):
        raise OSError("denied")

    monkeypatch.setattr(paths.os, "rename", boom)
    monkeypatch.setattr(paths.shutil, "copytree", boom)

    assert paths.migrate_legacy_data() == "skipped"
    assert paths.ensure_data_dir().endswith("ProtBot")


# ── The database file inside it ───────────────────────────────────────────────

def test_the_legacy_database_file_is_adopted(data_dir):
    """
    Moving the folder does not rename the file inside it. An install that
    upgrades must keep using its existing history, not start a fresh database.
    """
    os.makedirs(data_dir, exist_ok=True)
    legacy_path = os.path.join(data_dir, LEGACY_DB_FILENAME)

    seed = Database(data_dir=data_dir)
    seed.add_tracked_app("Chrome", "chrome.exe")
    seed.close()
    os.replace(os.path.join(data_dir, DB_FILENAME), legacy_path)

    db = Database(data_dir=data_dir)
    try:
        assert [a["name"] for a in db.get_all_tracked_apps()] == ["Chrome"]
        assert os.path.isfile(os.path.join(data_dir, DB_FILENAME))
    finally:
        db.close()


def test_a_new_install_uses_the_new_filename(data_dir):
    db = Database(data_dir=data_dir)
    try:
        assert os.path.isfile(os.path.join(data_dir, DB_FILENAME))
        assert not os.path.exists(os.path.join(data_dir, LEGACY_DB_FILENAME))
    finally:
        db.close()


def test_an_existing_protbot_database_is_not_replaced(data_dir):
    """If both files exist, the current one wins."""
    os.makedirs(data_dir, exist_ok=True)
    current = Database(data_dir=data_dir)
    current.add_tracked_app("Keep me", "keep.exe")
    current.close()

    with open(os.path.join(data_dir, LEGACY_DB_FILENAME), "wb") as fh:
        fh.write(b"not a database")

    db = Database(data_dir=data_dir)
    try:
        assert [a["name"] for a in db.get_all_tracked_apps()] == ["Keep me"]
    finally:
        db.close()


# ── Config carries over ───────────────────────────────────────────────────────

def test_settings_survive_the_rename(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = make_legacy(str(tmp_path))
    with open(os.path.join(legacy, "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"poll_interval": 42, "device_id": "keep-this"}, fh)

    config = Config()
    assert config.get("poll_interval") == 42
    assert config.get("device_id") == "keep-this"


# ── Old log names still get deleted ───────────────────────────────────────────

def test_delete_all_data_removes_pre_rename_logs(data_dir):
    db = Database(data_dir=data_dir)
    try:
        for name in ("monitor.log", "focusguard.log", "focusguard.log.1"):
            with open(os.path.join(data_dir, name), "w", encoding="utf-8") as fh:
                fh.write("usage history")

        assert db.delete_log_file() is True
        for name in ("monitor.log", "focusguard.log", "focusguard.log.1"):
            assert not os.path.exists(os.path.join(data_dir, name)), name
    finally:
        db.close()


# ── Nothing left behind ───────────────────────────────────────────────────────

def test_no_user_facing_text_still_says_the_old_name():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    allowed = {
        "core/paths.py",          # LEGACY_APP_NAME, by design
        "core/database.py",       # LEGACY_DB_FILENAME and old log names
        "tests/test_rename_migration.py",
    }

    # Build output holds copies of the source. The project is installable now,
    # so `python -m build` leaves one behind, and scanning it reports every
    # file twice under a path no exemption matches.
    generated = {".git", "build", "dist", "__pycache__", ".venv", "venv",
                 ".pytest_cache", ".ruff_cache"}

    offenders = []
    for path in list(repo_root.rglob("*.py")) + list(repo_root.rglob("*.iss")):
        rel = path.relative_to(repo_root).as_posix()
        if generated & set(rel.split("/")) or rel in allowed:
            continue
        if "focusguard" in path.read_text(encoding="utf-8").lower():
            offenders.append(rel)

    assert offenders == [], f"still mention the old name: {offenders}"
