"""
processes_page.py - Processes tab for ProtBot.
Shows real-time usage statistics for all tracked applications.
"""

import os
import csv

from core.logging_setup import get_logger
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# ── Colours ──────────────────────────────────────────────────────────────────
# The palette, the high-contrast variant and the WCAG contrast checks all live
# in ui/theme.py (AUDIT ST-06). This used to be nine hex literals copied into
# six files, which is what made a high-contrast mode impossible to add — there
# was no single thing to swap, and no single thing to measure.
from ui.theme import (  # noqa: F401
    ACCENT, ACCENT_TEXT, BG, BG2, BG3, BORDER, DANGER_BG, ERROR, FOCUS,
    ON_ACCENT, ON_DANGER, SUCCESS, TEXT, TEXT2, TEXT3, WARNING,
)

# ── Color Scheme ─────────────────────────────────────────────────────────────

log = get_logger("ui.processes")


def _fmt_sec(seconds: int) -> str:
    """Format seconds as 'Xh Ym' or 'Ym' or '0m'."""
    if seconds <= 0:
        return "0m"
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


class ProcessesPage(ttk.Frame):
    def __init__(self, parent, db, config, monitor) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.monitor = monitor
        self.configure(style='TFrame')
        # local app id → seconds used today on the user's *other* devices.
        # Filled from the running sync client; empty whenever sync is off, or
        # the group figure is too old or too stale-dated to enforce against.
        self._remote_usage: dict = {}
        self._linked_device_count: int = 1
        self._build_ui()
        self.refresh()
        self._schedule_sync()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Summary cards ────────────────────────────────────────────────────
        cards_frame = ttk.Frame(self, style='TFrame')
        cards_frame.pack(fill='x', padx=12, pady=(10, 6))

        self._card_tracked  = self._make_card(cards_frame, "Total Tracked",  "0", BG2, BG3)
        self._card_running  = self._make_card(cards_frame, "Running Now",     "0", BG2, SUCCESS)
        self._card_overlimit = self._make_card(cards_frame, "Over Limit Today","0", BG2, ERROR)
        self._card_devices   = self._make_card(cards_frame, "Linked Devices", "1", BG2, '#7c3aed')

        self._card_tracked.pack(side='left', fill='both', expand=True, padx=(0, 6))
        self._card_running.pack(side='left', fill='both', expand=True, padx=(0, 6))
        self._card_overlimit.pack(side='left', fill='both', expand=True, padx=(0, 6))
        self._card_devices.pack(side='left', fill='both', expand=True)

        # ── Treeview ─────────────────────────────────────────────────────────
        tree_frame = ttk.Frame(self, style='TFrame')
        tree_frame.pack(fill='both', expand=True, padx=12, pady=(0, 4))

        cols = ("Device", "App Name", "Category", "Status", "Today", "This Week",
                "Daily Limit", "Weekly Limit", "Progress")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show='headings', selectmode='browse')

        widths = {
            "Device":       110,
            "App Name":     140,
            "Category":     90,
            "Status":       90,
            "Today":        80,
            "This Week":    85,
            "Daily Limit":  90,
            "Weekly Limit": 95,
            "Progress":     90,
        }
        for col in cols:
            anchor = 'center' if col in ("Status", "Today", "This Week", "Daily Limit", "Weekly Limit", "Progress") else 'w'
            self._tree.heading(col, text=col, anchor=anchor)
            self._tree.column(col, width=widths[col], minwidth=50, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient='vertical',   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient='horizontal', command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self._tree.pack(fill='both', expand=True)

        self._tree.tag_configure('running',   foreground=SUCCESS)
        self._tree.tag_configure('stopped',   foreground=TEXT2)
        self._tree.tag_configure('overlimit', foreground=ERROR)
        self._tree.tag_configure('mobile',    foreground='#7c3aed')

        # ── Bottom toolbar ────────────────────────────────────────────────────
        btn_frame = ttk.Frame(self, style='TFrame')
        btn_frame.pack(fill='x', padx=12, pady=(2, 8))

        ttk.Button(btn_frame, text="Set Limits…",
                   command=self.set_limits).pack(side='left', padx=(0, 6))
        ttk.Button(btn_frame, text="Clear Today's Data",
                   command=self.clear_today, style='Danger.TButton').pack(side='left', padx=(0, 6))
        ttk.Button(btn_frame, text="Export CSV",
                   command=self.export_csv).pack(side='left', padx=(0, 6))

        self._bottom_info = tk.StringVar()
        tk.Label(btn_frame, textvariable=self._bottom_info,
                 bg=BG, fg=TEXT2, font=('Segoe UI', 9)).pack(side='right')

        ttk.Button(btn_frame, text="Force Scan Now",
                   command=self._force_scan).pack(side='left', padx=(0, 6))

    def _make_card(self, parent, title: str, value: str,
                   bg_color: str, accent_color: str) -> tk.Frame:
        card = tk.Frame(parent, bg=bg_color, bd=0, relief='flat')
        tk.Label(card, text=title, bg=bg_color, fg=TEXT2,
                 font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=(8, 0))
        lbl = tk.Label(card, text=value, bg=bg_color, fg=accent_color,
                       font=('Segoe UI', 22, 'bold'))
        lbl.pack(anchor='w', padx=12, pady=(0, 8))
        card._value_label = lbl
        card._title = title
        card._bg = bg_color
        card._accent = accent_color
        return card

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not hasattr(self, '_tree'):
            return
        try:
            status = self.monitor.get_status()
            apps   = self.db.get_all_tracked_apps()
        except Exception:
            return

        # Remember selection
        selected_iid = self._tree.focus()
        selected_app_id = self._iid_to_app_id.get(selected_iid) if hasattr(self, '_iid_to_app_id') else None

        self._tree.delete(*self._tree.get_children())
        self._iid_to_app_id = {}

        total_tracked = len(apps)
        running_count = 0
        over_limit_count = 0
        restore_iid = None

        device_label = "\U0001f5a5 This PC"
        for app in apps:
            app_id       = app["id"]
            name         = app.get("name", "")
            category     = app.get("category") or "Custom"
            daily_lim    = app.get("daily_limit_min", 0) or 0
            weekly_lim   = app.get("weekly_limit_min", 0) or 0
            app_status   = status.get(app_id, {})
            today_sec    = app_status.get("today_sec", 0)
            week_sec     = app_status.get("week_sec", 0)
            is_running   = app_status.get("running", False)

            # Add live session time for running apps
            if is_running and app_id in self.monitor.active_sessions:
                try:
                    from datetime import datetime as _dt
                    elapsed = (_dt.now() - self.monitor.active_sessions[app_id]["start_time"]).total_seconds()
                    today_sec += int(elapsed)
                    week_sec  += int(elapsed)
                except Exception:
                    pass

            status_str = "\u25b6 Running" if is_running else "\u2014 Stopped"
            if is_running:
                running_count += 1

            today_str  = _fmt_sec(today_sec)
            week_str   = _fmt_sec(week_sec)
            daily_str  = f"{daily_lim} min" if daily_lim else "\u2014"
            weekly_str = f"{weekly_lim} min" if weekly_lim else "\u2014"

            # Progress
            if daily_lim and daily_lim > 0:
                pct = today_sec / (daily_lim * 60) * 100
                if pct >= 100:
                    progress_str = f"\u26a0 {int(pct)}%"
                    over_limit_count += 1
                    tag = 'overlimit'
                else:
                    progress_str = f"{int(pct)}%"
                    tag = 'running' if is_running else 'stopped'
            else:
                progress_str = "\u2014"
                tag = 'running' if is_running else 'stopped'

            iid = self._tree.insert(
                "", 'end',
                values=(device_label, name, category, status_str, today_str, week_str,
                        daily_str, weekly_str, progress_str),
                tags=(tag,),
            )
            self._iid_to_app_id[iid] = app_id

            if selected_app_id and app_id == selected_app_id:
                restore_iid = iid

        # ── Cross-device rows ────────────────────────────────────────────────
        # One row per app that has time on the user's other devices, using the
        # names this device already knows. The protocol carries seconds per
        # app, not per app per device (server/models.py, SyncResp), so these
        # are labelled "Other devices" rather than named — saying which phone
        # would mean inventing a field no server is specified to send.
        for app in apps:
            seconds = int(self._remote_usage.get(app["id"], 0))
            if seconds <= 0:
                continue
            self._tree.insert(
                "", 'end',
                values=("\U0001f4f1 Other devices", app["name"],
                        app["category"] or "\u2014",
                        "\u2014 Remote", _fmt_sec(seconds), "\u2014",
                        "\u2014", "\u2014", "\u2014"),
                tags=('mobile',),
            )

        if restore_iid:
            self._tree.focus(restore_iid)
            self._tree.selection_set(restore_iid)

        # Update cards
        self._card_tracked._value_label.config(text=str(total_tracked))
        self._card_running._value_label.config(text=str(running_count))
        self._card_overlimit._value_label.config(text=str(over_limit_count))
        self._card_devices._value_label.config(text=str(self._linked_device_count))

        # Show live monitor diagnostics
        poll_time = self.monitor.last_poll_time
        proc_count = self.monitor.last_poll_proc_count
        psutil_ok = self.monitor.psutil_available
        thread_alive = self.monitor._thread and self.monitor._thread.is_alive()
        last_error = self.monitor.last_poll_error

        if not psutil_ok:
            diag = "  [ERROR: psutil not installed — run install.bat!]"
        elif not thread_alive:
            diag = "  [ERROR: monitor thread not running!]"
        elif poll_time is None:
            diag = "  [Waiting for first poll...]"
        elif last_error:
            diag = f"  [Poll error: {last_error[:60]}]"
        else:
            diag = (f"  | Monitor: OK | Processes seen: {proc_count} | "
                    f"Last scan: {poll_time.strftime('%H:%M:%S')}")

        self._bottom_info.set(
            f"Refreshed: {datetime.now().strftime('%H:%M:%S')}{diag}"
        )

    def _force_scan(self) -> None:
        """Trigger an immediate poll and refresh after a short delay."""
        self.monitor.trigger_poll()
        self.after(800, self.refresh)

    # ── Cross-device sync ─────────────────────────────────────────────────────
    #
    # This page used to fetch its own copy of the group totals, with
    #
    #     GET {server_url}/sync/{device_id}
    #
    # on a fifteen-minute timer. That is AUDIT SF-09 exactly: no credential at
    # all, and the device id — which was the only thing standing between a
    # stranger and this user's data — in a URL path, where it lands in every
    # access log between here and the server. It also parsed an `appDetails`
    # field the protocol does not define (server/models.py), so it was reading
    # a response no server was ever specified to send.
    #
    # The app already runs one sync client, on its own thread, authenticated,
    # with the staleness and clamping rules in core/syncproto.py behind it. A
    # view should read what that client holds rather than keep a second,
    # weaker copy. Nothing here does I/O now.

    def _schedule_sync(self) -> None:
        """Re-read the sync client's totals every fifteen minutes."""
        self._do_sync()
        self.after(900_000, self._schedule_sync)

    def _do_sync(self) -> None:
        """
        Refresh the cross-device figures from the running sync client.

        Reads memory only, so it runs on the Tk thread with no worker and no
        network. Wrapped whole because this is called on a timer: a failure
        here must cost one refresh, not the page.
        """
        client = getattr(self.monitor, "sync_client", None)
        if client is None:
            return
        try:
            status = client.status()
            if not status.get("enabled"):
                self._remote_usage = {}
                self._linked_device_count = 1
                return

            remote = {}
            for app in self.db.get_all_tracked_apps():
                seconds = int(client.remote_seconds_for(app["id"]) or 0)
                if seconds > 0:
                    remote[app["id"]] = seconds
            self._remote_usage = remote
            # The client knows how many devices it is syncing with only as
            # "more than this one", so this is 1 + whether anything came back.
            self._linked_device_count = 1 + len(self.config.get("linked_devices") or [])
        except Exception as e:
            log.warning("Could not read cross-device usage: %s", e)

    # ── Set Limits ────────────────────────────────────────────────────────────

    def set_limits(self) -> None:
        iid = self._tree.focus()
        if not iid:
            messagebox.showinfo("No Selection", "Please select an app to set limits for.", parent=self)
            return
        app_id = self._iid_to_app_id.get(iid)
        if app_id is None:
            return

        apps = self.db.get_all_tracked_apps()
        app = next((a for a in apps if a["id"] == app_id), None)
        if not app:
            return

        dialog = tk.Toplevel(self)
        dialog.title(f"Set Limits — {app['name']}")
        dialog.geometry("360x220")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(dialog, text=f"Usage limits for: {app['name']}",
                 bg=BG, fg=TEXT, font=('Segoe UI', 11, 'bold')).pack(padx=16, pady=(14, 8), anchor='w')

        frm = ttk.Frame(dialog, style='TFrame')
        frm.pack(fill='x', padx=16)
        frm.columnconfigure(1, weight=1)

        tk.Label(frm, text="Daily limit (minutes):", bg=BG, fg=TEXT2,
                 font=('Segoe UI', 10)).grid(row=0, column=0, sticky='w', pady=(0, 8))
        daily_var = tk.IntVar(value=app.get("daily_limit_min", 0))
        ttk.Spinbox(frm, from_=0, to=1440, textvariable=daily_var, width=10).grid(
            row=0, column=1, sticky='w', padx=(8, 0), pady=(0, 8))

        tk.Label(frm, text="Weekly limit (minutes):", bg=BG, fg=TEXT2,
                 font=('Segoe UI', 10)).grid(row=1, column=0, sticky='w')
        weekly_var = tk.IntVar(value=app.get("weekly_limit_min", 0))
        ttk.Spinbox(frm, from_=0, to=10080, textvariable=weekly_var, width=10).grid(
            row=1, column=1, sticky='w', padx=(8, 0))

        tk.Label(dialog, text="Set to 0 to disable the limit.",
                 bg=BG, fg=TEXT2, font=('Segoe UI', 9)).pack(padx=16, pady=(6, 0), anchor='w')

        def save() -> None:
            self.db.set_app_limits(app_id, daily_var.get(), weekly_var.get())
            dialog.destroy()
            self.refresh()

        btn_frame = ttk.Frame(dialog, style='TFrame')
        btn_frame.pack(fill='x', padx=16, pady=(12, 12))
        ttk.Button(btn_frame, text="Save", command=save, style='Accent.TButton').pack(side='right', padx=(6, 0))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='right')

    # ── Clear Today's Data ────────────────────────────────────────────────────

    def clear_today(self) -> None:
        if messagebox.askyesno(
            "Clear Today's Data",
            "Delete all usage sessions recorded today?\nThis cannot be undone.",
            parent=self,
        ):
            try:
                from datetime import date
                today = date.today().isoformat()
                with self.db._conn:
                    self.db._conn.execute(
                        "DELETE FROM usage_sessions WHERE date = ?;", (today,)
                    )
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=self)
            self.refresh()

    # ── Export CSV ────────────────────────────────────────────────────────────

    def export_csv(self) -> None:
        docs_dir = os.path.join(os.path.expanduser("~"), "Documents")
        os.makedirs(docs_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(docs_dir, f"ProtBot_export_{timestamp}.csv")

        try:
            apps = self.db.get_all_tracked_apps()
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["App Name", "Category", "Date", "Total Time (sec)", "Total Time (h:m)"])
                for app in apps:
                    history = self.db.get_usage_history(app["id"], days=30)
                    for row in history:
                        secs = row.get("total_sec", 0)
                        writer.writerow([
                            app["name"],
                            app.get("category", ""),
                            row.get("date", ""),
                            secs,
                            _fmt_sec(secs),
                        ])
            messagebox.showinfo(
                "Export Complete",
                f"Usage data exported to:\n{filename}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc), parent=self)
