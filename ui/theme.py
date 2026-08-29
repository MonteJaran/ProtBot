"""
theme.py - Colour palettes for ttk-styled chrome (AUDIT ST-06 remainder).

Two palettes: the app's normal dark theme, and a high-contrast one. Both feed
`_configure_style()` in app.py, the single place ttk.Style is configured for
the whole app -- tabs, buttons, entries, comboboxes, the treeview, scrollbars.

**What this does not cover.** Every page module (files_page.py,
processes_page.py, devices_page.py, insights_page.py, and the panels app.py
builds directly) draws its own body with plain tk.Frame/tk.Label widgets and
its own copy of the same colour constants, set once when that module is
imported -- not through ttk.Style, and not through this file. Re-theming
those would mean touching every one of those widget construction calls
individually across several hundred call sites, in code that cannot be
rendered or checked here (no display). Turning on high contrast recolours
the shared chrome -- the part a keyboard/screen-reader user actually
navigates through -- not the whole window. Said plainly rather than implied:
see STATUS.md.

Every pairing below that puts text on a background is checked against WCAG
2.1 AA (4.5:1, or 3:1 for the large/bold labels that qualify) by
tests/test_accessibility.py, which computes the ratios from these exact
values rather than trusting a comment. The default palette is NOT asserted
against AA -- it is the app's existing shipped theme, reproduced here
unchanged (same hex values as before this file existed) so turning high
contrast off is a true no-op, not a partial one.
"""


class Palette:
    """Named slots `_configure_style()` reads. See the module docstring for
    what each one feeds -- ON_ACCENT and the DANGER_BG pair exist because a
    fixed white-on-accent or a fixed dark-red literal, which is what the
    default theme hardcodes, stops being readable once ACCENT or ERROR
    change to a high-contrast colour."""

    def __init__(self, *, bg, bg2, bg3, text, text2,
                accent, on_accent, accent_active,
                error, danger_bg, danger_bg_active):
        self.BG = bg
        self.BG2 = bg2
        self.BG3 = bg3
        self.TEXT = text
        self.TEXT2 = text2
        self.ACCENT = accent
        self.ON_ACCENT = on_accent          # text/icon colour drawn on ACCENT
        self.ACCENT_ACTIVE = accent_active  # ACCENT's hover/pressed shade
        self.ERROR = error                  # Danger.TButton's foreground
        self.DANGER_BG = danger_bg
        self.DANGER_BG_ACTIVE = danger_bg_active

    # No SUCCESS/WARNING here: every ttk style _configure_style() defines
    # only ever reads BG/BG2/BG3/TEXT/TEXT2/ACCENT/ON_ACCENT/ACCENT_ACTIVE/
    # ERROR/DANGER_BG(_ACTIVE). SUCCESS and WARNING colours appear only in
    # each page module's own hand-drawn panels, which this file does not
    # reach -- see the module docstring. A field nothing reads would just be
    # a second, unenforced place for those numbers to drift.


# The app's existing theme, values unchanged from what app.py hardcoded
# before this file existed.
DEFAULT = Palette(
    bg='#1a1a2e', bg2='#16213e', bg3='#0f3460',
    text='#e0e0e0', text2='#9090a0',
    accent='#e94560', on_accent='#ffffff', accent_active='#c73652',
    error='#f87171', danger_bg='#7f1d1d', danger_bg_active='#991b1b',
)

# Near-black backgrounds, near-white text, and an accent chosen to clear
# 4.5:1 against black as text *and* against black as a button fill (ON_ACCENT
# is black, not the default's white -- white text on a light accent is
# exactly the kind of pairing that reads fine on the default's dark accent
# and fails on a bright high-contrast one). DANGER_BG drops to black rather
# than keeping the default's dark red, which does not clear 4.5:1 against a
# high-contrast ERROR red.
HIGH_CONTRAST = Palette(
    bg='#000000', bg2='#1a1a1a', bg3='#333333',
    text='#ffffff', text2='#e6e6e6',
    accent='#ffd400', on_accent='#000000', accent_active='#ffd400',
    error='#ff6e6e', danger_bg='#000000', danger_bg_active='#000000',
)


def palette(config) -> Palette:
    """Which palette the running app should style itself with."""
    try:
        enabled = bool(config.get("high_contrast", False))
    except Exception:
        enabled = False
    return HIGH_CONTRAST if enabled else DEFAULT


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """
    WCAG 2.1 relative-luminance contrast ratio between two sRGB colours.

    Exists so a test can compute the real number from the palette above
    instead of a comment asserting it. https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
    """

    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def luminance(hex_color: str) -> float:
        hex_color = hex_color.lstrip('#')
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    l1, l2 = luminance(hex_a), luminance(hex_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
