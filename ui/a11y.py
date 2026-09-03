"""
a11y.py - Keyboard operability: a visible focus ring everywhere, Escape
closes a dialog, and anything a mouse can click a keyboard can activate too.

AUDIT ST-06's other two asks, alongside ui/theme.py's high-contrast mode.
`apply_focus_ring` is called once, at startup, the same way and for the same
reason ui/theme.py's `apply_to_modules` is: Tk's option database and ttk's
style maps both apply to every widget of a given class created *after* the
call, in any module, so one call before the six pages are built reaches
every one of them without editing a widget constructor. Escape-closes and
click-or-Enter-or-Space are opt-in per widget (`bind_escape_closes`,
`bind_activate`) because they need a callback, not just a colour.

## What this deliberately does not attempt

Full screen-reader support — NVDA or Narrator announcing "Register This
Device, button" the way they do for a native Win32 control — is not
something vanilla Tkinter can do. Tk does not implement MSAA or UI
Automation for the widgets it draws; on Windows they are real HWNDs, but of
a Tk-registered window class with no accessible name or role attached, so a
screen reader sees an unlabelled pane, not a button. Making that work would
mean one of: a different GUI toolkit (wxPython and Qt both wrap real native
controls or bridge to UI Automation themselves — not a change this project
takes on for one line item), or hand-written COM/UI-Automation provider code
per widget, in ctypes, on top of a platform this machine cannot run and a
screen reader this project has no way to test against. That combination —
unverifiable, Windows-only, large — is exactly what STATUS.md's "written but
never executed" section exists to flag, and this project's own rule is not
to describe that kind of code as working. So it is not written.

What *is* real and shipped here: every interactive control operable from the
keyboard alone (this file), with a visible focus indicator (this file) and a
high-contrast palette for anyone who needs one (ui/theme.py). Keyboard
operability is also WCAG 2.1.1 in its own right, not a consolation prize —
plenty of assistive setups and motor-impairment cases need exactly this and
nothing about a screen reader.
"""

import tkinter as tk
from tkinter import ttk

from ui import theme

# Classic Tk widget classes that can take keyboard focus. Label and Frame are
# deliberately absent — most instances of both are static, and giving every
# label in the app a focus ring by default would be worse than the problem
# this solves. A Label or Frame doing double duty as a clickable control
# gets a ring individually, via bind_activate, which is exactly the set that
# should have one.
_FOCUSABLE_TK_CLASSES = (
    "Button", "Entry", "Checkbutton", "Radiobutton", "Listbox",
    "Spinbox", "Menubutton",
)

# ttk styles this project defines or uses (see ui/app.py's _configure_style)
# that take keyboard focus and should show it.
_FOCUSABLE_TTK_STYLES = (
    "TButton", "Accent.TButton", "Danger.TButton",
    "TEntry", "TCombobox", "TSpinbox",
    "TCheckbutton", "TRadiobutton",
)


def apply_focus_ring(root, config) -> None:
    """
    A visible focus ring on every keyboard-focusable control, applied once.

    Classic Tk widgets: via the option database (`*ClassName.option`),
    which only reaches widgets created after this call — call it before any
    page is built. An explicit `highlightthickness=` (or the like) at a
    widget's own construction still overrides the option database, so
    nothing already deliberately styled is disturbed.

    ttk widgets: via `ttk.Style` state maps, since ttk ignores the option
    database for anything the current theme draws itself.
    """
    ring = theme.focus_ring_color(config)
    bg = theme.colors(config)["BG"]

    for widget_class in _FOCUSABLE_TK_CLASSES:
        root.option_add(f"*{widget_class}.highlightThickness", 2)
        root.option_add(f"*{widget_class}.highlightColor", ring)
        root.option_add(f"*{widget_class}.highlightBackground", bg)

    _style_ttk_focus(ring)


def _style_ttk_focus(ring: str) -> None:
    style = ttk.Style()

    # bordercolor/lightcolor/darkcolor: what 'clam' (ui/app.py's theme)
    # actually paints an Entry's or Button's border from. focuscolor: what
    # it paints a Checkbutton's/Radiobutton's indicator ring from.
    # borderwidth/relief matter because this app's buttons are flat —
    # borderwidth=0 at rest (ui/app.py's _configure_style) — so a colour
    # with nothing to colour renders as nothing; bumping the border to 2px
    # only in the focus state is what actually makes it visible, confirmed
    # against style.lookup(style_name, option, ["focus"]) before this went
    # in, not assumed from how the Entry half of this behaved on its own,
    # which has a real border at rest and so did not need this to render.
    # Mapping every option on every style is redundant on some, harmless on
    # all — ttk accepts an option a theme's element layout does not use
    # rather than raising, also confirmed rather than assumed.
    for style_name in _FOCUSABLE_TTK_STYLES:
        style.map(
            style_name,
            bordercolor=[("focus", ring)],
            lightcolor=[("focus", ring)],
            darkcolor=[("focus", ring)],
            focuscolor=[("focus", ring)],
            borderwidth=[("focus", 2)],
            relief=[("focus", "solid")],
        )


def bind_activate(widget, callback, *, ring_color: str, background: str) -> None:
    """
    Make a click-only control (a Label or Frame standing in for a button)
    keyboard-reachable and keyboard-usable: tab-focusable, Enter and Space
    both trigger the same callback a click does, and focus gets a ring in
    the same two colours apply_focus_ring gives every other control.

    `ring_color`/`background` are passed rather than re-derived from config
    here, because every call site already has them (it built the widget's
    own colours from the same theme two lines above) and a second config
    lookup per widget is pure duplication.
    """
    widget.configure(takefocus=1)
    try:
        widget.configure(highlightthickness=2, highlightcolor=ring_color,
                         highlightbackground=background)
    except tk.TclError:
        pass   # a widget class with no highlight* options; focus still works
    widget.bind("<Return>", lambda _e: callback())
    widget.bind("<space>", lambda _e: callback())


def bind_escape_closes(toplevel, on_close=None) -> None:
    """
    Escape closes a Toplevel. None of this app's dialogs and popups change
    anything the moment they open — Escape is always a safe way out of one,
    and every one of them should have this, not just the ones someone
    happened to test with a keyboard.
    """
    handler = on_close or toplevel.destroy
    toplevel.bind("<Escape>", lambda _e: handler())


def focus_scrollable(canvas, config) -> None:
    """
    Make a Canvas used as a scroll container keyboard-reachable.

    Tk does not make Canvas tab-focusable by default (AUDIT ST-06) — its
    `takefocus` resolves to "" (not focusable) unless a widget explicitly
    asks otherwise, verified against a real Tk instance rather than assumed,
    since the empty-string default's resolution is not consistent across
    every Tk widget class.
    """
    canvas.configure(takefocus=1)
    try:
        canvas.configure(highlightthickness=1,
                         highlightcolor=theme.focus_ring_color(config))
    except tk.TclError:
        pass
