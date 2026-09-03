"""
app.py - Main application window for ProtBot.
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime
import webbrowser
import threading

from core.logging_setup import get_logger
from ui.files_page import FilesPage
from ui.processes_page import ProcessesPage
from ui.settings_page import SettingsPage
from ui.devices_page import DevicesPage
from ui.insights_page import InsightsPage

# ── Colours ──────────────────────────────────────────────────────────────────
# The palette, the high-contrast variant and the WCAG contrast checks all live
# in ui/theme.py (AUDIT ST-06). This used to be nine hex literals copied into
# six files, which is what made a high-contrast mode impossible to add — there
# was no single thing to swap, and no single thing to measure.
from ui.theme import (  # noqa: F401
    ACCENT, ACCENT_HOVER, ACCENT_TEXT, BG, BG2, BG3, BORDER, DANGER_BG,
    DANGER_HOVER, ERROR, FOCUS, ON_ACCENT, ON_DANGER, SUCCESS, TEXT, TEXT2,
    TEXT3, WARNING,
)

log = get_logger("ui")

# ── Kill Toast Notification ────────────────────────────────────────────────────

class KillToast:
    """
    A non-blocking on-screen toast that appears when ProtBot force-closes
    an app. Stays on top, auto-dismisses after 5 seconds with a countdown bar.
    Must be created and managed on the main tkinter thread.
    """

    _DURATION_MS = 5000   # total display time
    _TICK_MS     = 50     # progress bar update interval

    def __init__(self, root: tk.Tk, app_name: str, limit_min: int) -> None:
        self._root = root
        self._remaining = self._DURATION_MS

        # ── Window ────────────────────────────────────────────────────────────
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)        # no title bar
        self._win.attributes('-topmost', True)  # always on top
        self._win.attributes('-alpha', 0.95)
        self._win.configure(bg=BG)
        self._win.resizable(False, False)

        # ── Position: top-right corner ────────────────────────────────────────
        w, h = 320, 100
        sw = root.winfo_screenwidth()
        self._win.geometry(f"{w}x{h}+{sw - w - 18}+18")

        # ── Layout ────────────────────────────────────────────────────────────
        # Red accent bar on the left
        tk.Frame(self._win, bg=ACCENT, width=5).pack(side='left', fill='y')

        body = tk.Frame(self._win, bg=BG)
        body.pack(side='left', fill='both', expand=True, padx=(10, 10), pady=8)

        tk.Label(body, text="\u26a0  App Closed by ProtBot",
                 bg=BG, fg=ACCENT_TEXT,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w')

        tk.Label(body, text=app_name,
                 bg=BG, fg=TEXT,
                 font=('Segoe UI', 12, 'bold')).pack(anchor='w')

        tk.Label(body,
                 text=f"Daily limit of {limit_min} min reached.",
                 bg=BG, fg=TEXT2,
                 font=('Segoe UI', 9)).pack(anchor='w')

        # Countdown progress bar
        self._bar_frame = tk.Frame(self._win, bg=BG3, height=4)
        self._bar_frame.pack(side='bottom', fill='x')
        self._bar = tk.Frame(self._bar_frame, bg=ACCENT, height=4)
        self._bar.place(x=0, y=0, relwidth=1.0, height=4)

        # Click to dismiss
        for widget in (self._win, body, self._bar_frame, self._bar):
            widget.bind('<Button-1>', lambda _e: self._dismiss())

        self._tick()

    def _tick(self) -> None:
        if not self._win.winfo_exists():
            return
        self._remaining -= self._TICK_MS
        if self._remaining <= 0:
            self._dismiss()
            return
        fraction = self._remaining / self._DURATION_MS
        self._bar.place(relwidth=fraction)
        self._win.after(self._TICK_MS, self._tick)

    def _dismiss(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            # The window may already be gone; nothing to report.
            pass

# Colours: see the ui.theme import at the top of this file.


def _configure_style() -> ttk.Style:
    """
    The ttk theme, built from ui/theme.py.

    Two accessibility properties are set here rather than per widget, because
    per widget is how they end up missing from the one control that mattered
    (AUDIT ST-06, and WCAG 2.1 2.4.7 Focus Visible / 1.4.11 Non-text
    Contrast):

      * **Every focusable control shows where the focus is.** clam draws focus
        as a dotted 1px outline in the foreground colour, which on a dark
        background is close to invisible. It is replaced by a solid ring in
        FOCUS, a colour the contrast tests hold to 3:1 against every surface.

      * **Every control has a boundary.** The flat, borderless look meant a
        button and the card behind it differed only in fill, and the fills are
        brand colours chosen for looks. BORDER carries the 3:1 that 1.4.11
        asks for, which is what leaves the fills free.
    """
    style = ttk.Style()
    style.theme_use('clam')

    # clam's own focus colour, used wherever a widget draws its own ring.
    style.configure('.', focuscolor=FOCUS, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER)

    # ── Frames ───────────────────────────────────────────────────────────────
    style.configure('TFrame', background=BG)
    style.configure('Dark.TFrame', background=BG)
    style.configure('Card.TFrame', background=BG2)

    # ── Labels ───────────────────────────────────────────────────────────────
    style.configure('TLabel', background=BG, foreground=TEXT, font=('Segoe UI', 10))
    style.configure('Title.TLabel', background=BG, foreground=TEXT, font=('Segoe UI', 13, 'bold'))
    style.configure('Subtitle.TLabel', background=BG, foreground=TEXT2, font=('Segoe UI', 9))
    style.configure('Card.TLabel', background=BG2, foreground=TEXT, font=('Segoe UI', 10))
    style.configure('CardTitle.TLabel', background=BG2, foreground=TEXT2, font=('Segoe UI', 9))
    style.configure('CardValue.TLabel', background=BG2, foreground=TEXT, font=('Segoe UI', 18, 'bold'))
    style.configure('Status.TLabel', background=BG3, foreground=TEXT2, font=('Segoe UI', 9))
    style.configure('Section.TLabel', background=BG, foreground=ACCENT_TEXT, font=('Segoe UI', 11, 'bold'))
    style.configure('Info.TLabel', background=BG, foreground=TEXT2, font=('Segoe UI', 9))

    # ── Buttons ──────────────────────────────────────────────────────────────
    # borderwidth=1 rather than 0: a borderless button on a dark card is a
    # patch of slightly different colour, which is what WCAG 1.4.11 exists to
    # stop. The border is BORDER, which the contrast tests hold to 3:1 against
    # every surface a button can sit on.
    style.configure(
        'TButton',
        background=BG3, foreground=TEXT,
        font=('Segoe UI', 10),
        borderwidth=1, relief='solid', padding=(10, 5),
        bordercolor=BORDER, focuscolor=FOCUS,
    )
    style.map(
        'TButton',
        background=[('active', ACCENT), ('pressed', ACCENT)],
        foreground=[('active', ON_ACCENT), ('pressed', ON_ACCENT)],
        # A focused control has to look different from an unfocused one, or a
        # keyboard user cannot tell where they are.
        bordercolor=[('focus', FOCUS), ('!focus', BORDER)],
    )
    style.configure(
        'Accent.TButton',
        background=ACCENT, foreground=ON_ACCENT,
        font=('Segoe UI', 10, 'bold'),
        borderwidth=1, relief='solid', padding=(10, 5),
        bordercolor=BORDER, focuscolor=FOCUS,
    )
    style.map(
        'Accent.TButton',
        background=[('active', ACCENT_HOVER), ('pressed', ACCENT_HOVER)],
        bordercolor=[('focus', FOCUS), ('!focus', BORDER)],
    )
    style.configure(
        'Danger.TButton',
        background=DANGER_BG, foreground=ON_DANGER,
        font=('Segoe UI', 10),
        borderwidth=1, relief='solid', padding=(10, 5),
        bordercolor=BORDER, focuscolor=FOCUS,
    )
    style.map(
        'Danger.TButton',
        background=[('active', DANGER_HOVER), ('pressed', DANGER_HOVER)],
        bordercolor=[('focus', FOCUS), ('!focus', BORDER)],
    )

    # ── Notebook ─────────────────────────────────────────────────────────────
    style.configure(
        'TNotebook',
        background=BG2, borderwidth=0, tabmargins=0,
    )
    style.configure(
        'TNotebook.Tab',
        background=BG2, foreground=TEXT2,
        font=('Segoe UI', 10), padding=(16, 8),
        borderwidth=0,
    )
    style.map(
        'TNotebook.Tab',
        background=[('selected', BG3), ('active', BG3)],
        foreground=[('selected', TEXT), ('active', TEXT)],
        # Tabs take focus with Tab and move with the arrow keys. Without this
        # the focused tab is indistinguishable from the selected one.
        bordercolor=[('focus', FOCUS)],
    )

    # ── Treeview ─────────────────────────────────────────────────────────────
    style.configure(
        'Treeview',
        background=BG2, foreground=TEXT,
        fieldbackground=BG2,
        font=('Segoe UI', 10),
        rowheight=28, borderwidth=0,
    )
    style.configure(
        'Treeview.Heading',
        background=BG3, foreground=TEXT,
        font=('Segoe UI', 10, 'bold'),
        relief='flat', borderwidth=0,
    )
    style.map(
        'Treeview',
        background=[('selected', BG3)],
        foreground=[('selected', TEXT)],
    )
    style.map(
        'Treeview.Heading',
        background=[('active', ACCENT)],
    )

    # ── Combobox ─────────────────────────────────────────────────────────────
    style.configure(
        'TCombobox',
        background=BG2, foreground=TEXT,
        fieldbackground=BG2,
        selectbackground=BG3, selectforeground=TEXT,
        font=('Segoe UI', 10),
        borderwidth=1, relief='flat',
    )
    style.map(
        'TCombobox',
        fieldbackground=[('readonly', BG2)],
        foreground=[('readonly', TEXT)],
        background=[('readonly', BG2)],
        bordercolor=[('focus', FOCUS), ('!focus', BORDER)],
    )

    # ── Checkbutton / Radiobutton ─────────────────────────────────────────────
    style.configure(
        'TCheckbutton',
        background=BG, foreground=TEXT,
        font=('Segoe UI', 10),
    )
    style.map(
        'TCheckbutton',
        background=[('active', BG)],
        foreground=[('active', TEXT)],
        indicatorcolor=[('selected', ACCENT), ('!selected', BG2)],
        # The indicator is the control; its outline is what makes it visible
        # against the page, and what shows the keyboard focus.
        bordercolor=[('focus', FOCUS), ('!focus', BORDER)],
    )
    style.configure(
        'TRadiobutton',
        background=BG, foreground=TEXT,
        font=('Segoe UI', 10),
    )
    style.map(
        'TRadiobutton',
        background=[('active', BG)],
        foreground=[('active', TEXT)],
        indicatorcolor=[('selected', ACCENT), ('!selected', BG2)],
        bordercolor=[('focus', FOCUS), ('!focus', BORDER)],
    )

    # ── Entry ────────────────────────────────────────────────────────────────
    style.configure(
        'TEntry',
        background=BG2, foreground=TEXT,
        fieldbackground=BG2,
        insertcolor=TEXT,
        selectbackground=BG3, selectforeground=TEXT,
        font=('Segoe UI', 10),
        borderwidth=1, relief='solid',
        bordercolor=BORDER,
    )
    style.map('TEntry', bordercolor=[('focus', FOCUS), ('!focus', BORDER)])

    # ── Scrollbar ────────────────────────────────────────────────────────────
    style.configure(
        'TScrollbar',
        background=BG2, troughcolor=BG, arrowcolor=TEXT2,
        borderwidth=0, relief='flat',
    )
    style.map('TScrollbar', background=[('active', BG3)])

    # ── Spinbox ──────────────────────────────────────────────────────────────
    style.configure(
        'TSpinbox',
        background=BG2, foreground=TEXT,
        fieldbackground=BG2,
        insertcolor=TEXT,
        font=('Segoe UI', 10),
        borderwidth=1, relief='solid',
        bordercolor=BORDER,
    )
    style.map('TSpinbox', bordercolor=[('focus', FOCUS), ('!focus', BORDER)])

    # ── Treeview ─────────────────────────────────────────────────────────────
    # The rows are the app list, and it is reachable with Tab and the arrow
    # keys. A selected row that only differs by fill leaves a keyboard user
    # with no idea which app they are about to set a limit on.
    style.map('Treeview', bordercolor=[('focus', FOCUS), ('!focus', BORDER)])

    # ── Separator ────────────────────────────────────────────────────────────
    style.configure('TSeparator', background=BG3)

    return style


# ── Ad Banner ─────────────────────────────────────────────────────────────────

# No ad network is connected, so nothing is displayed.
#
# This list stays empty until a real ad network is integrated. Do NOT put
# real companies' names, taglines or logos here as filler: shipping another
# brand in an ad slot implies a commercial relationship that does not exist,
# which is false endorsement. Any placeholder used for screenshots must be
# an invented brand.
#
# Expected shape once a provider is wired up:
#     {"label": str, "headline": str, "sub": str, "url": str, "tag": str}
_ADS: list = []


def ads_available() -> bool:
    """True when there is at least one ad to display."""
    return bool(_ADS)


class AdBanner(tk.Frame):
    """
    A slim horizontal ad strip, shown only when ads are configured.

    With no ad network connected the banner has nothing to render, so callers
    should check `ads_available()` before packing it.
    """

    _ROTATE_MS = 5 * 60 * 1000   # rotate ad every 5 minutes

    def __init__(self, parent, **kw) -> None:
        super().__init__(parent, bg='#0d1b33', height=54, **kw)
        self.pack_propagate(False)
        self._idx    = 0
        self._ad_url = ""
        if not _ADS:
            return
        self._build()
        self._show_ad(self._idx)
        self._schedule_rotate()

    def _build(self) -> None:
        # Left: subtle "Ad" pill
        pill = tk.Frame(self, bg='#0d1b33')
        pill.pack(side='left', padx=(10, 6), pady=0, fill='y')
        tk.Label(pill, text=" Ad ", bg='#1e3a5f', fg='#6080a0',
                 font=('Segoe UI', 9), relief='flat',
                 padx=3).pack(side='left', anchor='center', pady=17)

        # Divider
        tk.Frame(self, bg='#1e3a5f', width=1).pack(side='left', fill='y', pady=8)

        # Centre: ad copy
        centre = tk.Frame(self, bg='#0d1b33', cursor='hand2')
        centre.pack(side='left', fill='both', expand=True, padx=12, pady=0)
        centre.bind('<Button-1>', self._on_click)

        self._lbl_label    = tk.Label(centre, text="", bg='#0d1b33', fg='#4a7fa0',
                                      font=('Segoe UI', 9), anchor='w', cursor='hand2')
        self._lbl_label.pack(fill='x', anchor='w', pady=(9, 0))
        self._lbl_label.bind('<Button-1>', self._on_click)

        self._lbl_headline = tk.Label(centre, text="", bg='#0d1b33', fg='#c8ddf0',
                                      font=('Segoe UI', 10, 'bold'), anchor='w', cursor='hand2')
        self._lbl_headline.pack(fill='x', anchor='w')
        self._lbl_headline.bind('<Button-1>', self._on_click)

        self._lbl_sub      = tk.Label(centre, text="", bg='#0d1b33', fg='#607080',
                                      font=('Segoe UI', 9), anchor='w', cursor='hand2')
        self._lbl_sub.pack(fill='x', anchor='w')
        self._lbl_sub.bind('<Button-1>', self._on_click)

        # Right: domain tag + subtle arrow
        right = tk.Frame(self, bg='#0d1b33')
        right.pack(side='right', padx=(0, 14), pady=0, fill='y')

        self._lbl_tag = tk.Label(right, text="", bg='#0d1b33', fg='#3a5a78',
                                 font=('Segoe UI', 9), cursor='hand2')
        self._lbl_tag.pack(anchor='center', pady=17)
        self._lbl_tag.bind('<Button-1>', self._on_click)

    def _show_ad(self, idx: int) -> None:
        if not _ADS:
            return
        ad = _ADS[idx % len(_ADS)]
        self._ad_url = ad["url"]
        self._lbl_label.config(text=ad["label"].upper())
        self._lbl_headline.config(text=ad["headline"])
        self._lbl_sub.config(text=ad["sub"])
        self._lbl_tag.config(text=ad["tag"] + " →")

    def _schedule_rotate(self) -> None:
        self.after(self._ROTATE_MS, self._rotate)

    def _rotate(self) -> None:
        if not _ADS:
            return
        self._idx = (self._idx + 1) % len(_ADS)
        self._show_ad(self._idx)
        self._schedule_rotate()

    def _on_click(self, _event=None) -> None:
        if self._ad_url:
            threading.Thread(target=lambda: webbrowser.open(self._ad_url),
                             daemon=True).start()


class MainApp:
    def __init__(self, root: tk.Tk, db, config, monitor) -> None:
        self.root = root
        self.db = db
        self.config = config
        self.monitor = monitor

        self._setup_window()
        _configure_style()
        self._build_ui()
        self._start_refresh_loop()

        # Override in main.py
        self.quit_app = lambda: self.root.destroy()

    # ── Window Setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.root.title("ProtBot \u2014 App Usage Tracker")
        self.root.geometry("900x650")
        self.root.minsize(800, 560)
        self.root.configure(bg=BG)
        # Try to set a simple icon color
        try:
            self.root.iconbitmap("")
        except Exception:
            pass

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header bar
        header = tk.Frame(self.root, bg=BG3, height=50)
        header.pack(fill='x', side='top')
        header.pack_propagate(False)

        tk.Label(
            header, text="  ProtBot",
            bg=BG3, fg=ACCENT_TEXT,
            font=('Segoe UI', 14, 'bold'),
        ).pack(side='left', padx=(10, 4), pady=8)
        tk.Label(
            header, text="App Usage Tracker",
            bg=BG3, fg=TEXT2,
            font=('Segoe UI', 10),
        ).pack(side='left', pady=8)

        # Quit button in header
        tk.Button(
            header, text="Quit",
            bg=BG3, fg=TEXT2, activebackground=ACCENT, activeforeground=ON_ACCENT,
            font=('Segoe UI', 9), relief='flat', bd=0, padx=10,
            command=self._on_quit,
        ).pack(side='right', padx=10, pady=8)

        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=0, pady=0)

        # Tabs
        self.files_page     = FilesPage(self.notebook, self.db, self.config, self.monitor)
        self.processes_page = ProcessesPage(self.notebook, self.db, self.config, self.monitor)
        self.insights_page  = InsightsPage(self.notebook, self.db, self.config, self.monitor)
        self.devices_page   = DevicesPage(self.notebook, self.db, self.config, self.monitor)
        self.settings_page  = SettingsPage(self.notebook, self.db, self.config, self.monitor)

        self.notebook.add(self.files_page,     text="\U0001f4c1 Files")
        self.notebook.add(self.processes_page, text="\U0001f4ca Processes")
        self.notebook.add(self.insights_page,  text="\U0001f4a1 Insights")
        self.notebook.add(self.devices_page,   text="\U0001f517 Devices")
        self.notebook.add(self.settings_page,  text="\u2699\ufe0f Settings")

        # Refresh insights only when its tab is selected — prevents scroll reset
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._bind_keyboard_navigation()

        # ── Bottom section (pack bottom-up so notebook gets remaining space) ──
        # Status bar (bottommost)
        self._status_var = tk.StringVar(value="Ready")
        status_bar = tk.Frame(self.root, bg=BG3, height=28)
        status_bar.pack(fill='x', side='bottom')
        status_bar.pack_propagate(False)

        self._status_label = tk.Label(
            status_bar, textvariable=self._status_var,
            bg=BG3, fg=TEXT2, font=('Segoe UI', 9),
            anchor='w', padx=12,
        )
        self._status_label.pack(side='left', fill='y')

        self._time_label = tk.Label(
            status_bar, text="",
            bg=BG3, fg=TEXT2, font=('Segoe UI', 9),
            anchor='e', padx=12,
        )
        self._time_label.pack(side='right', fill='y')

        # Ad banner (just above status bar) — only when ads are configured
        self._ad_banner = None
        if ads_available():
            tk.Frame(self.root, bg='#0a1525', height=1).pack(fill='x', side='bottom')
            self._ad_banner = AdBanner(self.root)
            self._ad_banner.pack(fill='x', side='bottom')
            tk.Frame(self.root, bg='#0a1525', height=1).pack(fill='x', side='bottom')

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _start_refresh_loop(self) -> None:
        self._refresh_cycle()

    def _refresh_cycle(self) -> None:
        self.refresh_all()
        self.root.after(5000, self._refresh_cycle)

    def refresh_all(self) -> None:
        # A refresh failure used to be invisible: the UI silently froze on
        # stale data with nothing recorded anywhere.
        try:
            self.files_page.refresh()
        except Exception as e:
            log.error("Files tab refresh failed: %s", e)
        try:
            self.processes_page.refresh()
        except Exception as e:
            log.error("Processes tab refresh failed: %s", e)
        now = datetime.now().strftime("%H:%M:%S")
        try:
            count = len(self.db.get_all_tracked_apps())
            running = len(self.monitor.running_apps)
            self._status_var.set(f"Tracking {count} app(s)  |  {running} running now")
        except Exception as e:
            log.error("Could not update the status bar: %s", e)
        self._time_label.config(text=f"Last updated: {now}")

    def show_update_available(self, info: dict) -> None:
        """
        Tell the user a newer version exists.

        Informative, not a nag: one status-bar line they can dismiss, and a
        dialog only when the release is marked critical — that flag is for
        security fixes, so it is the one case worth interrupting for. Nothing
        is ever downloaded or installed automatically.
        """
        version = info.get("version", "")
        url = info.get("url", "")

        bar = tk.Frame(self.root, bg='#1e3a5f')
        bar.pack(fill='x', side='top')

        label = "Security update" if info.get("critical") else "Update available"
        tk.Label(bar, text=f"  {label}: ProtBot {version}",
                 bg='#1e3a5f', fg=TEXT,
                 font=('Segoe UI', 9, 'bold')).pack(side='left', pady=5)

        if info.get("notes"):
            tk.Label(bar, text=f"  — {info['notes'][:80]}",
                     bg='#1e3a5f', fg=TEXT2,
                     font=('Segoe UI', 9)).pack(side='left', pady=5)

        tk.Button(bar, text="Dismiss", bg='#1e3a5f', fg=TEXT2,
                  font=('Segoe UI', 9), relief='flat', bd=0,
                  cursor='hand2',
                  command=bar.destroy).pack(side='right', padx=8)

        if url:
            tk.Button(bar, text="Download", bg=ACCENT, fg=ON_ACCENT,
                      font=('Segoe UI', 9, 'bold'),
                      relief='flat', bd=0, padx=12, cursor='hand2',
                      command=lambda: threading.Thread(
                          target=lambda: webbrowser.open(url),
                          daemon=True).start()).pack(side='right', padx=4)

        log.info("Update %s advertised to the user.", version)

    def show_kill_toast(self, app_name: str, limit_min: int) -> None:
        """Show an on-screen toast notification that an app was force-closed."""
        try:
            KillToast(self.root, app_name, limit_min)
        except Exception as e:
            log.error("Could not show the close notification: %s", e)

    # ── Keyboard navigation (AUDIT ST-06) ────────────────────────────────────

    def _bind_keyboard_navigation(self) -> None:
        """
        Reach every tab, and leave every dialog, without a mouse.

        Tab and Shift-Tab already traverse the controls within a page — that
        is Tk's own behaviour, and the focus ring in `_configure_style` is
        what makes it usable. What was missing is the level above: moving
        between the five tabs, which otherwise needs the pointer.

        WCAG 2.1 2.1.1 (Keyboard) asks that all functionality be operable
        from a keyboard, and 2.1.2 (No Keyboard Trap) that focus can always
        leave. Both bindings are on the root window rather than the notebook,
        so they work wherever the focus currently is.

          Ctrl+1 … Ctrl+5   go straight to a tab
          Ctrl+Tab          next tab, wrapping
          Ctrl+Shift+Tab    previous tab, wrapping

        The notebook itself also gains `takefocus`, so the tab strip is a stop
        in the Tab order and the left/right arrows then move between tabs —
        the convention a screen-reader user will already expect from every
        other tabbed Windows application.
        """
        self.notebook.configure(takefocus=True)

        for index in range(len(self.notebook.tabs())):
            self.root.bind(
                f"<Control-Key-{index + 1}>",
                lambda _event, i=index: self._select_tab(i),
            )

        self.root.bind("<Control-Tab>", lambda _e: self._cycle_tab(1))
        self.root.bind("<Control-Shift-Tab>", lambda _e: self._cycle_tab(-1))
        # Windows reports Shift+Tab as ISO_Left_Tab under some keyboard
        # layouts. Binding only <Control-Shift-Tab> leaves those users able to
        # go forwards through the tabs and not back.
        self.root.bind("<Control-ISO_Left_Tab>", lambda _e: self._cycle_tab(-1))

    def _select_tab(self, index: int) -> str:
        """
        Focus a tab by position. Returns "break" so the key is not also
        handled by whatever widget currently has focus.
        """
        try:
            tabs = self.notebook.tabs()
            if 0 <= index < len(tabs):
                self.notebook.select(tabs[index])
                self.notebook.focus_set()
        except Exception as e:
            # A key binding must never be able to take the window down.
            log.debug("Could not switch tab: %s", e)
        return "break"

    def _cycle_tab(self, step: int) -> str:
        """Next or previous tab, wrapping at both ends."""
        try:
            tabs = self.notebook.tabs()
            if tabs:
                current = tabs.index(self.notebook.select())
                self._select_tab((current + step) % len(tabs))
        except Exception as e:
            log.debug("Could not cycle tab: %s", e)
        return "break"

    def _on_tab_changed(self, event=None) -> None:
        try:
            selected = self.notebook.select()
            if selected == str(self.insights_page):
                self.insights_page.refresh()
            elif selected == str(self.devices_page):
                self.devices_page.refresh()
        except Exception as e:
            log.error("Tab switch refresh failed: %s", e)

    def update_status_bar(self, msg: str) -> None:
        self._status_var.set(msg)

    def _on_quit(self) -> None:
        self.quit_app()
