"""
theme.py - One palette, in one place, with the contrast checked by tests.

AUDIT ST-06 asked for three things beyond DPI awareness and a 10pt floor:
colours moved into a theme module, a high-contrast mode, and controls that are
reachable and visibly focused from the keyboard. This file is the first two,
and it is what makes the third possible — a focus ring needs a colour that is
guaranteed to stand out, and "guaranteed" means measured.

The European Accessibility Act (Directive (EU) 2019/882) has applied to
consumer software since 28 June 2025. Its technical yardstick in practice is
EN 301 549, which for a desktop UI points at WCAG 2.1 level AA. Two of those
success criteria are about colour and are the ones a hand-written palette
fails silently:

  * **1.4.3 Contrast (Minimum)** — text needs 4.5:1 against its background;
    large text (18pt, or 14pt bold) needs 3:1.
  * **1.4.11 Non-text Contrast** — the *boundary* of a control needs 3:1
    against what is next to it, so a button is distinguishable as a button.

## Why this is a module and not nine constants in six files

The palette used to be copy-pasted at the top of `app.py`, `devices_page.py`,
`files_page.py`, `insights_page.py`, `processes_page.py` and
`settings_page.py`. Six copies is not merely repetitive — it is what made a
high-contrast mode impossible to add, because there was no single thing to
swap. It also meant nobody could check the contrast, because there was no
single thing to check.

Measuring the old palette turned up four real failures at ordinary text sizes:
secondary text on the darkest surface (3.98:1), the accent colour used as text
(4.15:1), white on the accent-filled button (3.83:1), and the danger button's
text on its own fill (3.62:1). None of them look obviously wrong; that is what
a test is for.

## Two roles the old palette gave one colour

`ACCENT` was both a fill (behind white button text) and a text colour (on a
dark page). One value cannot do both: dark enough for white text on top is too
dark to read as text itself. They are separate here — `ACCENT` fills,
`ACCENT_TEXT` is read — and `tests/test_accessibility.py` holds each to the
threshold for the job it actually does.

Control boundaries are carried by `BORDER` rather than by the fills, which is
why the fills are free to be brand colours. A border that meets 3:1 against
every surface a control can sit on satisfies 1.4.11 regardless of what is
inside it.

## Choosing the palette

Read once, when this module is first imported, because the pages bind their
colours at import time and there is no earlier moment. Changing the setting
therefore needs a restart, which the Settings page says. The config file is
read directly rather than through `core.config.Config`: constructing one has
side effects — it writes the file back — and a theme module should not be able
to change a user's settings by being imported.
"""

from __future__ import annotations

import json
import os

# Every colour role, and what it is for. A page should never need a hex
# literal; if one of these does not fit, the answer is a new role here rather
# than a colour inline, so the contrast tests keep covering it.
DARK: dict[str, str] = {
    "BG": "#1a1a2e",           # the page
    "BG2": "#16213e",          # cards and raised surfaces
    "BG3": "#0f3460",          # headers, status bars, the deepest surface
    "ACCENT": "#c0304a",       # a filled button. Darkened so white text on it
                               # reaches 4.5:1 — the old #e94560 gave 3.83:1.
    "ACCENT_HOVER": "#cf4059",  # ACCENT under the pointer: lighter, still 4.6:1
                               # under white text
    "ACCENT_TEXT": "#f26177",  # the same brand colour, as text on a dark page
    "ON_ACCENT": "#ffffff",    # text on ACCENT
    "TEXT": "#e0e0e0",         # body text
    "TEXT2": "#a8a8b8",        # secondary text. Was #9090a0, which fell to
                               # 3.98:1 on BG3.
    "TEXT3": "#8f8fa0",        # deliberately dimmed: "planned", not available
    "SUCCESS": "#4ade80",
    "WARNING": "#fbbf24",
    "ERROR": "#f87171",
    "DANGER_BG": "#7f1d1d",    # destructive button fill
    "DANGER_HOVER": "#8f1f1f",  # and under the pointer, lighter by the same logic
    "ON_DANGER": "#fca5a5",    # text on DANGER_BG. Was #f87171 at 3.62:1.
    "BORDER": "#8892a4",       # control outlines — this is what carries 1.4.11
    "FOCUS": "#7dd3fc",        # the keyboard focus ring
}

