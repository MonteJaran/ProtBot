"""
devices_page.py - Devices & Plan management tab for ProtBot.

Sections
--------
1. This Device   — device ID, copy, server registration
2. Linked Devices — list, link-new (8-char code), join-with-code
3. Your Plan     — freemium vs premium feature comparison + upgrade CTA
"""

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from core import licensing
from core.logging_setup import get_logger
from ui import a11y
# The nine core colours (and the high-contrast alternative) live in
# ui/theme.py; TEXT3/GOLD/PURPLE are this page's own — see that module's
# docstring for why. theme.apply_to_modules() re-points the imported names
# in place before this page is ever built (ui/app.py, MainApp.__init__).
from ui.theme import BG, BG2, BG3, ACCENT, TEXT, TEXT2, SUCCESS, WARNING, ERROR

log = get_logger("devices")

# ── Colour palette (matches app.py) ──────────────────────────────────────────
TEXT3   = '#6a6a7a'   # dimmed — used for not-yet-built ("planned") features
GOLD    = '#fbbf24'
PURPLE  = '#a78bfa'

# ── Plan feature definitions ──────────────────────────────────────────────────
#
# IMPORTANT: only list a feature here once it actually works in the shipped
# build. Advertising features that do not exist is deceptive advertising, and
# it becomes a refund and chargeback problem the moment the app takes money.
#
# Everything still to be built lives in _PLANNED_FEATURES below and is
# rendered in a clearly separated "Planned" section — never mixed in with what
# a customer would be paying for today. See ROADMAP.md for the full plan.

# Shipping today, on every install.
_FREE_FEATURES = [
    "Unlimited tracked apps",
    "60-second polling",
    "Daily & weekly usage reports",
    "Desktop notifications at your limit",
    "Automatic app closing when over limit",
    "Usage insights: peak hours, categories, top apps",
    "CSV export",
    "Excel (.xlsx) export",
    "PDF report export",
    "Pattern recognition across your history",
    "All data stored locally on your PC",
    "Automatic cleanup of old history",
    "Scheduled focus hours",
]

# Shipping today, but only for Premium. Keep this empty until a paid tier
# genuinely gates something — an empty list renders as "not available yet".
_PREMIUM_FEATURES: list = []

# Not built yet. Shown greyed out under a "Planned" heading so the intent is
# recorded without being sold. Move an entry up to _PREMIUM_FEATURES only when
# it works end to end in the shipped build.
_PLANNED_FEATURES = [
    "Cross-device sync",
    "Predictive distraction alerts",
    "Team challenges & leaderboards",
    "Priority support",
]


