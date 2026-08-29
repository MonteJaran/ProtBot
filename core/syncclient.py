"""
syncclient.py - Talking to the sync server.

The rules live in core/syncproto.py; this is the part with a socket in it. It
runs on its own thread, posts today's totals every half hour, keeps the group
totals it gets back, and hands them to the monitor so a limit counts phone and
PC time together.

Four properties this has to hold, and the reasoning for each:

  * **Never raises into the caller.** The monitor's poll loop is what enforces
    limits. If a DNS failure could propagate out of a sync call, a bad network
    would stop time being counted at all. Every public function here returns a
    value; none of them throw.

  * **Never blocks the monitor.** All I/O is on the sync thread. The monitor
    only ever reads a dict that is already in memory.

  * **Off unless the user turned it on.** No device id means no requests, not
    even a registration. Registration is the opt-in, and PRIVACY.md says so;
    an app that phones home before that would make the policy false.

  * **Failure is local-only, never permissive.** A server that is down, empty,
    slow or hostile results in limits enforced against local usage — the exact
    behaviour of the app before sync existed. There is no response that makes
    a limit looser than what this device measured itself; see
    syncproto.merge_app_total.

There is no server implementing this yet. The endpoint paths and payloads come
from server/models.py, and the client is tested against a fake transport, so
what is verified is the client's behaviour on every response shape — including
the ones a broken server would send.
"""

import json
import threading
import time
import urllib.error
import urllib.request

from core import syncproto
from core.logging_setup import get_logger
from core.version import __version__

log = get_logger("sync")

REQUEST_TIMEOUT = 10

# Responses are small: a total per tracked app. A user with 50 apps produces a
# few kilobytes. Anything past this is wrong and is not parsed.
MAX_RESPONSE_BYTES = 256 * 1024

# Backoff after a failed cycle. Starts near the normal interval because sync
# is not urgent, and caps well below a day so a device that was offline
# overnight resumes on its own instead of waiting for a restart.
BACKOFF_START_SEC = 60
BACKOFF_MAX_SEC = 30 * 60

ENDPOINT_REGISTER = "/register"
ENDPOINT_APPS = "/apps"
ENDPOINT_UPLOAD = "/upload"
ENDPOINT_SYNC = "/sync"


