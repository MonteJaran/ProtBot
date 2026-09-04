"""
trends.py - Plain statistics over the user's own usage history.

ROADMAP.md's "pattern recognition" item, started at the honest end. This app
once advertised "AI pattern recognition" with nothing behind it (AUDIT
BL-02); the fix removed the claim rather than build a model to match it. What
actually earns the word "insights" is arithmetic over
`usage_sessions` — week-over-week deltas, which apps moved the most — and
that needs no model, so it says so rather than dressing plain statistics up
as something they are not.

Separated from core/database.py the same way core/activity.py is separated
from the monitor: this is where the rules are, so this is what gets tested
without a database. ui/insights_page.py calls core/database.py for the two
weeks' numbers and hands them here.
"""

from datetime import date, datetime


def week_over_week_delta(this_week_sec: int, last_week_sec: int) -> dict:
    """
    How this week's total compares to last week's.

    Returns {"this_week_sec", "last_week_sec", "delta_sec", "delta_pct"}.
    `delta_pct` is `None` rather than a divide-by-zero when last week was
    zero — "infinite percent increase" is not a number anyone should see
    printed, and `None` is the caller's cue to say "new this week" instead.
    Negative inputs are clamped to zero rather than trusted, the same
    defensive posture as syncproto's merge rules: a corrupt row must not be
    able to turn into a nonsensical trend.
    """
    this_week_sec = max(0, int(this_week_sec or 0))
    last_week_sec = max(0, int(last_week_sec or 0))
    delta_sec = this_week_sec - last_week_sec
    delta_pct = (delta_sec / last_week_sec * 100) if last_week_sec > 0 else None
    return {
        "this_week_sec": this_week_sec,
        "last_week_sec": last_week_sec,
        "delta_sec": delta_sec,
        "delta_pct": delta_pct,
    }


def biggest_movers(this_week: dict, last_week: dict, limit: int = 3) -> list:
    """
    Which apps changed the most between two weeks, up or down.

    `this_week` / `last_week` map app_id to seconds used, as returned by
    core/database.py's get_all_apps_usage_for_week (reshaped by the caller
    into {app_id: total_sec} — this function does not touch a database).

    An app present in one week's map but not the other counts as zero in
    the week it is missing from, rather than being skipped: an app that
    stopped being used entirely, or one that is brand new this week, is
    itself the finding — not a case to hide by requiring the app in both
    weeks.

    Returns up to `limit` entries, sorted by the size of the change
    (largest first, regardless of direction):
    [{"app_id", "this_week_sec", "last_week_sec", "delta_sec"}, ...].
    An app with no change in either week contributes nothing to sort by and
    is left out — "the app you use the same amount every week" is not a
    mover.
    """
    this_week = this_week or {}
    last_week = last_week or {}

    movers = []
    for app_id in set(this_week) | set(last_week):
        this_sec = max(0, int(this_week.get(app_id, 0) or 0))
        last_sec = max(0, int(last_week.get(app_id, 0) or 0))
        delta_sec = this_sec - last_sec
        if delta_sec == 0:
            continue
        movers.append({
            "app_id": app_id,
            "this_week_sec": this_sec,
            "last_week_sec": last_sec,
            "delta_sec": delta_sec,
        })

    movers.sort(key=lambda m: abs(m["delta_sec"]), reverse=True)
    return movers[:max(0, limit)]


# ── The other two pieces of "pattern recognition" ──────────────────────────
#
# ui/insights_page.py used to tease both of these under "Advanced Insights —
# Planned": "Distraction triggers" ("Which app you tend to open right after
# closing another") and "Day-of-week breakdown" ("Which days run longest, and
# by how much"). Same honest-statistics posture as the two functions above —
# no model, just arithmetic over usage_sessions.

_LOOKBACK_SESSIONS = 50  # see preceding_app_triggers — a deliberate bound,
# not a database limit: the triggering app is always among the last handful
# of sessions in practice, and this keeps the search O(n) in session count
# instead of O(n^2) without needing to reason about overlapping sessions.

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]


