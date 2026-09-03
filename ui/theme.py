"""
theme.py - The app's colour palette, and the high-contrast alternative to it.

AUDIT ST-06: "hardcoded hex colors with no high-contrast mode." Every page
(`ui/*_page.py`, `ui/app.py`) defined the same nine colours as its own
module-level literals — safe while there was only one palette, a problem the
moment there are two, because "add a second palette" would otherwise mean
finding and editing the same nine lines in six files and keeping them in
sync by hand. This module is the fix: the one place those nine colours are
defined, in both variants.

Two things this deliberately does not do:

  * **It does not touch the "extra" colours a couple of pages define for
    themselves** (`TEXT3`, `GOLD`, `PURPLE`, `CYAN` — used for a dimmed
    label, chart accents, that sort of thing) in *normal* mode. Those already
    differ slightly between the files that have them, are decorative rather
    than load-bearing for legibility, and unifying them was not what anyone
    asked for — so normal mode is pixel-for-pixel what it was before this
    file existed. `apply_to_modules` below does give them a single, verified
    value in *high-contrast* mode, because the reason those pages get to
    each pick their own shade — a bit of designer variety — is exactly the
    thing high-contrast mode exists to remove.
  * **It is a startup decision, not a live one.** Tk bakes a colour into a
    widget at the moment `bg=`/`fg=` is passed to its constructor; there is
    no general "re-theme everything already on screen" operation short of
    tearing down and rebuilding the whole window. So the Settings toggle
    that reads `config.get("high_contrast")` takes effect on the next
    launch, and says so, rather than promising something this would not
    actually do live.

## How re-theming six independent modules works without editing six modules

Every page's widget-construction code reads its colours as bare names —
`bg=BG`, `fg=ACCENT` — which Python resolves as a lookup in that *module's*
global namespace at the moment the widget is built, not at import time or
function-definition time. So `apply_to_modules()` does not need to touch a
single widget call: it reassigns the name directly on each already-imported
page module (`devices_page.BG = "#000000"`, and so on) before that page's
`__init__` runs, and every widget it goes on to build reads the new value
the normal way. `tests/test_theme.py::TestModuleGlobalRebindingWorks` pins
this down against a throwaway module rather than trusting the explanation.
"""

# No tkinter import at module level: contrast_ratio() and colors() are pure
# and are exercised directly by tests/test_theme.py, which runs in the same
# interpreter as the rest of the suite — one that has no tkinter (see
# CLAUDE.md). Only apply_to_modules() touches Tk, and only inside the
# function body, deferred, the same way the rest of this codebase imports
# tkinter-dependent things lazily from otherwise-pure modules.

# ── The two palettes ─────────────────────────────────────────────────────

# Unchanged from what every page already had — this is that literal block,
# moved rather than rewritten. See the module docstring for why the four
# page-specific "extra" names are not here.
NORMAL = {
    "BG":      "#1a1a2e",
    "BG2":     "#16213e",
    "BG3":     "#0f3460",
    "ACCENT":  "#e94560",
    "TEXT":    "#e0e0e0",
    "TEXT2":   "#9090a0",
    "SUCCESS": "#4ade80",
    "WARNING": "#fbbf24",
    "ERROR":   "#f87171",
}

# The same nine values, also as bare names — `from ui.theme import BG` is
# what every page does (see the module docstring), and `from X import Y`
# needs Y to exist as a plain attribute of X. Each page's own copy of the
# name is what apply_to_modules() later overwrites; these starting values on
# this module are what every copy begins as, always NORMAL's, since a page
# that somehow ran before apply_to_modules() had a chance to run should look
# like the app always has rather than like nothing was ever set.
BG      = NORMAL["BG"]
BG2     = NORMAL["BG2"]
BG3     = NORMAL["BG3"]
ACCENT  = NORMAL["ACCENT"]
TEXT    = NORMAL["TEXT"]
TEXT2   = NORMAL["TEXT2"]
SUCCESS = NORMAL["SUCCESS"]
WARNING = NORMAL["WARNING"]
ERROR   = NORMAL["ERROR"]

