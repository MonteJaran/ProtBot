"""
dataexport.py - Handing the user everything ProtBot holds about them.

The app could already delete everything (GDPR Art. 17). It could not hand any
of it back, which leaves two rights unimplemented:

  * **Art. 15, access** — a person may ask what you hold about them.
  * **Art. 20, portability** — and receive it "in a structured, commonly used
    and machine-readable format".

Those articles are written for controllers holding data on a server, and
ProtBot's data sits on the user's own disk, so the obligation is thin. But the
moment device sync is turned on there is a server holding usage keyed to a
device id, and "it's all local" stops being the whole answer. Building the
export locally is a morning's work; retrofitting it around a live server after
someone asks is not.

The format is JSON, not CSV. CSV cannot represent settings, or the fact that
an app has both a limit and a history, without becoming several files with an
undocumented relationship between them — and "machine-readable" means the
recipient can load it, not that it opens in a spreadsheet. `ui/processes_page`
already exports usage as CSV for people who want a spreadsheet; that is a
convenience, and this is the complete record.

Two things are deliberately excluded, both because including them would make
the export itself a hazard:

  * **The entitlement blob.** It is signed and machine-bound; a copy in a file
    the user might email is a licence key sitting in their outbox.
  * **The diagnostic log.** It is a plaintext record of every app opened, it
    can be megabytes, and it is already separately deletable. The export says
    where it is instead of inlining it.
"""

import json
import os
import tempfile
from datetime import date, datetime

from core.logging_setup import get_logger
from core.version import APP_NAME, __version__

log = get_logger("export")

EXPORT_FORMAT_VERSION = 1

# Settings that must never be copied into a file the user may share. Each is
# either a credential or points at one.
_EXCLUDED_SETTINGS = frozenset({
    "entitlement",     # signed licence blob, machine-bound
    "device_id",       # identifies this install to the sync server
    "device_token",    # the sync credential itself — see AUDIT SF-09
    "server_app_ids",  # meaningless without the device id, and tied to it
})


def build_export(db, config, now=None) -> dict:
    """
    Everything ProtBot holds, as a plain dict.

    Separated from writing it so the contents can be tested without a
    filesystem — and so a caller that wants to show the user what is in it
    before saving can do that.

    Each section degrades independently: if the tracked-app table cannot be
    read, the export still carries the settings and says what failed, rather
    than producing nothing. A partial answer to "what do you hold about me" is
    worth more than an error dialog.
    """
    moment = now if isinstance(now, datetime) else datetime.now()
    export = {
        "format": f"{APP_NAME.lower()}-export",
        "format_version": EXPORT_FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": moment.isoformat(timespec="seconds"),
        "errors": [],
    }

    def section(name, fn, default):
        try:
            return fn()
        except Exception as e:
            log.error("Could not export %s: %s", name, e)
            export["errors"].append(f"{name}: {e}")
            return default

    export["settings"] = section("settings", lambda: _settings(config), {})
    export["tracked_apps"] = section(
        "tracked apps", lambda: [dict(row) for row in db.get_all_tracked_apps()], [],
    )
    export["usage_history"] = section(
        "usage history", lambda: _usage_history(db), [],
    )
    export["notes"] = _notes(db)
    return export


def _settings(config) -> dict:
    """The user's settings, minus anything that is a credential."""
    raw = config.all() if hasattr(config, "all") else dict(getattr(config, "_data", {}))
    return {k: v for k, v in raw.items() if k not in _EXCLUDED_SETTINGS}


def _usage_history(db) -> list:
    """
    Every recorded session, newest day first.

    Read through the database's own accessor rather than a fresh query, so an
    export cannot drift from what the rest of the app considers the schema.
    """
    rows = []
    for app in db.get_all_tracked_apps():
        app_id = app["id"]
        for day in db.get_usage_history(app_id, days=36500):   # ~100 years: all of it
            rows.append({
                "app_id": app_id,
                "app_name": app["name"],
                "date": day["date"],
                "seconds": int(day["total_sec"]),
            })
    rows.sort(key=lambda r: (r["date"], r["app_name"]), reverse=True)
    return rows


def _notes(db) -> dict:
    """Where to find the things deliberately left out of the file."""
    data_dir = getattr(db, "data_dir", "")
    return {
        "excluded": sorted(_EXCLUDED_SETTINGS),
        "excluded_reason": (
            "Licence and sync credentials are left out on purpose: an export "
            "is a file you might send to someone, and these would let them "
            "act as this installation."
        ),
        "diagnostic_log": os.path.join(data_dir, "protbot.log") if data_dir else "",
        "diagnostic_log_note": (
            "Not included here. It is a plaintext record of every app opened "
            "and can be large; delete it from Settings, or open the file "
            "directly."
        ),
    }


def write_export(db, config, path: str, now=None) -> str:
    """
    Write the export to `path`. Returns the path written.

    Written to a temporary file in the same directory and then moved into
    place, so an interrupted export cannot leave a half-written file that
    looks like a complete answer to a data request.
    """
    export = build_export(db, config, now=now)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)

    handle, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(export, fh, indent=2, ensure_ascii=False, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise

    log.info("Exported %d app(s) and %d usage row(s) to %s",
             len(export.get("tracked_apps", [])),
             len(export.get("usage_history", [])), path)
    return path


def default_export_path(directory: str = "", now=None) -> str:
    """
    A dated filename, so repeated exports do not overwrite each other.

    Someone exporting twice is usually comparing before and after, and
    silently replacing the first file is the wrong answer to that.
    """
    today = (now or date.today())
    if isinstance(today, datetime):
        today = today.date()
    name = f"{APP_NAME}_data_export_{today.isoformat()}.json"
    return os.path.join(directory or os.path.expanduser("~"), name)