def preceding_app_triggers(sessions, distraction_app_ids, min_distraction_sec: int = 600,
                            max_gap_sec: int = 300, limit: int = 3) -> list:
    """
    Which app tends to be running right before a distraction session starts.

    `sessions` is core/database.py's get_sessions_since() shape: every
    recorded session in some trailing window, each a dict with "app_id",
    "start_time", "end_time" (ISO strings; a session still missing an
    end_time is the caller's job to exclude — this function trusts the list
    it is given) and "duration_sec". Sorted by start_time here regardless of
    the order given, so the caller does not have to get that right too.

    `distraction_app_ids` is which app ids count as a distraction — a UI
    decision (ui/insights_page.py's `_DISTRACTING` category set), not
    something this function knows on its own.

    A session counts as a distraction session when its app_id is in
    `distraction_app_ids` and it ran at least `min_distraction_sec` (default
    10 minutes — a five-second alt-tab is not a distraction session). Its
    trigger is the most recently-ended *other* app among the
    `_LOOKBACK_SESSIONS` sessions before it that finished no more than
    `max_gap_sec` (default 5 minutes) before this one started — the thing
    that was open right beforehand. A distraction session with nothing that
    recently before it (the first thing opened that day, or a gap too large
    to call causal) contributes nothing.

    Returns up to `limit` {"app_id", "count"} entries, most-frequent trigger
    first; ties keep the order their app was first identified as a trigger.
    """
    if not sessions or not distraction_app_ids:
        return []

    ordered = sorted(sessions, key=lambda s: s["start_time"])
    counts: dict = {}
    first_seen: list = []

    for i, sess in enumerate(ordered):
        if sess["app_id"] not in distraction_app_ids:
            continue
        if int(sess.get("duration_sec", 0) or 0) < min_distraction_sec:
            continue

        start = sess["start_time"]
        window = ordered[max(0, i - _LOOKBACK_SESSIONS):i]
        best_app_id = None
        best_gap = None
        for other in window:
            if other["app_id"] == sess["app_id"]:
                continue
            end = other.get("end_time")
            if not end:
                continue
            gap = _seconds_between(end, start)
            if gap is None or not (0 <= gap <= max_gap_sec):
                continue
            if best_gap is None or gap < best_gap:   # closest-ending session wins
                best_gap = gap
                best_app_id = other["app_id"]

        if best_app_id is not None:
            if best_app_id not in counts:
                first_seen.append(best_app_id)
            counts[best_app_id] = counts.get(best_app_id, 0) + 1

    ranked = sorted(first_seen, key=lambda app_id: counts[app_id], reverse=True)
    return [{"app_id": app_id, "count": counts[app_id]} for app_id in ranked[:max(0, limit)]]


def _seconds_between(earlier_iso: str, later_iso: str):
    """later - earlier, in seconds, or None if either string won't parse —
    one bad timestamp should drop that one comparison, not the whole report."""
    try:
        return (datetime.fromisoformat(later_iso) - datetime.fromisoformat(earlier_iso)).total_seconds()
    except (TypeError, ValueError):
        return None


def weekday_breakdown(daily_totals: list) -> list:
    """
    Average usage per day of the week, and how far each day's average sits
    from the overall daily average — "which days run longest, and by how
    much".

    `daily_totals` is core/database.py's get_daily_totals() shape: one entry
    per *calendar* day in some trailing window — {"date": "YYYY-MM-DD",
    "total_sec": int} — including zero-usage days. That matters here:
    dropping zero days would average each weekday over a different, smaller
    sample depending on how many of them happened to have any usage at all,
    quietly favouring whichever weekday has the fewest idle days rather than
    the one that actually runs longest.

    Returns one entry per weekday that appears in the data, sorted by
    average descending (the worst day first): {"weekday": 0-6 (Monday=0),
    "name", "avg_sec", "drift_pct"}. `drift_pct` is how far that weekday's
    average sits above (positive) or below (negative) the overall average
    across every day given; `None` when the overall average is zero.
    """
    if not daily_totals:
        return []

    buckets: dict = {i: [] for i in range(7)}
    all_totals = []
    for entry in daily_totals:
        try:
            weekday = date.fromisoformat(entry["date"]).weekday()
        except (KeyError, TypeError, ValueError):
            continue
        secs = max(0, int(entry.get("total_sec", 0) or 0))
        buckets[weekday].append(secs)
        all_totals.append(secs)

    if not all_totals:
        return []

    overall_avg = sum(all_totals) / len(all_totals)

    result = []
    for weekday in range(7):
        values = buckets[weekday]
        if not values:
            continue
        avg = sum(values) / len(values)
        drift_pct = ((avg - overall_avg) / overall_avg * 100) if overall_avg > 0 else None
        result.append({
            "weekday": weekday,
            "name": _WEEKDAY_NAMES[weekday],
            "avg_sec": int(round(avg)),
            "drift_pct": drift_pct,
        })

    result.sort(key=lambda r: r["avg_sec"], reverse=True)
    return result
