"""
paths.py - Where ProtBot keeps its data, and the move from the old name.

The app shipped as ProtBot and stored everything in
%LOCALAPPDATA%\\ProtBot. Renaming without handling that would silently
abandon a user's entire history behind a folder they have no reason to look in
— the app would simply start empty and they would assume it broke.

migrate_legacy_data() moves the old directory across on first run. It is
conservative in both directions: it never overwrites an existing ProtBot
directory, and it never deletes the old one if the move fails.
"""

import os
import shutil

from core.version import APP_NAME

# The name this app used to ship under. This is a HISTORICAL constant and must
# never be renamed along with the app — it is the only way an upgrade finds the
# user's existing data.
LEGACY_APP_NAME = "FocusGuard"


def _base_dir() -> str:
    """%LOCALAPPDATA% on Windows, the home directory anywhere else."""
    return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


def data_dir() -> str:
    return os.path.join(_base_dir(), APP_NAME)


def legacy_data_dir() -> str:
    return os.path.join(_base_dir(), LEGACY_APP_NAME)


def migrate_legacy_data(target: str = "", legacy: str = "") -> str:
    """
    Move data from the old ProtBot directory to the current one, once.

    Returns a short status: "migrated", "renamed-failed-copied", "skipped" or
    "nothing-to-do". Never raises — a failed migration must leave the user with
    a working app and their old data intact, not a crash on launch.
    """
    target = target or data_dir()
    legacy = legacy or legacy_data_dir()

    if os.path.abspath(target) == os.path.abspath(legacy):
        return "nothing-to-do"
    if not os.path.isdir(legacy):
        return "nothing-to-do"

    # Never merge into an existing directory: if the user has already run the
    # renamed build, that data is the newer of the two and must win.
    if os.path.isdir(target) and os.listdir(target):
        return "skipped"

    try:
        if os.path.isdir(target):
            os.rmdir(target)          # empty, created by an earlier launch
        os.rename(legacy, target)
        return "migrated"
    except OSError:
        pass

    # os.rename fails across filesystems, and on Windows if any file in the old
    # directory is still open. Copy instead, and leave the original alone.
    try:
        shutil.copytree(legacy, target, dirs_exist_ok=True)
        return "renamed-failed-copied"
    except OSError:
        return "skipped"


def ensure_data_dir() -> str:
    """The data directory, migrated if needed and guaranteed to exist."""
    target = data_dir()
    try:
        migrate_legacy_data(target)
    except Exception:
        # Migration is best effort. A new empty directory is a worse outcome
        # than a crash for nobody, but a crash on launch is worse than both.
        pass
    os.makedirs(target, exist_ok=True)
    return target
