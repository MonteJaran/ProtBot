"""
Accessibility, held to a measurable standard.

Directive (EU) 2019/882 — the European Accessibility Act — has applied to
consumer software placed on the EU market since 28 June 2025. Its technical
yardstick in practice is EN 301 549, which for desktop software points at
WCAG 2.1 level AA.

Most of WCAG cannot be checked by a test. Three parts of it can, and they are
the three that go wrong silently:

  * **Contrast** is arithmetic. A palette author cannot tell 4.4:1 from 4.6:1
    by looking, and the failure is invisible to the person who chose the
    colours and disabling to everyone else. The old palette had four such
    failures, all in colours that look perfectly readable to someone with
    ordinary vision on a good monitor.

  * **Whether the colours are in one place** decides whether any of the rest
    is possible. Nine hex literals copied into six files is what made a
    high-contrast mode unbuildable — there was nothing to swap.

  * **Whether the focus indicator exists at all.** Whether it is *visible* is
    the contrast test above; whether it was configured is a source check,
    because the default clam focus ring is a dotted outline in the foreground
    colour and effectively invisible on a dark background.

What is not tested here is the part that needs a person: whether the tab
order makes sense, whether a screen reader announces something useful, whether
the app is usable at 200% zoom. Those need a real Windows session with a real
screen reader, and STATUS.md says so rather than this file implying otherwise.
"""

import os
import re

import pytest

from tests.conftest import REPO_ROOT
from ui import theme

UI_DIR = os.path.join(REPO_ROOT, "ui")


def ui_sources():
    for name in sorted(os.listdir(UI_DIR)):
        if name.endswith(".py") and name not in {"__init__.py", "theme.py"}:
            with open(os.path.join(UI_DIR, name), encoding="utf-8") as fh:
                yield name, fh.read()


# ── Contrast ──────────────────────────────────────────────────────────────

class TestContrastMaths:
    """
    The measurement itself, before it is trusted to judge a palette.

    Checked against values published in the WCAG specification, because a
    contrast function that is subtly wrong produces a palette that passes its
    own test and fails a real one.
    """

    def test_black_on_white_is_the_maximum(self):
        assert theme.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)

    def test_a_colour_against_itself_is_one(self):
        assert theme.contrast_ratio("#3a7bd5", "#3a7bd5") == pytest.approx(1.0, abs=0.001)

    def test_it_does_not_matter_which_way_round_the_arguments_go(self):
        assert theme.contrast_ratio("#1a1a2e", "#e0e0e0") == pytest.approx(
            theme.contrast_ratio("#e0e0e0", "#1a1a2e"))

    def test_luminance_is_weighted_not_averaged(self):
        # The eye is far more sensitive to green than to blue. Averaging the
        # channels rates the two alike, and produces a palette that looks
        # contrasty to its author and is unreadable to everyone else.
        assert theme.relative_luminance("#00ff00") > theme.relative_luminance("#0000ff")

    def test_a_malformed_colour_is_rejected_rather_than_scored(self):
        with pytest.raises(ValueError):
            theme.relative_luminance("not-a-colour")


class TestEveryPaletteMeetsWcagAA:

    @pytest.mark.parametrize("name", sorted(theme.PALETTES))
    def test_the_palette_passes_every_requirement(self, name):
        problems = theme.check_palette(theme.PALETTES[name])
        assert not problems, (
            f"the {name} palette fails WCAG AA:\n  " + "\n  ".join(problems)
        )

    @pytest.mark.parametrize("name", sorted(theme.PALETTES))
    def test_the_palette_defines_every_role(self, name):
        # A missing role is a page falling back to a hex literal, which is
        # exactly what the contrast tests cannot see.
        assert set(theme.PALETTES[name]) == set(theme.DARK), (
            f"the {name} palette does not define the same roles as the default"
        )

    def test_the_high_contrast_palette_is_actually_higher_contrast(self):
        # Otherwise it is a second theme wearing the name.
        for role in ("TEXT", "TEXT2", "TEXT3"):
            plain = theme.contrast_ratio(theme.DARK[role], theme.DARK["BG"])
            high = theme.contrast_ratio(theme.HIGH_CONTRAST[role],
                                        theme.HIGH_CONTRAST["BG"])
            assert high > plain, f"{role} is no better in the high-contrast palette"

    def test_body_text_clears_AAA_in_the_high_contrast_palette(self):
        # 7:1 is WCAG AAA. Someone turning this on is asking for more than the
        # minimum, and a "high-contrast" mode that only just scrapes AA is not
        # answering that.
        ratio = theme.contrast_ratio(theme.HIGH_CONTRAST["TEXT"],
                                     theme.HIGH_CONTRAST["BG"])
        assert ratio >= 7.0

    def test_a_failing_palette_is_reported_and_not_passed(self):
        # The check has to be capable of failing, or none of the above means
        # anything.
        broken = dict(theme.DARK, TEXT="#1c1c30")   # near-invisible on BG
        problems = theme.check_palette(broken)
        assert problems
        assert any("TEXT on BG" in p for p in problems)


class TestTheSelectedPaletteIsTheUsersChoice:

    def test_the_default_is_the_dark_palette(self, config):
        assert theme.selected_name(config) == "dark"

    def test_a_user_who_asked_for_high_contrast_gets_it(self, config):
        config.set("theme", "high-contrast")
        assert theme.selected_name(config) == "high-contrast"
        assert theme.palette_for("high-contrast")["BG"] == theme.HIGH_CONTRAST["BG"]

    def test_a_name_we_do_not_ship_falls_back_rather_than_raising(self, config):
        # A hand-edited config must produce a readable window to fix it in.
        config.set("theme", "solarized-banana")
        assert theme.selected_name(config) == theme.DEFAULT_PALETTE

    def test_reading_the_setting_never_raises(self):
        class Exploding:
            def get(self, *_args, **_kwargs):
                raise RuntimeError("config is gone")

        assert theme.selected_name(Exploding()) == theme.DEFAULT_PALETTE


