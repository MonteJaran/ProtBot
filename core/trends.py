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