# Verified against the WCAG formula in tests/test_theme.py, not chosen by
# eye: every one of these clears 4.5:1 (the AA threshold for normal-sized
# text) against all three backgrounds below, most by a wide margin — see
# TestHighContrastMeetsWCAG_AA for the exact numbers this is held to.
HIGH_CONTRAST = {
    "BG":      "#000000",
    "BG2":     "#0a0a0a",
    "BG3":     "#141414",
    "ACCENT":  "#ffcc00",
    "TEXT":    "#ffffff",
    "TEXT2":   "#e0e0e0",
    "SUCCESS": "#33ff66",
    "WARNING": "#ffcc00",
    "ERROR":   "#ff6666",
}

# The four page-specific extras. Not part of NORMAL (each page keeps its own
# literal there — see module docstring) but given one shared, verified value
# each for high-contrast mode, same reasoning as above.
EXTRA_HIGH_CONTRAST = {
    "TEXT3":  "#c0c0c0",
    "GOLD":   "#ffcc00",
    "PURPLE": "#e0b3ff",
    "CYAN":   "#80f0ff",
}

# A visible focus ring needs to be one colour everywhere, in both palettes —
# see ui/a11y.py, which is the only other module that reads this one.
FOCUS_RING = {
    "normal": "#e94560",         # == NORMAL["ACCENT"]
    "high_contrast": "#ffcc00",  # == HIGH_CONTRAST["ACCENT"]
}

# WCAG 2.1 success criterion 1.4.3. 4.5:1 for ordinary text; UI components
# and text above ~18pt (or 14pt bold) may use the lower 3:1 bar instead.
# Kept here, not inlined in tests, so a test asserting "clears AA" and this
# module's own docstring claim can never quietly drift apart.
AA_NORMAL_TEXT = 4.5
AA_LARGE_TEXT = 3.0

# Every module this applies to, and the names it is allowed to overwrite on
# each — deliberately a fixed list rather than "every uppercase name in the
# module", so this can never overwrite something that merely looks like a
# colour constant.
_CORE_NAMES = tuple(NORMAL.keys())
_EXTRA_NAMES = tuple(EXTRA_HIGH_CONTRAST.keys())
_THEMED_MODULES = (
    "ui.app",
    "ui.devices_page",
    "ui.files_page",
    "ui.insights_page",
    "ui.processes_page",
    "ui.settings_page",
)


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    """
    WCAG's contrast ratio between two colours, from 1.0 (identical) to 21.0
    (black on white). The formula, not an approximation of it — this is what
    a real contrast checker computes, so a value here means what it says.
    """
    l1, l2 = _luminance(hex1), _luminance(hex2)
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


def is_high_contrast(config) -> bool:
    """
    Whether the high-contrast palette is the active one.

    Never raises: a config that cannot answer this is not high-contrast,
    same as one that was never asked — a theme lookup must not be able to
    take the rest of the window down with it.
    """
    try:
        return bool(config.get("high_contrast", False))
    except Exception:
        return False


def colors(config) -> dict:
    """The nine core colours for the active palette, keyed by name."""
    return dict(HIGH_CONTRAST if is_high_contrast(config) else NORMAL)


def focus_ring_color(config) -> str:
    return FOCUS_RING["high_contrast" if is_high_contrast(config) else "normal"]


def apply_to_modules(config) -> None:
    """
    Re-point every page module's colour constants at the active palette.

    Call once, before any page is constructed — main.py / ui/app.py does
    this ahead of `_configure_style()` and every `*Page(...)` call. Safe to
    call more than once (idempotent) and safe to call in normal mode, where
    it is a no-op that reassigns each name to the value it already had.

    See the module docstring for why overwriting a bare module-level name
    reaches every widget that module goes on to build, with no per-widget
    change needed.
    """
    import importlib

    palette = colors(config)
    extra = EXTRA_HIGH_CONTRAST if is_high_contrast(config) else {}

    for module_name in _THEMED_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            # A page that fails to import is a problem main.py already
            # surfaces loudly elsewhere; theming it is not this function's
            # job to fail loudly over too.
            continue

        for name in _CORE_NAMES:
            if hasattr(module, name):
                setattr(module, name, palette[name])
        for name in _EXTRA_NAMES:
            if name in extra and hasattr(module, name):
                setattr(module, name, extra[name])