# ── One palette, in one place ─────────────────────────────────────────────

class TestThePaletteIsNotCopiedAround:
    """
    The structural half. Contrast can only be checked where the colours are
    named, so a page that reaches for a hex literal opts out of every test
    above and out of the high-contrast mode at the same time.
    """

    # Decorative surfaces that have not been brought into the theme yet, and
    # the QR canvas, which is not decoration at all: a QR code has to be black
    # on white to be scannable, and running it through a palette would make it
    # unreadable in the high-contrast one. STATUS.md carries the rest.
    KNOWN_LITERALS = {
        "app.py": 21,           # the ad banner and the update bar
        "devices_page.py": 15,  # plan cards, and the QR canvas
        "files_page.py": 9,
        "insights_page.py": 8,  # chart series colours
        "processes_page.py": 2,
        "settings_page.py": 0,  # done — hold it there
    }

    HEX = re.compile(r"'#[0-9a-fA-F]{6}'")

    def test_no_page_defines_its_own_palette(self):
        # The specific thing that was wrong: BG/BG2/BG3/ACCENT/TEXT/... copied
        # verbatim into six files.
        for name, source in ui_sources():
            for role in ("BG", "BG2", "BG3", "ACCENT", "TEXT", "TEXT2"):
                assert not re.search(rf"^{role} +=", source, re.MULTILINE), (
                    f"ui/{name} defines {role} itself. Import it from ui.theme, "
                    "or the high-contrast palette will not reach this page."
                )

    def test_every_page_takes_its_colours_from_the_theme(self):
        for name, source in ui_sources():
            if not self.HEX.search(source) and "BG" not in source:
                continue
            assert "from ui.theme import" in source, (
                f"ui/{name} uses colours without importing the theme"
            )

    @pytest.mark.parametrize("name", sorted(KNOWN_LITERALS))
    def test_the_remaining_hex_literals_do_not_grow(self, name):
        # A ratchet, not a pass. The count going down is the point; going up
        # means a new colour was written inline where no test can see it.
        with open(os.path.join(UI_DIR, name), encoding="utf-8") as fh:
            found = len(self.HEX.findall(fh.read()))
        assert found <= self.KNOWN_LITERALS[name], (
            f"ui/{name} has {found} inline colours, up from "
            f"{self.KNOWN_LITERALS[name]}. Add a role to ui/theme.py instead — "
            "an inline colour is invisible to the contrast tests and does not "
            "change with the high-contrast palette."
        )


# ── Keyboard ──────────────────────────────────────────────────────────────

class TestKeyboardOperation:
    """
    WCAG 2.1.1 (Keyboard) and 2.4.7 (Focus Visible). Source checks: the UI
    cannot be imported here, because CI runners have no display.
    """

    def _app_source(self):
        with open(os.path.join(UI_DIR, "app.py"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_focus_ring_is_configured(self):
        # clam draws focus as a dotted outline in the foreground colour, which
        # on a dark background cannot be seen. Left alone, the app has no
        # visible focus indicator at all.
        source = self._app_source()
        assert "focuscolor=FOCUS" in source
        assert "('focus', FOCUS)" in source

    def test_controls_have_a_border_rather_than_only_a_fill(self):
        # WCAG 1.4.11: a control has to be distinguishable from what is next
        # to it. The fills are brand colours; BORDER is what carries this.
        source = self._app_source()
        assert "bordercolor=BORDER" in source
        assert "relief='solid'" in source

    def test_every_tab_is_reachable_from_the_keyboard(self):
        source = self._app_source()
        assert "_bind_keyboard_navigation" in source
        assert "<Control-Tab>" in source
        assert "Control-Key-" in source

    def test_shift_tab_works_on_both_keyboard_layouts(self):
        # Windows reports Shift+Tab as ISO_Left_Tab under some layouts.
        # Binding only one leaves those users able to go forwards and not back.
        source = self._app_source()
        assert "<Control-Shift-Tab>" in source
        assert "<Control-ISO_Left_Tab>" in source

    def test_the_tab_strip_itself_takes_focus(self):
        # So the arrow keys move between tabs once it is reached, which is what
        # every other tabbed Windows application does.
        assert "takefocus=True" in self._app_source()

    def test_no_page_removes_a_control_from_the_tab_order(self):
        for name, source in ui_sources():
            assert "takefocus=False" not in source and "takefocus=0" not in source, (
                f"ui/{name} takes a control out of the keyboard tab order"
            )


class TestTheUserCanChooseTheHighContrastPalette:

    def test_settings_offers_the_toggle(self):
        with open(os.path.join(UI_DIR, "settings_page.py"), encoding="utf-8") as fh:
            source = fh.read()
        assert "High-contrast" in source
        assert '"theme"' in source

    def test_it_says_a_restart_is_needed(self):
        # The pages bind their colours at import, so there is no live palette
        # to swap. A toggle that appears to do nothing is worse than one that
        # explains itself.
        with open(os.path.join(UI_DIR, "settings_page.py"), encoding="utf-8") as fh:
            source = fh.read()
        assert "next time ProtBot starts" in source

    def test_the_setting_has_a_default(self, config):
        from core.config import DEFAULT_CONFIG

        assert DEFAULT_CONFIG["theme"] in theme.PALETTES
