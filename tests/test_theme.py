"""
ui/theme.py: the palette, and the high-contrast mode built on top of it.

ui/theme.py deliberately imports no tkinter at module level so this file can
run in the same interpreter as the rest of the suite, which has none (see
CLAUDE.md) — everything here exercises real functions, not a description of
what they are supposed to do. What cannot be covered this way — that a
widget actually renders the ring apply_to_modules and ui/a11y.py's style
maps produce — was checked by hand against a real Tk instance before this
landed; see the commit for what that check was and what it found.
"""

import sys
import types

import pytest

from ui import theme


# ── The contrast formula itself ─────────────────────────────────────────────

class TestContrastRatio:

    def test_black_on_white_is_the_maximum(self):
        assert theme.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)

    def test_identical_colors_have_no_contrast(self):
        assert theme.contrast_ratio("#123456", "#123456") == pytest.approx(1.0, abs=0.001)

    def test_it_does_not_care_about_argument_order(self):
        a, b = theme.contrast_ratio("#1a1a2e", "#e0e0e0"), theme.contrast_ratio("#e0e0e0", "#1a1a2e")
        assert a == pytest.approx(b)

    def test_a_known_pair_matches_a_hand_computed_value(self):
        # #808080 on white: relative luminance of mid-grey is well-known
        # (~0.215), giving (1.0+0.05)/(0.2158+0.05) ~= 3.95.
        assert theme.contrast_ratio("#808080", "#ffffff") == pytest.approx(3.95, abs=0.05)


class TestBareNamesExistAndMatchNormal:
    """
    `from ui.theme import BG` is what every page does (ui/app.py's module
    docstring explains why) — that import fails at collection time, for
    every page at once, if this module does not also expose BG etc. as bare
    names alongside the NORMAL/HIGH_CONTRAST dicts. Caught here rather than
    by ui/app.py refusing to import, since nothing in this suite can import
    ui/app.py to notice (see CLAUDE.md on the Tk modules).
    """

    @pytest.mark.parametrize("name", list(theme.NORMAL.keys()))
    def test_every_normal_key_is_also_a_bare_module_attribute(self, name):
        assert hasattr(theme, name), f"ui.theme.{name} does not exist"
        assert getattr(theme, name) == theme.NORMAL[name]


# ── The high-contrast palette actually meets the bar it claims ─────────────

class TestHighContrastMeetsWCAG_AA:
    """
    The claim in ui/theme.py's docstring, checked rather than trusted: every
    foreground colour in HIGH_CONTRAST clears AA_NORMAL_TEXT against every
    background colour in it. Normal mode is not held to this — see the
    module docstring for why not.
    """

    _BACKGROUNDS = ("BG", "BG2", "BG3")
    _FOREGROUNDS = ("ACCENT", "TEXT", "TEXT2", "SUCCESS", "WARNING", "ERROR")

    @pytest.mark.parametrize("fg_name", _FOREGROUNDS)
    @pytest.mark.parametrize("bg_name", _BACKGROUNDS)
    def test_every_foreground_clears_aa_against_every_background(self, fg_name, bg_name):
        fg = theme.HIGH_CONTRAST[fg_name]
        bg = theme.HIGH_CONTRAST[bg_name]
        ratio = theme.contrast_ratio(fg, bg)
        assert ratio >= theme.AA_NORMAL_TEXT, (
            f"{fg_name} ({fg}) on {bg_name} ({bg}) is {ratio:.2f}:1, "
            f"below the {theme.AA_NORMAL_TEXT}:1 AA minimum for normal text"
        )

    @pytest.mark.parametrize("extra_name", ["TEXT3", "GOLD", "PURPLE", "CYAN"])
    @pytest.mark.parametrize("bg_name", _BACKGROUNDS)
    def test_every_extra_color_clears_at_least_large_text_aa(self, extra_name, bg_name):
        # The four page-specific extras are chart accents and a dimmed
        # label, not body text — held to the large-text/UI-component bar
        # (3:1), the one WCAG itself applies to that category.
        fg = theme.EXTRA_HIGH_CONTRAST[extra_name]
        bg = theme.HIGH_CONTRAST[bg_name]
        ratio = theme.contrast_ratio(fg, bg)
        assert ratio >= theme.AA_LARGE_TEXT, (
            f"{extra_name} ({fg}) on {bg_name} ({bg}) is {ratio:.2f}:1, "
            f"below the {theme.AA_LARGE_TEXT}:1 AA minimum for large text/UI"
        )

    def test_the_focus_ring_is_visible_in_both_palettes(self):
        for mode, palette in [("normal", theme.NORMAL), ("high_contrast", theme.HIGH_CONTRAST)]:
            ring = theme.FOCUS_RING[mode]
            for bg_name in self._BACKGROUNDS:
                ratio = theme.contrast_ratio(ring, palette[bg_name])
                assert ratio >= theme.AA_LARGE_TEXT, (
                    f"{mode} focus ring {ring} on {bg_name} is {ratio:.2f}:1"
                )

    def test_high_contrast_colors_are_hex(self):
        # Cheap guard against a typo landing as an invalid literal that
        # would only surface once Tk tried to parse it.
        import re

        hex_re = re.compile(r"^#[0-9a-fA-F]{6}$")
        for source in (theme.NORMAL, theme.HIGH_CONTRAST, theme.EXTRA_HIGH_CONTRAST):
            for name, value in source.items():
                assert hex_re.match(value), f"{name} = {value!r} is not #rrggbb"
        for value in theme.FOCUS_RING.values():
            assert hex_re.match(value)