def _auth_header(token: str) -> dict:
    token = str(token or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


class Transport:
    """
    One HTTP POST, returning parsed JSON or None.

    A class rather than a function so tests can pass a fake in and exercise
    every response shape — timeout, 500, HTML error page, valid JSON with the
    wrong types — without a network or a server.
    """

    def __init__(self, base_url: str, timeout: int = REQUEST_TIMEOUT,
                token: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        # The device's bearer token (AUDIT SF-09) -- see RegisterResp.t in
        # server/models.py. Optional: a Transport built before registration,
        # or against a server that has not deployed the check yet, still
        # works, just unauthenticated.
        self.token = str(token or "").strip()

    def post(self, path: str, payload: dict):
        if not self.base_url:
            return None
        # Usage data leaves the machine here. Plain http would put it on the
        # wire in clear text, so refuse rather than downgrade.
        if not self.base_url.lower().startswith("https://"):
            log.error("Sync server URL is not https; refusing to send usage data.")
            return None

        url = self.base_url + path
        try:
            body = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError) as e:
            log.error("Could not encode a sync request: %s", e)
            return None

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"ProtBot/{__version__}",
                **_auth_header(self.token),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.debug("Sync request to %s failed: %s", path, e)
            return None

        if len(raw) > MAX_RESPONSE_BYTES:
            log.warning("Sync response from %s is larger than expected; ignoring.", path)
            return None

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            log.debug("Sync response from %s is not JSON: %s", path, e)
            return None


def build_transport(config, timeout: int = REQUEST_TIMEOUT) -> "Transport":
    """The one place that turns config into a Transport, token included."""
    return Transport(config.get("server_url", ""), timeout=timeout,
                     token=config.get("device_token", ""))


def authed_request(config, method: str, path: str, body: dict | None = None,
                   timeout: int = REQUEST_TIMEOUT):
    """
    A synchronous, authenticated request that raises on failure.

    For foreground UI code (Devices tab: register, generate a link code, join
    one, list the group) that needs to show the user *why* a request failed —
    the opposite contract from Transport.post, which swallows everything
    because it runs on the background sync thread and must never raise into
    the monitor's poll loop. Both enforce https and attach the device's
    token; this is not routed through Transport because the two error
    contracts do not mix.

    Never puts anything identifying in the URL (AUDIT SF-09) -- path is a
    fixed string, and the caller passes ids like device_id in `body`.
    """
    base = str(config.get("server_url", "") or "").rstrip("/")
    if not base:
        raise ValueError("Server URL not configured — go to Settings.")
    if not base.lower().startswith("https://"):
        raise ValueError("Sync server URL must be https.")

    url = base + "/" + path.lstrip("/")
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"ProtBot/{__version__}",
        **_auth_header(config.get("device_token", "")),
    }

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class SyncClient:
    """
    Keeps this device's totals and the group's totals in step.

    The monitor holds one of these and reads `group_totals` through
    `remote_seconds_for()`. Nothing the monitor calls does I/O.
    """

    def __init__(self, db, config, transport=None) -> None:
        self.db = db
        self.config = config
        self._transport = transport or build_transport(config)

        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()

        # Group totals from the last successful /sync, keyed by server app id.
        self._group_totals: dict = {}
        self._group_fetched_at = 0.0
        # The date those totals describe. Freshness alone is not enough: a
        # sync at 23:50 is still "fresh" at 00:30, but it is yesterday's
        # figure, and applying it to today would hand the user a limit that
        # was already spent before midnight.
        self._group_date = ""
        # What we last uploaded, so our own stale contribution can be removed
        # from the group figure. See syncproto.merge_app_total.
        self._uploaded: dict = {}
        self._uploaded_date = ""
        self._backoff = BACKOFF_START_SEC
        self._last_error = ""

    # ── The switch ───────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """
        Whether sync should run at all.

        Both conditions are the user's own doing: they accepted the privacy
        policy, and they registered this device. Registration is the opt-in.
        """
        try:
            from core import consent
            if not consent.has_consented(self.config):
                return False
        except Exception:
            return False
        return bool(str(self.config.get("device_id", "") or "").strip())

    @property
    def device_id(self) -> str:
        return str(self.config.get("device_id", "") or "").strip()

    # ── What the monitor reads ───────────────────────────────────────────

    def remote_seconds_for(self, local_app_id: int) -> int:
        """
        Seconds this app was used today on *other* devices.

        Returns 0 whenever there is any doubt: sync off, never synced, the app
        has no server id yet, the group figure is too old to enforce against,
        or it describes a different day. 0 means "local usage only", which is
        the app's behaviour without sync and is always safe.

        The date check is not redundant with the freshness one. A sync at 23:50
        is still inside the freshness window at 00:30, but it is yesterday's
        total — applying it would give the user a limit that was already spent
        before midnight.

        Reads memory only. Called from the monitor's poll loop, which must not
        wait on a network.
        """
        if not self.enabled:
            return 0

        server_id = self._server_id_for(local_app_id)
        if not server_id:
            return 0

        today = syncproto.local_date()
        with self._lock:
            if not syncproto.is_fresh(self._group_fetched_at):
                return 0
            if self._group_date != today:
                return 0
            group = int(self._group_totals.get(server_id, 0))
            uploaded = (int(self._uploaded.get(server_id, 0))
                        if self._uploaded_date == today else 0)

        return max(0, min(group - uploaded, syncproto.MAX_PLAUSIBLE_DAILY_SEC))

    def status(self) -> dict:
        """A snapshot for the Devices tab. Never raises, never does I/O."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "device_id": self.device_id,
                "last_sync": self._group_fetched_at,
                "fresh": (syncproto.is_fresh(self._group_fetched_at)
                          and self._group_date == syncproto.local_date()),
                "apps_known": len(self._group_totals),
                "last_error": self._last_error,
            }

    # ── The thread ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin syncing in the background. Safe to call when already running."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="protbot-sync",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop syncing. Waits briefly, then gives up rather than hanging exit."""
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            delay = syncproto.UPLOAD_INTERVAL_SEC
            if self.enabled:
                ok = self.sync_once()
                if ok:
                    self._backoff = BACKOFF_START_SEC
                else:
                    delay = self._backoff
                    self._backoff = min(self._backoff * 2, BACKOFF_MAX_SEC)
            # Waiting on the event rather than sleeping means stop() returns
            # promptly instead of after up to half an hour.
            self._stop.wait(delay)

    # ── One cycle ────────────────────────────────────────────────────────

    def sync_once(self) -> bool:
        """
        Map apps, upload today's totals, fetch the group's. True if the group
        totals were refreshed.

        Wrapped whole: this runs on a background thread, and an exception
        escaping it would kill the thread and stop sync for the rest of the
        session with nothing in the log but a traceback nobody sees.
        """
        try:
            return self._sync_once()
        except Exception as e:
            log.error("Sync cycle failed: %s", e)
            with self._lock:
                self._last_error = str(e)
            return False

    def _sync_once(self) -> bool:
        if not self.enabled:
            return False

        self._ensure_app_ids()

        local_totals = self._local_totals_by_server_id()
        payload = syncproto.build_upload(self.device_id, local_totals)
        today = syncproto.local_date()

        if payload:
            if self._transport.post(ENDPOINT_UPLOAD, payload) is None:
                with self._lock:
                    self._last_error = "upload failed"
                return False
            with self._lock:
                # Only recorded once the server accepted it. Recording an
                # upload that never landed would make merge_app_total subtract
                # a contribution the group total does not contain, and this
                # device's own minutes would go missing from the shared total.
                self._uploaded = dict(local_totals)
                self._uploaded_date = today

        response = self._transport.post(ENDPOINT_SYNC, {"d": self.device_id})
        if response is None:
            with self._lock:
                self._last_error = "sync fetch failed"
            return False

        totals = syncproto.parse_sync(response)
        with self._lock:
            # A new day means our recorded upload is about yesterday. Keeping
            # it would subtract yesterday's seconds from today's group total.
            if self._uploaded_date != today:
                self._uploaded = {}
                self._uploaded_date = today
            self._group_totals = totals
            self._group_fetched_at = time.time()
            self._group_date = today
            self._last_error = ""

        log.debug("Synced: %d app(s), %d device(s).",
                  len(totals), syncproto.parse_device_count(response))
        return True

    # ── App identity ─────────────────────────────────────────────────────

    def _ensure_app_ids(self) -> None:
        """
        Make sure every tracked app has a server id, sending the list if not.

        Sent only when something is missing. The list changes when the user
        adds an app, which is rare, so re-sending it every half hour would be
        pure noise on the wire.
        """
        try:
            apps = self.db.get_all_tracked_apps() or []
        except Exception as e:
            log.error("Could not read tracked apps for sync: %s", e)
            return

        known = self._app_id_map()
        missing = [a for a in apps if str(a.get("id")) not in known]
        if not missing:
            return

        payload = syncproto.build_app_sync(self.device_id, apps)
        if not payload:
            return

        response = self._transport.post(ENDPOINT_APPS, payload)
        if response is None:
            return

        mapping = syncproto.parse_app_map(response)
        if not mapping:
            return

        merged = dict(known)
        merged.update({str(k): int(v) for k, v in mapping.items()})
        self.config.set("server_app_ids", merged)

    def _app_id_map(self) -> dict:
        raw = self.config.get("server_app_ids", {}) or {}
        return raw if isinstance(raw, dict) else {}

    def _server_id_for(self, local_app_id: int) -> int:
        try:
            return int(self._app_id_map().get(str(local_app_id), 0))
        except (TypeError, ValueError):
            return 0

    def _local_totals_by_server_id(self) -> dict:
        """Today's local usage, re-keyed from local ids to server ids."""
        try:
            rows = self.db.get_all_usage_today() or []
        except Exception as e:
            log.error("Could not read today's usage for sync: %s", e)
            return {}

        totals = {}
        for row in rows:
            server_id = self._server_id_for(row.get("app_id", 0))
            if not server_id:
                continue
            try:
                seconds = int(row.get("duration_sec", 0) or 0)
            except (TypeError, ValueError):
                continue
            if seconds > 0:
                totals[server_id] = totals.get(server_id, 0) + seconds
        return totals


