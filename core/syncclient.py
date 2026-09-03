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

  * **Every request carries a credential the device id is not.** Registration
    issues a secret token; every later request sends it in an `Authorization`
    header, and this module refuses to send one without it. See below.

## The device token (AUDIT SF-09)

The device id used to be the whole credential. That is an identifier, not a
secret: it travels in payloads, it is shown in the Devices tab, and in the
shape this protocol started out with it sat in a URL path, where it lands in
server, proxy and intermediary logs. Anyone who read one out of a log could
read that user's usage — textbook IDOR.

So registration now returns two things: the id, which names the device, and a
token, which proves you are it. Four rules follow, and each is enforced here
rather than left to the server:

  * **The token goes in a header, never in a URL or a payload.** Request
    bodies are logged by some proxies; query strings are logged by nearly all
    of them. `Authorization` is the one place with an established convention
    of being redacted.

  * **No token means no request.** `/register` is the sole exception, because
    it is where the token comes from. Everything else is refused locally
    rather than sent unauthenticated and left for the server to reject —
    an unauthenticated request is the vulnerability, not the error message.

  * **A refusal is not a network failure.** 401 and 403 mean the credential is
    wrong; retrying every half hour will never make it right. Sync stops and
    says so, until the user registers the device again. Every other failure
    keeps its backoff.

  * **Registration is all-or-nothing.** A server that returns an id but no
    token leaves nothing stored. Half a registration is a device id being
    used as a credential again, which is the thing being fixed.

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

# The only endpoint that runs before there is a credential, because it is
# where the credential comes from. Transport.post refuses every other path
# without a token rather than sending it unauthenticated.
UNAUTHENTICATED_ENDPOINTS = frozenset({ENDPOINT_REGISTER})

# A wrong credential, as opposed to a bad network. The difference matters:
# one is worth retrying and the other never will be.
AUTH_FAILURE_STATUSES = frozenset({401, 403})