# Not "the dark palette with more contrast" — a different set of decisions.
# Backgrounds go to true black so the ratios have the whole range to work with,
# and the brand colour stops being decorative: it is dark enough to sit under
# white text and nothing else.
HIGH_CONTRAST: dict[str, str] = {
    "BG": "#000000",
    "BG2": "#0d0d0d",
    "BG3": "#1f1f1f",
    "ACCENT": "#8a1128",
    "ACCENT_HOVER": "#a3152f",
    "ACCENT_TEXT": "#ff8fa3",
    "ON_ACCENT": "#ffffff",
    "TEXT": "#ffffff",
    "TEXT2": "#e6e6e6",
    "TEXT3": "#cccccc",
    "SUCCESS": "#5cff9d",
    "WARNING": "#ffd21f",
    "ERROR": "#ff9d9d",
    "DANGER_BG": "#5c0f0f",
    "DANGER_HOVER": "#7a1414",
    "ON_DANGER": "#ffd6d6",
    "BORDER": "#d9d9d9",
    "FOCUS": "#00e5ff",
}

PALETTES: dict[str, dict[str, str]] = {
    "dark": DARK,
    "high-contrast": HIGH_CONTRAST,
}

DEFAULT_PALETTE = "dark"

# WCAG 2.1 thresholds.
AA_NORMAL_TEXT = 4.5
AA_LARGE_TEXT = 3.0
AA_NON_TEXT = 3.0

# The contract every palette is held to. Each entry is
# (foreground, background, minimum, why) — the "why" is what a failure prints,
# because a bare ratio does not tell you which screen went wrong.
#
# Surface-on-surface pairs are deliberately absent. BG3 against BG is a card
# on a page: grouping, not a control, and 1.4.11 is about controls. What makes
# a control distinguishable here is BORDER, which is checked against every
# surface one can sit on.
CONTRAST_REQUIREMENTS: tuple[tuple[str, str, float, str], ...] = (
    ("TEXT", "BG", AA_NORMAL_TEXT, "body text on the page"),
    ("TEXT", "BG2", AA_NORMAL_TEXT, "body text on a card"),
    ("TEXT", "BG3", AA_NORMAL_TEXT, "body text on a header"),
    ("TEXT2", "BG", AA_NORMAL_TEXT, "secondary text on the page"),
    ("TEXT2", "BG2", AA_NORMAL_TEXT, "card subtitles"),
    ("TEXT2", "BG3", AA_NORMAL_TEXT, "the status bar"),
    ("TEXT3", "BG", AA_NORMAL_TEXT, "dimmed 'planned' text"),
    ("TEXT3", "BG2", AA_NORMAL_TEXT, "dimmed text on a card"),
    ("ACCENT_TEXT", "BG", AA_NORMAL_TEXT, "section headings"),
    ("ACCENT_TEXT", "BG2", AA_NORMAL_TEXT, "accent text on a card"),
    ("SUCCESS", "BG", AA_NORMAL_TEXT, "an 'under limit' figure"),
    ("SUCCESS", "BG2", AA_NORMAL_TEXT, "an 'under limit' figure on a card"),
    ("WARNING", "BG", AA_NORMAL_TEXT, "an 'approaching limit' figure"),
    ("WARNING", "BG2", AA_NORMAL_TEXT, "an 'approaching limit' figure on a card"),
    ("ERROR", "BG", AA_NORMAL_TEXT, "an 'over limit' figure"),
    ("ERROR", "BG2", AA_NORMAL_TEXT, "an 'over limit' figure on a card"),
    ("ON_ACCENT", "ACCENT", AA_NORMAL_TEXT, "the label on a primary button"),
    # Hover states are not exempt. A button whose label becomes unreadable the
    # moment the pointer is over it is unreadable exactly when it is being read.
    ("ON_ACCENT", "ACCENT_HOVER", AA_NORMAL_TEXT, "a primary button under the pointer"),
    ("ON_DANGER", "DANGER_BG", AA_NORMAL_TEXT, "the label on a destructive button"),
    ("ON_DANGER", "DANGER_HOVER", AA_NORMAL_TEXT,
     "a destructive button under the pointer"),
    ("BORDER", "BG", AA_NON_TEXT, "a control outlined against the page"),
    ("BORDER", "BG2", AA_NON_TEXT, "a control outlined on a card"),
    ("BORDER", "BG3", AA_NON_TEXT, "a control outlined on a header"),
    ("FOCUS", "BG", AA_NON_TEXT, "the focus ring on the page"),
    ("FOCUS", "BG2", AA_NON_TEXT, "the focus ring on a card"),
    ("FOCUS", "BG3", AA_NON_TEXT, "the focus ring on a header"),
)


