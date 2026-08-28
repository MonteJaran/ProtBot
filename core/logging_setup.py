"""
logging_setup.py - One place that decides where ProtBot's logs go.

Replaces the hand-rolled _log() in monitor.py, which had three problems:

  * No rotation and no size cap. One line per tracked app per poll, forever —
    roughly 29,000 lines a day with twenty apps on a 60-second interval.
  * Timestamps were %H:%M:%S with no date, so the log was useless for
    diagnosing anything spanning more than one day.
  * Everything was written unconditionally, so the file doubled as a plaintext
    behavioural record of every app the user opened.

Per-app poll detail now goes to DEBUG, which is off in a release build, and the
file is capped. Logging is opt-in noisy: WARNING by default, turned up only
when someone is actually chasing a bug.
"""

import logging
import logging.handlers
import os

LOG_FILENAME = "protbot.log"

# Two 512 KB files. Enough to see what happened before a crash, small enough
# that it never becomes a liability sitting in the user's profile.
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 1

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def log_paths(data_dir: str) -> list:
    """Every file this module may create, including rotated backups."""
    base = os.path.join(data_dir, LOG_FILENAME)
    return [base] + [f"{base}.{i}" for i in range(1, BACKUP_COUNT + 1)]


def configure(data_dir: str, level=None, force: bool = False) -> None:
    """
    Set up file logging under `data_dir`. Safe to call more than once.

    `level` defaults to the PROTBOT_LOG_LEVEL environment variable, or
    WARNING. Set PROTBOT_LOG_LEVEL=DEBUG to get the per-poll detail.
    """
    global _configured
    if _configured and not force:
        return

    if level is None:
        level = os.environ.get("PROTBOT_LOG_LEVEL", "WARNING").upper()
    if isinstance(level, str):
        level = getattr(logging, level, logging.WARNING)

    root = logging.getLogger("protbot")
    root.setLevel(level)
    root.propagate = False

    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    try:
        os.makedirs(data_dir, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(data_dir, LOG_FILENAME),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        root.addHandler(handler)
    except OSError:
        # An unwritable log directory must never stop the app from running.
        root.addHandler(logging.NullHandler())

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """A child logger. Call configure() first; this works regardless."""
    return logging.getLogger(f"protbot.{name}")