def register_device(config, device_name: str = "", email: str = "",
                    transport=None) -> str:
    """
    Register this device and store the id it is given. Returns the id, or "".

    This is the moment sync turns on, so it is deliberately an explicit call
    made from the Devices tab rather than something that happens on startup.
    The email is optional and is the user's to type or leave blank; the server
    discards it after the response (server/models.py).

    Also stores the bearer token the server issues alongside the id (AUDIT
    SF-09) — every request after this one authenticates with it instead of
    the device id travelling alone. A server that has not deployed token
    issuance yet and omits `t` still registers the device; the token is
    simply empty until the server does, at which point every client already
    sends whatever it has.
    """
    transport = transport or build_transport(config)
    payload = {"n": str(device_name or "")}
    if email:
        payload["e"] = str(email)

    response = transport.post(ENDPOINT_REGISTER, payload)
    if not isinstance(response, dict):
        log.warning("Device registration did not return a response.")
        return ""

    device_id = str(response.get("id", "") or "").strip()
    if not device_id:
        log.warning("Device registration returned no id.")
        return ""

    config.set("device_id", device_id)
    config.set("device_token", str(response.get("t", "") or "").strip())
    log.info("Device registered for sync.")
    return device_id


def unregister_device(config) -> None:
    """
    Turn sync off and forget everything it needs to work.

    Clearing the device id alone would leave the app quiet but still holding
    the identifier that ties this machine to data on the server, and the stale
    app-id mapping would be wrong the moment the user registered again. The
    token goes with it — it authenticates that same id and is worthless
    (and a leftover secret) without it.
    """
    config.set("device_id", "")
    config.set("device_token", "")
    config.set("server_app_ids", {})
    config.set("linked_devices", [])
    log.info("Device unregistered; sync is off.")