def relative_luminance(colour: str) -> float:
    """
    WCAG 2.1 relative luminance of an #rrggbb colour.

    The sRGB transfer function, not a simple average: the eye is far more
    sensitive to green than to blue, and averaging the channels rates yellow
    and blue as equally bright. That is the mistake that produces a palette
    which looks contrasty to its author and is unreadable to anyone else.
    """
    text = colour.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"{colour!r} is not an #rrggbb colour")

    channels = []
    for index in (0, 2, 4):
        value = int(text[index:index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045
                        else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """
    The WCAG contrast ratio between two colours, from 1.0 to 21.0.

    Symmetric by construction — the brighter of the two goes on top — so a
    caller cannot get a different answer by passing the arguments the other
    way round.
    """
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def check_palette(palette: dict[str, str]) -> list[str]:
    """
    Every requirement this palette fails, as readable sentences.

    Returns a list rather than raising: a caller wants all of them, not the
    first. An empty list means the palette meets WCAG AA everywhere the app
    actually puts one colour on another.
    """
    problems = []
    for foreground, background, minimum, why in CONTRAST_REQUIREMENTS:
        if foreground not in palette or background not in palette:
            problems.append(f"missing colour: {foreground} or {background}")
            continue
        ratio = contrast_ratio(palette[foreground], palette[background])
        if ratio < minimum:
            problems.append(
                f"{foreground} on {background} ({why}) is {ratio:.2f}:1, "
                f"below the {minimum}:1 minimum"
            )
    return problems


def palette_for(name: str) -> dict[str, str]:
    """The named palette, or the default if the name is not one we ship."""
    return dict(PALETTES.get(str(name or "").strip().lower(),
                             PALETTES[DEFAULT_PALETTE]))


def selected_name(config=None) -> str:
    """
    Which palette the user has chosen.

    Accepts a Config when a caller has one — the Settings page does — and
    otherwise reads the file directly. Never raises: a damaged config must
    give the user a readable window to fix it in, not a crash before any
    window exists.
    """
    try:
        if config is not None:
            raw = config.get("theme", DEFAULT_PALETTE)
        else:
            raw = _read_theme_setting()
    except Exception:
        return DEFAULT_PALETTE
    name = str(raw or "").strip().lower()
    return name if name in PALETTES else DEFAULT_PALETTE


def _read_theme_setting() -> str:
    """
    The theme name from config.json, read without constructing a Config.

    Config() writes the file back on load, and importing a theme module is not
    a moment at which a user's settings should change on disk.
    """
    from core.paths import data_dir

    path = os.path.join(data_dir(), "config.json")
    if not os.path.isfile(path):
        return DEFAULT_PALETTE
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("theme", DEFAULT_PALETTE) if isinstance(data, dict) else DEFAULT_PALETTE


# ── The active palette ────────────────────────────────────────────────────
# Bound once, here, because the pages import these names at module load and
# there is no earlier point to choose. Changing the setting takes effect at
# the next start, which is what the Settings page tells the user.

ACTIVE_NAME = selected_name()
ACTIVE = palette_for(ACTIVE_NAME)

BG = ACTIVE["BG"]
BG2 = ACTIVE["BG2"]
BG3 = ACTIVE["BG3"]
ACCENT = ACTIVE["ACCENT"]
ACCENT_HOVER = ACTIVE["ACCENT_HOVER"]
ACCENT_TEXT = ACTIVE["ACCENT_TEXT"]
ON_ACCENT = ACTIVE["ON_ACCENT"]
TEXT = ACTIVE["TEXT"]
TEXT2 = ACTIVE["TEXT2"]
TEXT3 = ACTIVE["TEXT3"]
SUCCESS = ACTIVE["SUCCESS"]
WARNING = ACTIVE["WARNING"]
ERROR = ACTIVE["ERROR"]
DANGER_BG = ACTIVE["DANGER_BG"]
DANGER_HOVER = ACTIVE["DANGER_HOVER"]
ON_DANGER = ACTIVE["ON_DANGER"]
BORDER = ACTIVE["BORDER"]
FOCUS = ACTIVE["FOCUS"]
