"""
Accessibility (AUDIT ST-06 remainder): keyboard navigation and the
high-contrast palette.

Nothing here can render a window (no display in CI) or drive a real screen
reader, so what these tests check is what actually can be checked without
one: the high-contrast palette's numbers are real WCAG contrast ratios, not
just plausible-looking hex, and every dialog that used to be dismissible
only by finding a button with the mouse now also responds to Escape. Read as
text, like the rest of this suite's checks on the ui/*.py modules it cannot
import.
"""

import os

import pytest

from tests.conftest import REPO_ROOT
from ui import theme


def read(*parts) -> str:
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── The high-contrast palette meets WCAG AA ─────────────────────────────────
#
# Only the HIGH_CONTRAST palette is asserted against AA. DEFAULT is the app's
# existing shipped theme, reproduced here unchanged -- fixing its contrast
# would be a different, unrequested change, and is not this file's job.

class TestHighContrastPaletteMeetsWcagAA:

    AA_NORMAL_TEXT = 4.5

    @pytest.mark.parametrize("fg,bg,label", [
        (theme.HIGH_CONTRAST.TEXT, theme.HIGH_CONTRAST.BG, "TEXT on BG"),
        (theme.HIGH_CONTRAST.TEXT, theme.HIGH_CONTRAST.BG2, "TEXT on BG2"),
        (theme.HIGH_CONTRAST.TEXT, theme.HIGH_CONTRAST.BG3, "TEXT on BG3"),
        (theme.HIGH_CONTRAST.TEXT2, theme.HIGH_CONTRAST.BG, "TEXT2 on BG"),
        (theme.HIGH_CONTRAST.TEXT2, theme.HIGH_CONTRAST.BG2, "TEXT2 on BG2"),
        (theme.HIGH_CONTRAST.ACCENT, theme.HIGH_CONTRAST.BG, "ACCENT on BG (Section.TLabel)"),
        (theme.HIGH_CONTRAST.ON_ACCENT, theme.HIGH_CONTRAST.ACCENT,
         "ON_ACCENT on ACCENT (button/heading text on an accent fill)"),
        (theme.HIGH_CONTRAST.ERROR, theme.HIGH_CONTRAST.DANGER_BG,
         "ERROR on DANGER_BG (Danger.TButton)"),
        (theme.HIGH_CONTRAST.ERROR, theme.HIGH_CONTRAST.DANGER_BG_ACTIVE,
         "ERROR on DANGER_BG_ACTIVE"),
        (theme.HIGH_CONTRAST.ERROR, theme.HIGH_CONTRAST.BG, "ERROR on BG"),
    ])
    def test_pairing_clears_normal_text_contrast(self, fg, bg, label):
        ratio = theme.contrast_ratio(fg, bg)
        assert ratio >= self.AA_NORMAL_TEXT, (
            f"{label}: {ratio:.2f}:1, below WCAG AA's {self.AA_NORMAL_TEXT}:1 "
            "for normal text"
        )

    def test_on_accent_is_not_just_the_defaults_white(self):
        # The bug this whole ON_ACCENT field exists to avoid: the default
        # theme's accent is dark enough that white text on it passes, but a
        # high-contrast accent bright enough to read as text on black is not
        # -- reusing white there would ship illegible button text.
        assert theme.HIGH_CONTRAST.ON_ACCENT != theme.DEFAULT.ON_ACCENT


# ── The switch is a real no-op when off ─────────────────────────────────────

class TestPaletteSelection:

    def test_default_palette_matches_what_was_hardcoded_before(self):
        # Regression guard: turning high contrast off must be pixel-identical
        # to the app's existing theme, not an approximation of it.
        assert theme.DEFAULT.BG == '#1a1a2e'
        assert theme.DEFAULT.ACCENT == '#e94560'
        assert theme.DEFAULT.ON_ACCENT == '#ffffff'
        assert theme.DEFAULT.DANGER_BG == '#7f1d1d'

    def test_off_by_default(self, config):
        assert theme.palette(config) is theme.DEFAULT

    def test_on_when_the_setting_is_set(self, config):
        config.set("high_contrast", True)
        assert theme.palette(config) is theme.HIGH_CONTRAST

    def test_a_broken_config_falls_back_to_default_rather_than_raising(self):
        class BrokenConfig:
            def get(self, key, default=None):
                raise RuntimeError("boom")

        assert theme.palette(BrokenConfig()) is theme.DEFAULT


# ── Keyboard navigation: every dialog answers Escape ────────────────────────

class TestDialogsRespondToEscape:
    """
    Before this, the only way to dismiss most of these was finding a Cancel
    button (or the title-bar close icon) with a mouse. `grab_set()` makes
    them modal, so a keyboard-only user had no way out at all short of
    Alt-F4.
    """

    @pytest.mark.parametrize("path,dialog_count", [
        (("ui", "settings_page.py"), 1),   # Confirm Data Deletion
        (("ui", "processes_page.py"), 1),  # Set Limits
        (("ui", "devices_page.py"), 2),    # Link New Device, Join with Code
        (("ui", "files_page.py"), 3),      # Browse Pre-loaded Apps, Edit App, _ask_string
    ])
    def test_every_dialog_in_this_file_binds_escape(self, path, dialog_count):
        text = read(*path)
        toplevels = text.count("tk.Toplevel(")
        escapes = text.count("<Escape>")
        assert toplevels == dialog_count, (
            f"{path[-1]} has {toplevels} tk.Toplevel() dialogs, expected "
            f"{dialog_count} -- update this test's count (and check the new "
            "one binds Escape) rather than silently letting it drift"
        )
        assert escapes >= dialog_count, (
            f"{path[-1]}: {toplevels} dialogs but only {escapes} <Escape> "
            "binding(s)"
        )

    def test_the_data_deletion_dialog_binds_escape_to_cancel_not_delete(self):
        # The one place binding Escape to the wrong handler would be a real
        # safety regression rather than an inconvenience.
        text = read("ui", "settings_page.py")
        start = text.index('dialog.title("Confirm Data Deletion")')
        # Escape must be bound before do_delete is even defined below it,
        # and must reference dialog.destroy -- not do_delete.
        window = text[start:start + 600]
        assert "dialog.bind('<Escape>', lambda e: dialog.destroy())" in window


# ── The Settings checkbox wires through to the palette ──────────────────────

class TestTheSettingsCheckbox:

    def test_settings_page_has_a_high_contrast_toggle(self):
        text = read("ui", "settings_page.py")
        assert 'self.config.get("high_contrast", False)' in text
        assert '"high_contrast", self._high_contrast_var.get()' in text

    def test_the_description_does_not_overclaim(self):
        # It must not read as "the whole app recolours" -- see ui/theme.py's
        # docstring on what this does and does not cover.
        text = read("ui", "settings_page.py")
        start = text.index("High-contrast colours")
        caption = text[start:start + 500]
        assert "shared controls" in caption or "tabs, buttons" in caption

    def test_app_py_passes_config_into_configure_style(self):
        text = read("ui", "app.py")
        assert "_configure_style(config)" in text
        assert "def _configure_style(config=None)" in text