# ── Reading the config ──────────────────────────────────────────────────────

class TestIsHighContrast:

    def test_defaults_to_normal(self, config):
        assert theme.is_high_contrast(config) is False
        assert theme.colors(config) == theme.NORMAL

    def test_the_setting_switches_it(self, config):
        config.set("high_contrast", True)
        assert theme.is_high_contrast(config) is True
        assert theme.colors(config) == theme.HIGH_CONTRAST

    def test_a_config_that_cannot_answer_is_never_high_contrast(self):
        # A theme lookup must not be able to take the window down with it.
        class BrokenConfig:
            def get(self, *_a, **_kw):
                raise RuntimeError("boom")

        assert theme.is_high_contrast(BrokenConfig()) is False
        assert theme.colors(BrokenConfig()) == theme.NORMAL

    def test_focus_ring_color_follows_the_same_switch(self, config):
        assert theme.focus_ring_color(config) == theme.FOCUS_RING["normal"]
        config.set("high_contrast", True)
        assert theme.focus_ring_color(config) == theme.FOCUS_RING["high_contrast"]


# ── The module-global rebinding apply_to_modules relies on ─────────────────

class TestApplyToModules:
    """
    apply_to_modules() re-points bare names on already-imported page
    modules — see ui/theme.py's module docstring for why that reaches every
    widget those modules go on to build without editing one. Exercised here
    against a throwaway module injected into sys.modules, not the real
    ui/*_page.py files: those import tkinter, which this interpreter does
    not have (see CLAUDE.md) — a fake module with the same shape as a real
    page module proves the same mechanism.
    """

    @pytest.fixture
    def fake_page_module(self, monkeypatch):
        name = "tests._fake_theme_target"
        module = types.ModuleType(name)
        # The nine core names every real page defines, one extra some do,
        # and one unrelated name that must survive untouched.
        module.BG = "#111111"
        module.BG2 = "#111111"
        module.BG3 = "#111111"
        module.ACCENT = "#111111"
        module.TEXT = "#111111"
        module.TEXT2 = "#111111"
        module.SUCCESS = "#111111"
        module.WARNING = "#111111"
        module.ERROR = "#111111"
        module.GOLD = "#111111"          # a page-specific extra
        module.SOME_OTHER_CONSTANT = "leave me alone"
        sys.modules[name] = module
        monkeypatch.setattr(theme, "_THEMED_MODULES", (name,))
        yield module
        del sys.modules[name]

    def test_normal_mode_sets_every_core_name_to_the_normal_value(
            self, fake_page_module, config):
        theme.apply_to_modules(config)
        for key, value in theme.NORMAL.items():
            assert getattr(fake_page_module, key) == value

    def test_high_contrast_mode_sets_every_core_name(self, fake_page_module, config):
        config.set("high_contrast", True)
        theme.apply_to_modules(config)
        for key, value in theme.HIGH_CONTRAST.items():
            assert getattr(fake_page_module, key) == value

    def test_high_contrast_mode_also_overrides_the_extra_names_present(
            self, fake_page_module, config):
        config.set("high_contrast", True)
        theme.apply_to_modules(config)
        assert fake_page_module.GOLD == theme.EXTRA_HIGH_CONTRAST["GOLD"]

    def test_normal_mode_does_not_touch_extra_names(self, fake_page_module, config):
        # See the module docstring: normal mode leaves each page's own
        # extras exactly as that page defined them.
        theme.apply_to_modules(config)
        assert fake_page_module.GOLD == "#111111"

    def test_a_name_the_module_never_defined_is_not_injected(
            self, fake_page_module, config):
        config.set("high_contrast", True)
        theme.apply_to_modules(config)
        assert not hasattr(fake_page_module, "PURPLE")   # this fake never had one
        assert not hasattr(fake_page_module, "CYAN")

    def test_an_unrelated_module_attribute_is_left_alone(self, fake_page_module, config):
        theme.apply_to_modules(config)
        assert fake_page_module.SOME_OTHER_CONSTANT == "leave me alone"

    def test_a_module_that_cannot_be_imported_does_not_raise(self, config, monkeypatch):
        monkeypatch.setattr(theme, "_THEMED_MODULES", ("no.such.module.at.all",))
        theme.apply_to_modules(config)   # must not raise

    def test_is_idempotent(self, fake_page_module, config):
        theme.apply_to_modules(config)
        theme.apply_to_modules(config)
        assert fake_page_module.BG == theme.NORMAL["BG"]

    def test_the_real_theme_module_is_itself_in_the_themed_list(self):
        # ui/app.py's _configure_style() reads BG etc. as module globals on
        # ui.app the same way every page does — if "ui.app" ever fell out
        # of this list, the ttk styles would silently stop re-theming while
        # every plain tk widget kept working, which is the kind of half
        # broken nobody would notice from a screenshot of one tab.
        assert "ui.app" in theme._THEMED_MODULES
        assert "ui.devices_page" in theme._THEMED_MODULES
        assert "ui.processes_page" in theme._THEMED_MODULES
        assert "ui.files_page" in theme._THEMED_MODULES
        assert "ui.insights_page" in theme._THEMED_MODULES
        assert "ui.settings_page" in theme._THEMED_MODULES