class DevicesPage(ttk.Frame):
    def __init__(self, parent, db, config, monitor):
        super().__init__(parent, style='TFrame')
        self.db      = db
        self.config  = config
        self.monitor = monitor

        self._link_countdown    = [None]
        self._link_key          = tk.StringVar(value="")
        self._link_seconds      = [0]
        self._registering       = False   # prevents double-fire
        self._reg_timeout_id    = None    # after-id for timeout watchdog

        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Scrollable canvas wrapper
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill='both', expand=True)

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb     = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)

        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        self._inner = tk.Frame(canvas, bg=BG)
        self._win_id = canvas.create_window((0, 0), window=self._inner, anchor='nw')

        self._inner.bind('<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
            lambda e: canvas.itemconfig(self._win_id, width=e.width))

        # Mouse wheel
        canvas.bind('<MouseWheel>',
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units'))
        # Propagate wheel from all child widgets up to the canvas
        self._inner.bind_all('<MouseWheel>',
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units'))

        # Keyboard scroll. Tab reaches the canvas too, not just a click — a
        # Canvas is not focusable by default in Tk (AUDIT ST-06); see
        # ui/a11y.py's focus_scrollable for why that needed an explicit fix
        # rather than being something Tab traversal already handled.
        a11y.focus_scrollable(canvas, self.config)
        canvas.bind('<Button-1>', lambda e: canvas.focus_set())
        canvas.bind('<Up>',       lambda e: canvas.yview_scroll(-1, 'units'))
        canvas.bind('<Down>',     lambda e: canvas.yview_scroll( 1, 'units'))
        canvas.bind('<Prior>',    lambda e: canvas.yview_scroll(-5, 'units'))  # Page Up
        canvas.bind('<Next>',     lambda e: canvas.yview_scroll( 5, 'units'))  # Page Down
        canvas.bind('<Home>',     lambda e: canvas.yview_moveto(0))
        canvas.bind('<End>',      lambda e: canvas.yview_moveto(1))

        self._canvas = canvas
        self._populate()

    def _populate(self):
        for w in self._inner.winfo_children():
            w.destroy()

        # ── Section 1: This Device ─────────────────────────────────────────
        self._section_header(self._inner, "\U0001f4bb  This Device")
        self._build_this_device(self._inner)

        _sep(self._inner)

        # ── Section 2: Linked Devices ──────────────────────────────────────
        self._section_header(self._inner, "\U0001f517  Linked Devices")
        self._build_linked_devices(self._inner)

        _sep(self._inner)

        # ── Section 3: Your Plan ───────────────────────────────────────────
        self._section_header(self._inner, "\u2605  Your Plan")
        self._build_plan(self._inner)

        # Bottom padding
        tk.Frame(self._inner, bg=BG, height=24).pack(fill='x')

    # ── Section: This Device ──────────────────────────────────────────────────

    def _build_this_device(self, parent):
        card = _card(parent)

        dev_id = self.config.get("device_id") or ""

        if dev_id:
            # Show device ID with copy button
            row = tk.Frame(card, bg=BG2)
            row.pack(fill='x', pady=(0, 8))

            tk.Label(row, text="Device ID", bg=BG2, fg=TEXT2,
                     font=('Segoe UI', 9)).pack(side='left')

            _status_dot(row, SUCCESS, "Registered").pack(side='right')

            id_frame = tk.Frame(card, bg=BG3, bd=0)
            id_frame.pack(fill='x', pady=(0, 10))

            id_lbl = tk.Label(id_frame, text=dev_id,
                              bg=BG3, fg=TEXT,
                              font=('Courier New', 11, 'bold'),
                              padx=12, pady=8)
            id_lbl.pack(side='left', fill='x', expand=True)

            tk.Button(id_frame, text="Copy",
                      bg=ACCENT, fg='#fff',
                      font=('Segoe UI', 9, 'bold'),
                      relief='flat', bd=0, padx=10, pady=6,
                      activebackground='#c73652', activeforeground='#fff',
                      cursor='hand2',
                      command=lambda: self._copy(dev_id)).pack(side='right', padx=4, pady=4)

            tk.Label(card,
                     text="Keep this ID safe — it's your identity across all devices.\n"
                          "It is never linked to your email or personal data.",
                     bg=BG2, fg=TEXT2, font=('Segoe UI', 9),
                     justify='left', anchor='w').pack(fill='x')

        else:
            # Not registered yet
            tk.Label(card,
                     text="No device ID yet. Register to enable cross-device sync,\n"
                          "global statistics, and the team dashboard.",
                     bg=BG2, fg=TEXT2, font=('Segoe UI', 9),
                     justify='left', anchor='w').pack(fill='x', pady=(0, 10))

            email_row = tk.Frame(card, bg=BG2)
            email_row.pack(fill='x', pady=(0, 8))

            tk.Label(email_row, text="Email (optional):", bg=BG2, fg=TEXT2,
                     font=('Segoe UI', 9)).pack(side='left', padx=(0, 8))
            self._email_var = tk.StringVar()
            email_entry = ttk.Entry(email_row, textvariable=self._email_var, width=28)
            email_entry.pack(side='left')
            email_entry.bind('<Return>', lambda e: self._register_device())

            tk.Label(card,
                     text="Your email is used only to deliver your Device ID — it is\n"
                          "never stored on our servers.",
                     bg=BG2, fg=TEXT2, font=('Segoe UI', 9),
                     justify='left', anchor='w').pack(fill='x', pady=(0, 10))

            self._reg_btn = tk.Button(card, text="Register This Device",
                                      bg=ACCENT, fg='#fff',
                                      font=('Segoe UI', 10, 'bold'),
                                      relief='flat', bd=0, padx=16, pady=8,
                                      activebackground='#c73652',
                                      activeforeground='#fff',
                                      cursor='hand2',
                                      command=self._register_device)
            self._reg_btn.pack(anchor='w')

            self._reg_status = tk.Label(card, text="", bg=BG2, fg=TEXT2,
                                        font=('Segoe UI', 9))
            self._reg_status.pack(anchor='w', pady=(4, 0))

    # ── Section: Linked Devices ───────────────────────────────────────────────

    def _build_linked_devices(self, parent):
        card = _card(parent)

        dev_id     = self.config.get("device_id") or ""
        linked     = self.config.get("linked_devices") or []
        max_dev    = 10 if licensing.is_premium(self.config) else 2

        # Header row
        hdr = tk.Frame(card, bg=BG2)
        hdr.pack(fill='x', pady=(0, 10))
        tk.Label(hdr, text=f"Connected: {len(linked) + (1 if dev_id else 0)} / {max_dev}",
                 bg=BG2, fg=TEXT, font=('Segoe UI', 10, 'bold')).pack(side='left')

        if not dev_id:
            tk.Label(card, text="Register this device first to link other devices.",
                     bg=BG2, fg=TEXT2, font=('Segoe UI', 9)).pack(anchor='w')
            return

        # This device row
        self._device_row(card, "\U0001f4bb  This Device",
                         dev_id[:8] + "..." + dev_id[-4:],
                         "Active now", SUCCESS, is_self=True)

        # Linked device rows
        for info in linked:
            name     = info.get("name", "Unknown Device")
            short_id = info.get("id", "")
            short_id = short_id[:8] + "..." + short_id[-4:] if len(short_id) > 12 else short_id
            last_seen = info.get("last_seen", "")
            self._device_row(card, "\U0001f4f1  " + name, short_id,
                             f"Last seen: {last_seen}" if last_seen else "Never synced",
                             TEXT2, is_self=False,
                             on_remove=lambda i=info: self._remove_device(i))

        tk.Frame(card, bg=BG3, height=1).pack(fill='x', pady=(10, 10))

        # Action buttons
        btn_row = tk.Frame(card, bg=BG2)
        btn_row.pack(fill='x')

        at_limit = (len(linked) + 1) >= max_dev

        link_btn = tk.Button(btn_row,
                             text="+ Link New Device",
                             bg=BG3 if at_limit else SUCCESS,
                             fg=TEXT2 if at_limit else '#0a1a0a',
                             font=('Segoe UI', 9, 'bold'),
                             relief='flat', bd=0, padx=12, pady=6,
                             cursor='hand2' if not at_limit else 'arrow',
                             state='disabled' if at_limit else 'normal',
                             command=self._generate_link_key)
        link_btn.pack(side='left', padx=(0, 8))

        tk.Button(btn_row,
                  text="Join with Code",
                  bg=BG3, fg=TEXT,
                  font=('Segoe UI', 9),
                  relief='flat', bd=0, padx=12, pady=6,
                  activebackground=ACCENT, activeforeground='#fff',
                  cursor='hand2',
                  command=self._show_join_dialog).pack(side='left', padx=(8, 0))

        tk.Button(btn_row,
                  text="Match Apps…",
                  bg=BG3, fg=TEXT,
                  font=('Segoe UI', 9),
                  relief='flat', bd=0, padx=12, pady=6,
                  activebackground=ACCENT, activeforeground='#fff',
                  cursor='hand2',
                  command=self._show_match_apps_dialog).pack(side='left', padx=(8, 0))

        if at_limit and not licensing.is_premium(self.config):
            tk.Label(card,
                     text=f"Device limit reached ({max_dev}). A higher limit is planned "
                          f"but not available yet.",
                     bg=BG2, fg=WARNING, font=('Segoe UI', 9)).pack(anchor='w', pady=(8, 0))

        # Link key display (shown after "Link New Device" is clicked)
        self._key_frame = tk.Frame(card, bg=BG3)
        # Not packed until key is generated

    def _device_row(self, parent, name, short_id, status_text,
                    status_color, is_self, on_remove=None):
        row = tk.Frame(parent, bg='#0d1e38', bd=0)
        row.pack(fill='x', pady=2)

        tk.Label(row, text=name, bg='#0d1e38', fg=TEXT,
                 font=('Segoe UI', 9, 'bold'), width=22, anchor='w').pack(
            side='left', padx=(10, 4), pady=6)

        tk.Label(row, text=short_id, bg='#0d1e38', fg=TEXT2,
                 font=('Courier New', 8)).pack(side='left', padx=(0, 10))

        tk.Label(row, text=status_text, bg='#0d1e38', fg=status_color,
                 font=('Segoe UI', 9)).pack(side='left')

        if not is_self and on_remove:
            tk.Button(row, text="Remove",
                      bg='#0d1e38', fg=ERROR,
                      font=('Segoe UI', 9),
                      relief='flat', bd=0, padx=8,
                      activebackground='#7f1d1d', activeforeground=ERROR,
                      cursor='hand2',
                      command=on_remove).pack(side='right', padx=6, pady=4)

    # ── Section: Plan ─────────────────────────────────────────────────────────

    def _build_plan(self, parent):
        premium = licensing.is_premium(self.config)

        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill='x', padx=18, pady=(0, 6))
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        # ── Freemium card ──────────────────────────────────────────────────
        free_card = tk.Frame(outer, bg=BG2, bd=0)
        free_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

        free_hdr = tk.Frame(free_card, bg='#0f3460', height=48)
        free_hdr.pack(fill='x')
        free_hdr.pack_propagate(False)
        tk.Label(free_hdr, text="Free", bg='#0f3460', fg=TEXT,
                 font=('Segoe UI', 14, 'bold')).pack(side='left', padx=14, pady=10)
        if not premium:
            tk.Label(free_hdr, text="CURRENT", bg='#0f3460', fg=SUCCESS,
                     font=('Segoe UI', 9, 'bold')).pack(side='right', padx=10)

        tk.Label(free_card, text="$0 / month",
                 bg=BG2, fg=TEXT2, font=('Segoe UI', 10)).pack(
            anchor='w', padx=14, pady=(8, 6))

        for feat in _FREE_FEATURES:
            _feature_row(free_card, feat, unlocked=True, bg=BG2)

        tk.Frame(free_card, bg=BG, height=12).pack(fill='x')

        # ── Premium card ───────────────────────────────────────────────────
        prem_bg  = '#0f1e38'
        prem_hdr = '#1a0a3e'

        prem_card = tk.Frame(outer, bg=prem_bg, bd=0)
        prem_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0))

        hdr_frame = tk.Frame(prem_card, bg=prem_hdr, height=48)
        hdr_frame.pack(fill='x')
        hdr_frame.pack_propagate(False)
        tk.Label(hdr_frame, text="★ Premium", bg=prem_hdr, fg=GOLD,
                 font=('Segoe UI', 14, 'bold')).pack(side='left', padx=14, pady=10)
        tk.Label(hdr_frame, text="IN DEVELOPMENT", bg=prem_hdr, fg=TEXT3,
                 font=('Segoe UI', 9, 'bold')).pack(side='right', padx=10)

        # No price is shown while Premium cannot actually be bought. Pricing
        # comes back here once payment and server-side entitlement are live.
        tk.Label(prem_card,
                 text="Not available yet",
                 bg=prem_bg, fg=TEXT2,
                 font=('Segoe UI', 10)).pack(anchor='w', padx=14, pady=(8, 2))

        # Anything already shipping behind the paid tier.
        for feat in _PREMIUM_FEATURES:
            _feature_row(prem_card, feat, unlocked=premium, bg=prem_bg)

        # Everything still to be built — dimmed and explicitly labelled.
        tk.Label(prem_card,
                 text="Planned",
                 bg=prem_bg, fg=TEXT3,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=14, pady=(8, 2))

        for feat in _PLANNED_FEATURES:
            _feature_row(prem_card, feat, unlocked=False, bg=prem_bg, planned=True)

        tk.Label(prem_card,
                 text="Not built yet, and not included in any purchase.\n"
                      "See ROADMAP.md for the full plan.",
                 bg=prem_bg, fg=TEXT3, justify='left',
                 font=('Segoe UI', 9)).pack(anchor='w', padx=14, pady=(8, 12))

    # ── Helpers: API calls ────────────────────────────────────────────────────

    def _register_device(self):
        # Prevent double-fire (button click + Enter key race, or window-switch retry)
        if self._registering:
            return

        server = self.config.get("server_url") or ""
        if not server:
            messagebox.showwarning(
                "Server Not Configured",
                "Enter the Firebase function URL in Settings > Server URL first.",
                parent=self)
            return

        self._registering = True
        if hasattr(self, '_reg_btn'):
            self._reg_btn.config(state='disabled', text="Registering...")
        if hasattr(self, '_reg_status'):
            self._reg_status.config(text="Contacting server...", fg=TEXT2)

        email = self._email_var.get().strip() if hasattr(self, '_email_var') else ""

        # Watchdog: if no response in 12 s, unlock the button so user can retry
        def _timeout():
            if self._registering:
                self._registering = False
                self._reg_error("Request timed out — please try again.")

        self._reg_timeout_id = self.after(12000, _timeout)

        def _do():
            import socket

            from core import syncclient

            hostname = socket.gethostname() or "Windows PC"
            # The same registration this device's sync client would perform
            # itself, rather than a second implementation of it — id *and*
            # bearer token (AUDIT SF-09) both land in config from one call.
            dev_id = syncclient.register_device(
                self.config, device_name=hostname, email=email,
                platform="Windows")
            if dev_id:
                self.after(0, lambda: self._reg_done(dev_id))
            else:
                self.after(0, lambda: self._reg_error(
                    "Could not reach the server, or it refused the request."))

        threading.Thread(target=_do, daemon=True).start()

    def _reg_done(self, dev_id):
        # Cancel watchdog
        if self._reg_timeout_id:
            self.after_cancel(self._reg_timeout_id)
            self._reg_timeout_id = None
        self._registering = False
        if hasattr(self, '_reg_status'):
            self._reg_status.config(text="Registered!", fg=SUCCESS)
        self.after(600, self._populate)

    def _reg_error(self, msg):
        # Cancel watchdog
        if self._reg_timeout_id:
            self.after_cancel(self._reg_timeout_id)
            self._reg_timeout_id = None
        self._registering = False
        if hasattr(self, '_reg_btn'):
            self._reg_btn.config(state='normal', text="Register This Device")
        if hasattr(self, '_reg_status'):
            self._reg_status.config(text=f"Error: {msg}", fg=ERROR)

    def _generate_link_key(self):
        server = self.config.get("server_url") or ""
        dev_id = self.config.get("device_id") or ""
        if not server or not dev_id:
            messagebox.showwarning("Not Ready",
                                   "Register this device first.", parent=self)
            return

        def _do():
            from core import linking

            try:
                session = linking.request_link(self.config)
                self.after(0, lambda: self._show_link_key(session))
            except linking.LinkError as exc:
                self.after(0, lambda e=exc: messagebox.showerror(
                    "Error", str(e), parent=self))

        threading.Thread(target=_do, daemon=True).start()

    # ── Showing a link code ───────────────────────────────────────────────

    # Pixels per QR module. Small enough that a version-3 code fits a modest
    # dialog, large enough that a phone camera resolves it at arm's length —
    # below about 5 px the code becomes a coin toss on a scaled display.
    QR_MODULE_PX = 7
    QR_QUIET_MODULES = 4

    def _show_link_key(self, session):
        """
        The link code, as a QR to scan and as characters to type.

        Both, always. The QR is the fast path, and a camera that will not focus
        is a bad reason to be unable to link a device — so the characters stay
        on screen next to it rather than behind a "having trouble?" link.

        Takes an already-built linking.LinkSession: request_link() either
        returns one it has already validated, or raises before this is ever
        called, so there is nothing left here to fail on.
        """
        if self._link_countdown[0]:
            self.after_cancel(self._link_countdown[0])

        if hasattr(self, '_key_popup') and self._key_popup.winfo_exists():
            self._key_popup.destroy()

        popup = tk.Toplevel(self)
        popup.title("Link New Device")
        popup.configure(bg=BG)
        popup.transient(self)
        popup.resizable(False, False)
        a11y.bind_escape_closes(popup)
        self._key_popup = popup

        tk.Label(popup, text="Scan this with ProtBot on your phone",
                 bg=BG, fg=TEXT, font=('Segoe UI', 11, 'bold'),
                 ).pack(pady=(16, 2))
        tk.Label(popup, text="Devices tab → Link a device → Scan",
                 bg=BG, fg=TEXT2, font=('Segoe UI', 9)).pack(pady=(0, 10))

        self._draw_qr(popup, session)

        tk.Label(popup, text="or type this code",
                 bg=BG, fg=TEXT2, font=('Segoe UI', 9)).pack(pady=(12, 2))
        tk.Label(popup, text=session.formatted_key(), bg=BG3, fg=SUCCESS,
                 font=('Courier New', 22, 'bold'), padx=20, pady=8,
                 ).pack(fill='x', padx=24)

        tk.Button(popup, text="Copy Code", bg=ACCENT, fg='#fff',
                  font=('Segoe UI', 9, 'bold'), relief='flat', bd=0,
                  padx=14, pady=6,
                  command=lambda: self._copy(session.key)).pack(pady=(10, 2))

        self._countdown_lbl = tk.Label(popup, text="", bg=BG, fg=WARNING,
                                       font=('Segoe UI', 9))
        self._countdown_lbl.pack()

        # Anyone who scans this joins the device group and can read its usage
        # totals. Saying so is cheaper than explaining it afterwards.
        tk.Label(popup,
                 text="Anyone who scans this can see your usage totals.\n"
                      "Do not share it or leave it in a screen recording.",
                 bg=BG, fg=TEXT2, font=('Segoe UI', 8), justify='center',
                 ).pack(pady=(6, 14), padx=20)

        self._tick_link_countdown(popup, session)

    def _draw_qr(self, parent, session) -> None:
        """
        Draw the code on a Canvas, one rectangle per dark module.

        Always black on white, whatever the app's theme. A QR rendered light-on-
        dark is inverted, and while some scanners cope, plenty do not — and the
        failure looks like a broken feature rather than a contrast problem.
        """
        try:
            matrix = session.matrix()
        except Exception as exc:
            log.error("Could not build the link QR code: %s", exc)
            tk.Label(parent,
                     text="Could not draw the code — use the characters below.",
                     bg=BG, fg=WARNING, font=('Segoe UI', 9)).pack(pady=8)
            return

        module = self.QR_MODULE_PX
        quiet = self.QR_QUIET_MODULES
        span = (len(matrix) + quiet * 2) * module

        canvas = tk.Canvas(parent, width=span, height=span, bg='#ffffff',
                           highlightthickness=0, bd=0)
        canvas.pack()

        for row, cells in enumerate(matrix):
            for col, dark in enumerate(cells):
                if not dark:
                    continue
                left = (col + quiet) * module
                top = (row + quiet) * module
                canvas.create_rectangle(left, top, left + module, top + module,
                                        fill='#000000', outline='')

    def _tick_link_countdown(self, popup, session) -> None:
        """
        Count down, and close the dialog when the code dies.

        The window closing is the point. A code left on screen after the server
        has forgotten it is worse than no code: someone scans it, waits, and
        gets an error that says nothing about why.
        """
        if not popup.winfo_exists():
            return

        remaining = session.seconds_left()
        if remaining <= 0:
            popup.destroy()
            return

        minutes, seconds = divmod(remaining, 60)
        if self._countdown_lbl.winfo_exists():
            self._countdown_lbl.config(text=f"Expires in {minutes}:{seconds:02d}")

        self._link_countdown[0] = self.after(
            1000, lambda: self._tick_link_countdown(popup, session))

    def _show_join_dialog(self):
        dev_id = self.config.get("device_id") or ""
        if not dev_id:
            messagebox.showwarning("Not Ready",
                                   "Register this device first.", parent=self)
            return

        dialog = tk.Toplevel(self)
        dialog.title("Join with Code")
        dialog.geometry("340x160")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        a11y.bind_escape_closes(dialog)

        tk.Label(dialog, text="Enter the 8-character code from the other device:",
                 bg=BG, fg=TEXT2, font=('Segoe UI', 9),
                 wraplength=300).pack(pady=(16, 8))

        code_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=code_var,
                          font=('Courier New', 16), width=12, justify='center')
        entry.pack(pady=(0, 8))
        entry.focus_set()

        status_lbl = tk.Label(dialog, text="", bg=BG, fg=TEXT2,
                              font=('Segoe UI', 9))
        status_lbl.pack()

        def _join():
            code = code_var.get().strip().upper()
            if len(code) != 8:
                status_lbl.config(text="Code must be 8 characters.", fg=ERROR)
                return
            status_lbl.config(text="Joining...", fg=TEXT2)

            def _do():
                from core import linking

                try:
                    grp = linking.join_link(self.config, code)
                    self.after(0, lambda: self._join_done(dialog, grp))
                except linking.LinkError as exc:
                    self.after(0, lambda e=exc: status_lbl.config(
                        text=f"Error: {e}", fg=ERROR))

            threading.Thread(target=_do, daemon=True).start()

        ttk.Button(dialog, text="Join", style='Accent.TButton',
                   command=_join).pack(pady=(4, 0))

        dialog.bind('<Return>', lambda e: _join())

    def _join_done(self, dialog, grp_id: str):
        dialog.destroy()
        messagebox.showinfo("Linked!",
                            f"Devices linked successfully.\nGroup: {grp_id[:8]}...",
                            parent=self)
        # Fetch live group device list from server so the other device shows up
        self._refresh_group_devices()

    # ── Matching apps across devices by hand ────────────────────────────────
    #
    # syncproto.canonical_app_key is a best-effort guess and says so: a
    # package named after its vendor rather than its product — Firefox.exe
    # meeting org.mozilla.firefox — is a case no string rule resolves
    # without a brand list. This dialog is the fallback: type the same key
    # on both devices and they join, the same as if the guess had matched.
    # See STATUS.md and core/syncclient.py's set_manual_key.

    def _show_match_apps_dialog(self):
        from core import syncproto

        dialog = tk.Toplevel(self)
        dialog.title("Match Apps Across Devices")
        dialog.geometry("520x460")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.resizable(False, True)
        a11y.bind_escape_closes(dialog)

        tk.Label(
            dialog,
            text="ProtBot guesses which app here is the same as one on another\n"
                 "device by its name. When that guess is wrong, give the app the\n"
                 "same sync key here and on the other device to join them by hand.",
            bg=BG, fg=TEXT2, font=('Segoe UI', 9), justify='left',
            wraplength=480,
        ).pack(anchor='w', padx=16, pady=(14, 10))

        # Scrollable list — the app count is unbounded, unlike everything
        # else in this dialog.
        outer = tk.Frame(dialog, bg=BG)
        outer.pack(fill='both', expand=True, padx=16)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        a11y.focus_scrollable(canvas, self.config)
        canvas.bind('<Button-1>', lambda e: canvas.focus_set())
        canvas.bind('<Up>',   lambda e: canvas.yview_scroll(-1, 'units'))
        canvas.bind('<Down>', lambda e: canvas.yview_scroll(1, 'units'))

        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
            lambda e: canvas.itemconfig(win_id, width=e.width))

        try:
            apps = self.db.get_all_tracked_apps() or []
        except Exception as exc:
            log.error("Could not read tracked apps for the match dialog: %s", exc)
            apps = []

        if not apps:
            tk.Label(inner, text="No tracked apps yet.",
                     bg=BG, fg=TEXT2, font=('Segoe UI', 9)).pack(
                anchor='w', pady=8)

        for app in apps:
            self._match_app_row(inner, app, syncproto)

        tk.Button(dialog, text="Close", bg=BG3, fg=TEXT,
                  font=('Segoe UI', 9), relief='flat', bd=0, padx=14, pady=6,
                  activebackground=ACCENT, activeforeground='#fff',
                  cursor='hand2', command=dialog.destroy).pack(pady=(6, 14))

    def _match_app_row(self, parent, app, syncproto) -> None:
        from core import syncclient

        app_id = app.get("id")
        name = app.get("name", "") or app.get("exe_name", "")
        auto_key = syncproto.canonical_app_key(name)
        manual = syncclient.manual_key_for(self.config, app_id)

        row = tk.Frame(parent, bg='#0d1e38')
        row.pack(fill='x', pady=3)

        tk.Label(row, text=name, bg='#0d1e38', fg=TEXT,
                 font=('Segoe UI', 9, 'bold'), width=16, anchor='w',
                 wraplength=110, justify='left').pack(
            side='left', padx=(10, 6), pady=6)

        key_var = tk.StringVar(value=manual or auto_key)
        entry = ttk.Entry(row, textvariable=key_var, width=16)
        entry.pack(side='left', padx=(0, 6))

        status = tk.Label(row, bg='#0d1e38', fg=TEXT2, font=('Segoe UI', 8),
                          width=8, anchor='w')
        status.pack(side='left', padx=(0, 6))

        def refresh_status() -> None:
            current = syncclient.manual_key_for(self.config, app_id)
            status.config(text="custom" if current else "automatic",
                         fg=ACCENT if current else TEXT2)

        def save(_event=None) -> None:
            typed = key_var.get()
            if syncproto.canonical_app_key(typed) == auto_key:
                # Typing back the automatic key is the same as not
                # overriding it — clear rather than store a no-op override,
                # so "automatic" still reads as automatic afterwards.
                syncclient.clear_manual_key(self.config, app_id)
            else:
                stored = syncclient.set_manual_key(self.config, app_id, typed)
                key_var.set(stored)
            refresh_status()

        def reset() -> None:
            syncclient.clear_manual_key(self.config, app_id)
            key_var.set(auto_key)
            refresh_status()

        entry.bind('<Return>', save)
        entry.bind('<FocusOut>', save)

        tk.Button(row, text="Reset", bg='#0d1e38', fg=TEXT2,
                  font=('Segoe UI', 8), relief='flat', bd=0, padx=6,
                  activebackground=BG3, activeforeground=TEXT,
                  cursor='hand2', command=reset).pack(side='left')

        refresh_status()

    def _refresh_group_devices(self):
        """Fetch group member list from server, update config, repopulate UI."""
        dev_id     = self.config.get("device_id") or ""
        server_url = self.config.get("server_url") or ""
        if not dev_id or not server_url:
            self._populate()
            return

        def _fetch():
            from core import linking

            try:
                # No device id in this request at all, path or body — see
                # linking.list_group and AUDIT SF-09.
                devices = linking.list_group(self.config)
                others = [
                    {
                        "id":        d["id"],
                        "name":      d.get("name") or (d.get("platform") or "Unknown") + " Device",
                        "platform":  d.get("platform") or "Unknown",
                        "last_seen": _fmt_seen(d.get("seen")),
                    }
                    for d in devices
                    if not d.get("isOwn", False)
                ]
                self.config.set("linked_devices", others)
            except linking.LinkError:
                pass
            finally:
                self.after(0, self._populate)

        threading.Thread(target=_fetch, daemon=True).start()

    def _remove_device(self, device_info: dict):
        if not messagebox.askyesno("Remove Device",
                                   "Remove this device from your group?",
                                   parent=self):
            return
        linked = [d for d in (self.config.get("linked_devices") or [])
                  if d.get("id") != device_info.get("id")]
        self.config.set("linked_devices", linked)
        self._populate()

    def _activate_license(self):
        """
        Activate a licence key against the server.

        Runs off the UI thread: this is a network call, and doing it inline
        freezes the window for however long the server takes to answer.
        """
        key = self._license_var.get().strip() if hasattr(self, '_license_var') else ""
        if not key:
            messagebox.showinfo("Licence", "Enter your licence key first.",
                                parent=self)
            return

        def _work():
            result = licensing.activate(self.config, key)
            self.after(0, lambda r=result: _done(r))

        def _done(result):
            if result["ok"]:
                messagebox.showinfo("Licence", result["message"], parent=self)
                self._populate()          # redraw with the new entitlement
            else:
                messagebox.showwarning("Licence", result["message"], parent=self)

        threading.Thread(target=_work, daemon=True).start()

    def _open_upgrade(self):
        webbrowser.open("https://protbot.app/premium")

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    # ── Public refresh (called by tab switch) ─────────────────────────────────
    def refresh(self):
        # Re-fetch live group list from server every time the tab is opened
        self._refresh_group_devices()

    # ── Shared UI helpers ──────────────────────────────────────────────────────

    def _section_header(self, parent, text: str):
        tk.Label(parent, text=text,
                 bg=BG, fg=ACCENT,
                 font=('Segoe UI', 11, 'bold')).pack(
            anchor='w', padx=18, pady=(16, 6))


