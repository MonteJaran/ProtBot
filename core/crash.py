"""
crash.py - Catching what would otherwise disappear.

Python's default behaviour for an unhandled exception is to print a traceback
to stderr and exit. A frozen Windows GUI app has no stderr: PyInstaller builds
it with no console, so the traceback goes nowhere and the process vanishes.
The user sees ProtBot close on its own and has nothing to send you.

Worse than the crash is the *silent* case. Tkinter catches exceptions raised
in callbacks, prints them, and keeps running — so a broken button prints to a
console nobody has and the window stays open looking fine. And an exception on
a background thread kills only that thread: the monitor stops counting, limits
stop being enforced, and the window still shows yesterday's numbers as if
nothing happened. That is the failure this module exists for.

Three hooks, because Python has three separate paths and each defaults to
losing the error:

    sys.excepthook            the main thread
    threading.excepthook      any other thread          (3.8+)
    Tk.report_callback_exception   anything inside a widget callback

All three land in the same place: the rotating log file, with a marker the
user can be pointed at. KeyboardInterrupt is passed through untouched — it is
how someone stops the app from a terminal, not a fault.
"""

import sys
import threading
import traceback

from core.logging_setup import get_logger

log = get_logger("crash")

# Set when anything has been caught, so the UI can offer to open the log
# rather than the user having to know it exists.
_crashed = threading.Event()

# The most recent traceback, for the dialog. One is enough: the first failure
# is the useful one, and keeping every traceback in memory in an app that is
# already misbehaving is not a good trade.
_last_traceback = ""
_lock = threading.RLock()


def has_crashed() -> bool:
    """True if any unhandled exception has been recorded this session."""
    return _crashed.is_set()


def last_traceback() -> str:
    with _lock:
        return _last_traceback


def record(exc_type, exc_value, exc_tb, where: str = "") -> None:
    """
    Log one unhandled exception.

    Never raises. This is called *from* an error path, and an exception here
    would replace a recoverable fault with an unrecoverable one — the classic
    way a crash handler makes things worse than the crash.
    """
    if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        with _lock:
            global _last_traceback
            _last_traceback = text
        _crashed.set()
        log.critical("Unhandled exception%s:\n%s",
                     f" in {where}" if where else "", text)
    except Exception:
        # Absolutely last resort. If logging itself is broken there is nowhere
        # left to put this, and swallowing it is better than a recursive crash.
        pass


def install(root=None) -> None:
    """
    Route every unhandled exception into the log.

    Call once at startup, as early as possible — before the database opens and
    before the monitor starts, so a failure in either is captured rather than
    lost. Pass the Tk root once it exists to cover widget callbacks too.
    """
    sys.excepthook = lambda exc_type, exc_value, exc_tb: record(
        exc_type, exc_value, exc_tb, where="the main thread",
    )

    def _thread_hook(args) -> None:
        # A dead background thread is the quiet failure this is really for:
        # the monitor stops counting and the window keeps showing old numbers.
        name = getattr(args.thread, "name", "a background thread")
        record(args.exc_type, args.exc_value, args.exc_traceback,
               where=f"thread '{name}'")

    threading.excepthook = _thread_hook

    if root is not None:
        install_tk(root)


def install_tk(root) -> None:
    """
    Route Tkinter callback errors into the log as well.

    Tk catches these itself and prints them, which in a frozen build means
    discarding them. Overriding the hook is the documented way to intervene.
    """
    def _report(exc_type, exc_value, exc_tb) -> None:
        record(exc_type, exc_value, exc_tb, where="a window callback")

    try:
        root.report_callback_exception = _report
    except Exception as e:
        log.warning("Could not install the Tk exception hook: %s", e)


def reset_for_tests() -> None:
    """Clear recorded state. Only for tests, which run many cases in one process."""
    global _last_traceback
    with _lock:
        _last_traceback = ""
    _crashed.clear()