class Transport:
    """
    One authenticated HTTP POST, returning parsed JSON or None.

    A class rather than a function so tests can pass a fake in and exercise
    every response shape — timeout, 500, HTML error page, valid JSON with the
    wrong types — without a network or a server.

    `token` is the device token, either a string or a zero-argument callable
    returning one. A callable is what callers should pass: a transport is
    built once, at startup, and the token does not exist until the user
    registers. Copying the value in would freeze an empty credential for the
    life of the process, and sync would stay broken until the app restarted.
    """

    def __init__(self, base_url: str, timeout: int = REQUEST_TIMEOUT,
                 token=None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self._token = token
        # The HTTP status of the last response, or 0 if the request never got
        # one. SyncClient reads it to tell a refused credential from a bad
        # network; post() returns None for both, and they need opposite
        # responses.
        self.last_status = 0

    def token(self) -> str:
        """
        The current device token, or "".

        Never raises: this is called on the sync thread inside post(), and a
        config read that threw here would take the whole cycle down.
        """
        source = self._token
        if callable(source):
            try:
                source = source()
            except Exception as e:
                log.error("Could not read the device token: %s", e)
                return ""
        return str(source or "").strip()

    def post(self, path: str, payload: dict):
        # Reset first: a caller reading last_status after a request that never
        # reached the network would otherwise see the previous one's code and
        # act on a refusal that has already been handled.
        self.last_status = 0

        if not self.base_url:
            return None
        # Usage data leaves the machine here. Plain http would put it on the
        # wire in clear text, so refuse rather than downgrade.
        if not self.base_url.lower().startswith("https://"):
            log.error("Sync server URL is not https; refusing to send usage data.")
            return None

        # No credential, no request. Sending it anyway and letting the server
        # decide is the vulnerability itself (AUDIT SF-09), not a friendlier
        # error path. /register is the exception because it issues the token.
        token = self.token()
        if not token and path not in UNAUTHENTICATED_ENDPOINTS:
            log.error("No device token; refusing to send an unauthenticated "
                      "request to %s. Register this device again.", path)
            return None

        url = self.base_url + path
        try:
            body = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError) as e:
            log.error("Could not encode a sync request: %s", e)
            return None

        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"ProtBot/{__version__}",
        }
        if token:
            # A header, not a path segment or a body field: it is the one
            # place in an HTTP request that logging tools redact by
            # convention. Never logged from here either.
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(
            url, data=body, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.last_status = int(getattr(response, "status", 200) or 200)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as e:
            # Caught before URLError, which it subclasses: the status code is
            # the whole point, and the generic handler would discard it.
            self.last_status = int(getattr(e, "code", 0) or 0)
            log.debug("Sync request to %s was refused: %s", path, e)
            return None
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


class SyncClient:
    """
    Keeps this device's totals and the group's totals in step.

    The monitor holds one of these and reads `group_totals` through
    `remote_seconds_for()`. Nothing the monitor calls does I/O.
    """

    def __init__(self, db, config, transport=None) -> None:
        self.db = db
        self.config = config
        self._transport = transport or transport_for(config)

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
        # Set when the server refused this device's credentials. Retrying a
        # rejected token on a timer never succeeds and keeps a pointless
        # request going out every half hour, so sync stops until the token
        # changes — which only happens when the user registers again.
        self._auth_failed = False
        self._auth_token_seen = ""

    # ── The switch ───────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """
        Whether sync should run at all.

        All three conditions are the user's own doing: they accepted the
        privacy policy, and they registered this device, which is what issues
        both halves of the credential. Registration is the opt-in.

        The token is required, not merely preferred. A device id on its own is
        an identifier — it is shown in the Devices tab and carried in every
        payload — and treating it as a credential is exactly what AUDIT SF-09
        was about. An install that has an id and no token is one where
        registration half-completed, and the fix is to register again rather
        than to send the id by itself.
        """
        try:
            from core import consent
            if not consent.has_consented(self.config):
                return False
        except Exception:
            return False
        return bool(self.device_id) and bool(self.device_token)

    @property
    def device_id(self) -> str:
        return str(self.config.get("device_id", "") or "").strip()

    @property
    def device_token(self) -> str:
        """
        The secret half of the credential. Never logged, never in a payload.

        Read from config on every use rather than cached, so registering
        (or unregistering) takes effect on the next cycle instead of at the
        next restart.
        """
        return str(self.config.get("device_token", "") or "").strip()

    @property
    def credentials_refused(self) -> bool:
        """Whether the server rejected this device's token."""
        with self._lock:
            return self._auth_failed

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
                # The one sync failure the user has to do something about.
                # Every other one clears itself when the network comes back.
                "credentials_refused": self._auth_failed,
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
        if self._refused():
            return False

        self._ensure_app_ids()

        local_totals = self._local_totals_by_server_id()
        payload = syncproto.build_upload(self.device_id, local_totals)
        today = syncproto.local_date()

        if payload:
            if self._post(ENDPOINT_UPLOAD, payload) is None:
                self._fail("upload failed")
                return False
            with self._lock:
                # Only recorded once the server accepted it. Recording an
                # upload that never landed would make merge_app_total subtract
                # a contribution the group total does not contain, and this
                # device's own minutes would go missing from the shared total.
                self._uploaded = dict(local_totals)
                self._uploaded_date = today

        response = self._post(ENDPOINT_SYNC, {"d": self.device_id})
        if response is None:
            self._fail("sync fetch failed")
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

    # ── Credentials ──────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict):
        """
        One request, noticing a refused credential on the way past.

        Every request in a cycle goes through here rather than straight to the
        transport, because any of them can be the one the server refuses and
        the response to that is different from the response to a timeout.
        """
        response = self._transport.post(path, payload)
        if response is None and self._is_auth_failure():
            self._reject()
        return response

    def _fail(self, message: str) -> None:
        """
        Record why a cycle stopped, without overwriting a refusal.

        A rejected credential surfaces as "upload failed" if the generic
        message is allowed to land on top of it — and those two say opposite
        things to the user. One is wait for the network, the other is register
        this device again.
        """
        with self._lock:
            if not self._auth_failed:
                self._last_error = message

    def _is_auth_failure(self) -> bool:
        """
        Whether the last request was refused rather than merely failed.

        Read through getattr because a test's fake transport is not obliged to
        have the attribute, and a missing one must read as "not a refusal" —
        the safe answer, which keeps the ordinary backoff.
        """
        try:
            return int(getattr(self._transport, "last_status", 0)) in AUTH_FAILURE_STATUSES
        except (TypeError, ValueError):
            return False

    def _reject(self) -> None:
        """Stop syncing until the token changes, and say why."""
        with self._lock:
            already = self._auth_failed
            self._auth_failed = True
            self._auth_token_seen = self.device_token
            self._last_error = "the server refused this device's credentials"
        if not already:
            # Once, not every half hour: this is the log a user is asked to
            # send, and a repeated line would bury everything around it.
            log.error("The sync server refused this device's credentials. "
                      "Sync is stopped until the device is registered again.")

    def _refused(self) -> bool:
        """
        Whether to skip this cycle because the credential was rejected.

        A token different from the refused one means the user registered
        again, so the new credential gets a chance rather than inheriting the
        old one's verdict.
        """
        with self._lock:
            token = self.device_token
            if token != self._auth_token_seen:
                self._auth_failed = False
                self._auth_token_seen = token
            return self._auth_failed

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

        response = self._post(ENDPOINT_APPS, payload)
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


def transport_for(config, timeout: int = REQUEST_TIMEOUT) -> Transport:
    """
    A Transport carrying this device's token, for everything except
    registration.

    Anything that talks to the sync server on behalf of a registered device
    should build its transport here — core/linking.py included — so there is
    one place the credential is attached rather than one per call site, and
    no way to add an endpoint that quietly goes out unauthenticated.

    The token is passed as a callable, not a value. A transport built at
    startup would otherwise hold the empty string forever, and sync would keep
    refusing its own requests until the app was restarted.
    """
    return Transport(
        config.get("server_url", ""),
        timeout=timeout,
        token=lambda: str(config.get("device_token", "") or "").strip(),
    )


def register_device(config, device_name: str = "", email: str = "",
                    transport=None) -> str:
    """
    Register this device and store the credentials it is given. Returns the
    device id, or "".

    This is the moment sync turns on, so it is deliberately an explicit call
    made from the Devices tab rather than something that happens on startup.
    The email is optional and is the user's to type or leave blank; the server
    discards it after the response (server/models.py).

    Registration returns two things and both are required: an id, which names
    the device, and a token, which proves it. A response carrying only an id
    is refused and nothing is stored — half a registration would leave the app
    treating the id as a credential, which is the weakness this replaced
    (AUDIT SF-09).

    The transport used here deliberately carries no token: this is the call
    that issues one, and a stale credential from a previous registration has
    no business being sent to it.
    """
    transport = transport or Transport(config.get("server_url", ""))
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

    token = str(response.get("t", "") or "").strip()
    if not token:
        log.error("Device registration returned no access token; sync needs "
                  "one and will not be enabled without it.")
        return ""

    # Stored together, token first: a crash between the two writes must not
    # leave an id that looks registered with no credential behind it.
    config.set("device_token", token)
    config.set("device_id", device_id)
    log.info("Device registered for sync.")
    return device_id


def unregister_device(config) -> None:
    """
    Turn sync off and forget everything it needs to work.

    Clearing the device id alone would leave the app quiet but still holding
    the identifier that ties this machine to data on the server, and the stale
    app-id mapping would be wrong the moment the user registered again. The
    token goes with it: keeping a live credential for a device the user has
    just disconnected is the opposite of what they asked for.
    """
    config.set("device_id", "")
    config.set("device_token", "")
    config.set("server_app_ids", {})
    config.set("linked_devices", [])
    log.info("Device unregistered; sync is off.")