# ── Module-level helpers ──────────────────────────────────────────────────────

def _fmt_seen(unix_sec) -> str:
    """Convert a Unix timestamp (seconds) to a human-readable 'last seen' string."""
    if not unix_sec:
        return "Never"
    try:
        import datetime
        dt = datetime.datetime.fromtimestamp(int(unix_sec))
        now = datetime.datetime.now()
        diff = now - dt
        if diff.days == 0:
            h = diff.seconds // 3600
            if h == 0:
                return "Just now"
            return f"{h}h ago"
        if diff.days == 1:
            return "Yesterday"
        return dt.strftime("%b %d")
    except Exception:
        return ""


# ── Widget helpers ────────────────────────────────────────────────────────────

def _card(parent) -> tk.Frame:
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill='x', padx=18, pady=(0, 4))
    inner = tk.Frame(outer, bg=BG2, padx=14, pady=12)
    inner.pack(fill='x')
    return inner


def _sep(parent):
    tk.Frame(parent, bg=BG3, height=1).pack(fill='x', padx=18, pady=(4, 0))


def _status_dot(parent, color: str, label: str) -> tk.Label:
    return tk.Label(parent, text=f"\u25cf  {label}",
                    bg=BG2, fg=color, font=('Segoe UI', 9))


def _feature_row(parent, text: str, unlocked: bool, bg: str, planned: bool = False):
    """
    Render one feature line.

    planned=True dims the row and marks it "PLANNED" \u2014 Tk cannot blur text, so
    a muted colour plus an explicit label is how a not-yet-built feature is
    shown without implying it is included.
    """
    row = tk.Frame(parent, bg=bg)
    row.pack(fill='x', padx=14, pady=1)

    if planned:
        icon  = "\u25cb"          # hollow circle: not delivered
        color = TEXT3
    elif unlocked:
        icon  = "\u2705"
        color = TEXT
    else:
        icon  = "\U0001f512"
        color = TEXT2

    tk.Label(row, text=icon, bg=bg, fg=color,
             font=('Segoe UI', 9), width=2).pack(side='left')
    tk.Label(row, text=text, bg=bg, fg=color,
             font=('Segoe UI', 9), anchor='w').pack(side='left', padx=(4, 0))

    if planned:
        tk.Label(row, text="PLANNED", bg=bg, fg=TEXT3,
                 font=('Segoe UI', 9)).pack(side='right')
