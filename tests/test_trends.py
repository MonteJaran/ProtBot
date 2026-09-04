"""
core/trends.py — the pure statistics half of ROADMAP.md's "pattern
recognition" item. No database here; core/test_database.py covers the two
new query methods that feed this.
"""

from core import trends


class TestWeekOverWeekDelta:

    def test_an_increase(self):
        result = trends.week_over_week_delta(this_week_sec=1200, last_week_sec=600)
        assert result == {
            "this_week_sec": 1200,
            "last_week_sec": 600,
            "delta_sec": 600,
            "delta_pct": 100.0,
        }

    def test_a_decrease(self):
        result = trends.week_over_week_delta(this_week_sec=300, last_week_sec=600)
        assert result["delta_sec"] == -300
        assert result["delta_pct"] == -50.0

    def test_no_change(self):
        result = trends.week_over_week_delta(this_week_sec=500, last_week_sec=500)
        assert result["delta_sec"] == 0
        assert result["delta_pct"] == 0.0

    def test_last_week_zero_gives_no_percentage_not_a_divide_by_zero(self):
        # "Infinite percent increase" is not a number anyone should see
        # printed — None is the caller's cue to say "new this week" instead.
        result = trends.week_over_week_delta(this_week_sec=600, last_week_sec=0)
        assert result["delta_sec"] == 600
        assert result["delta_pct"] is None

    def test_both_zero(self):
        result = trends.week_over_week_delta(this_week_sec=0, last_week_sec=0)
        assert result["delta_sec"] == 0
        assert result["delta_pct"] is None

    def test_negative_inputs_are_clamped_not_trusted(self):
        # Defensive the same way syncproto's merge rules are: a corrupt row
        # must not produce a nonsensical trend.
        result = trends.week_over_week_delta(this_week_sec=-100, last_week_sec=-50)
        assert result["this_week_sec"] == 0
        assert result["last_week_sec"] == 0
        assert result["delta_sec"] == 0
        assert result["delta_pct"] is None

    def test_non_numeric_input_does_not_raise(self):
        result = trends.week_over_week_delta(this_week_sec=None, last_week_sec=None)
        assert result["this_week_sec"] == 0
        assert result["last_week_sec"] == 0


class TestBiggestMovers:

    def test_the_largest_change_sorts_first_regardless_of_direction(self):
        this_week = {1: 100, 2: 500, 3: 300}
        last_week = {1: 100, 2: 200, 3: 900}
        movers = trends.biggest_movers(this_week, last_week, limit=3)
        # app 3 dropped by 600 (largest |delta|), app 2 rose by 300.
        assert [m["app_id"] for m in movers] == [3, 2]
        assert movers[0]["delta_sec"] == -600
        assert movers[1]["delta_sec"] == 300

    def test_unchanged_apps_are_not_movers(self):
        movers = trends.biggest_movers({1: 100}, {1: 100})
        assert movers == []

    def test_an_app_only_used_this_week_counts_as_new(self):
        movers = trends.biggest_movers({1: 600}, {})
        assert len(movers) == 1
        assert movers[0] == {
            "app_id": 1, "this_week_sec": 600, "last_week_sec": 0, "delta_sec": 600,
        }

    def test_an_app_only_used_last_week_counts_as_stopped(self):
        movers = trends.biggest_movers({}, {1: 600})
        assert len(movers) == 1
        assert movers[0]["delta_sec"] == -600

    def test_the_limit_is_respected(self):
        this_week = {i: i * 100 for i in range(1, 11)}
        movers = trends.biggest_movers(this_week, {}, limit=3)
        assert len(movers) == 3
        # Largest deltas first: apps 10, 9, 8.
        assert [m["app_id"] for m in movers] == [10, 9, 8]

    def test_a_limit_of_zero_returns_nothing(self):
        assert trends.biggest_movers({1: 100}, {}, limit=0) == []

    def test_empty_inputs_return_nothing(self):
        assert trends.biggest_movers({}, {}) == []
        assert trends.biggest_movers(None, None) == []

    def test_negative_or_junk_values_are_clamped_not_trusted(self):
        movers = trends.biggest_movers({1: -50}, {1: None})
        assert movers == []   # both clamp to 0, so no change


def _session(app_id, start, end, duration_sec):
    return {"app_id": app_id, "start_time": start, "end_time": end,
            "duration_sec": duration_sec}


class TestPrecedingAppTriggers:

    def test_the_app_that_just_closed_is_the_trigger(self):
        # Browser runs 09:00-09:05, Discord (a distraction) starts right
        # after at 09:06 and runs 15 minutes — long enough to count.
        sessions = [
            _session("browser", "2026-09-01T09:00:00", "2026-09-01T09:05:00", 300),
            _session("discord", "2026-09-01T09:06:00", "2026-09-01T09:21:00", 900),
        ]
        result = trends.preceding_app_triggers(sessions, {"discord"})
        assert result == [{"app_id": "browser", "count": 1}]

    def test_a_short_session_on_the_distracting_app_does_not_count(self):
        sessions = [
            _session("browser", "2026-09-01T09:00:00", "2026-09-01T09:05:00", 300),
            _session("discord", "2026-09-01T09:06:00", "2026-09-01T09:06:30", 30),
        ]
        assert trends.preceding_app_triggers(sessions, {"discord"}) == []

    def test_a_gap_too_large_is_not_a_trigger(self):
        sessions = [
            _session("browser", "2026-09-01T09:00:00", "2026-09-01T09:05:00", 300),
            _session("discord", "2026-09-01T10:00:00", "2026-09-01T10:15:00", 900),
        ]
        assert trends.preceding_app_triggers(sessions, {"discord"}, max_gap_sec=300) == []

    def test_the_distracting_app_itself_is_never_its_own_trigger(self):
        sessions = [
            _session("discord", "2026-09-01T09:00:00", "2026-09-01T09:05:00", 300),
            _session("discord", "2026-09-01T09:06:00", "2026-09-01T09:21:00", 900),
        ]
        assert trends.preceding_app_triggers(sessions, {"discord"}) == []

    def test_counts_accumulate_across_multiple_occurrences(self):
        sessions = []
        for day in ("01", "02", "03"):
            sessions.append(_session("browser", f"2026-09-{day}T09:00:00",
                                      f"2026-09-{day}T09:05:00", 300))
            sessions.append(_session("discord", f"2026-09-{day}T09:06:00",
                                      f"2026-09-{day}T09:21:00", 900))
        result = trends.preceding_app_triggers(sessions, {"discord"})
        assert result == [{"app_id": "browser", "count": 3}]

    def test_most_frequent_trigger_sorts_first(self):
        sessions = [
            _session("mail", "2026-09-01T08:00:00", "2026-09-01T08:05:00", 300),
            _session("discord", "2026-09-01T08:06:00", "2026-09-01T08:21:00", 900),
            _session("browser", "2026-09-02T09:00:00", "2026-09-02T09:05:00", 300),
            _session("discord", "2026-09-02T09:06:00", "2026-09-02T09:21:00", 900),
            _session("browser", "2026-09-03T09:00:00", "2026-09-03T09:05:00", 300),
            _session("discord", "2026-09-03T09:06:00", "2026-09-03T09:21:00", 900),
        ]
        result = trends.preceding_app_triggers(sessions, {"discord"})
        assert result[0] == {"app_id": "browser", "count": 2}
        assert {"app_id": "mail", "count": 1} in result

    def test_unordered_input_is_sorted_internally(self):
        sessions = [
            _session("discord", "2026-09-01T09:06:00", "2026-09-01T09:21:00", 900),
            _session("browser", "2026-09-01T09:00:00", "2026-09-01T09:05:00", 300),
        ]
        assert trends.preceding_app_triggers(sessions, {"discord"}) == [
            {"app_id": "browser", "count": 1},
        ]

    def test_the_closest_preceding_session_wins_over_an_earlier_one(self):
        sessions = [
            _session("mail", "2026-09-01T08:50:00", "2026-09-01T08:55:00", 300),
            _session("browser", "2026-09-01T09:00:00", "2026-09-01T09:05:00", 300),
            _session("discord", "2026-09-01T09:06:00", "2026-09-01T09:21:00", 900),
        ]
        result = trends.preceding_app_triggers(sessions, {"discord"}, max_gap_sec=3600)
        assert result == [{"app_id": "browser", "count": 1}]

    def test_limit_is_respected(self):
        sessions = []
        for i, app in enumerate(("a", "b", "c", "d")):
            sessions.append(_session(app, f"2026-09-0{i+1}T09:00:00",
                                      f"2026-09-0{i+1}T09:05:00", 300))
            sessions.append(_session("discord", f"2026-09-0{i+1}T09:06:00",
                                      f"2026-09-0{i+1}T09:21:00", 900))
        result = trends.preceding_app_triggers(sessions, {"discord"}, limit=2)
        assert len(result) == 2

    def test_empty_inputs_return_nothing(self):
        assert trends.preceding_app_triggers([], {"discord"}) == []
        assert trends.preceding_app_triggers([_session("d", "x", "y", 900)], set()) == []
        assert trends.preceding_app_triggers(None, {"discord"}) == []

    def test_a_session_with_nothing_recently_before_it_contributes_nothing(self):
        sessions = [_session("discord", "2026-09-01T09:06:00", "2026-09-01T09:21:00", 900)]
        assert trends.preceding_app_triggers(sessions, {"discord"}) == []


class TestWeekdayBreakdown:

    def test_the_highest_average_day_sorts_first(self):
        daily = [
            {"date": "2026-08-31", "total_sec": 1000},  # Monday
            {"date": "2026-09-01", "total_sec": 5000},  # Tuesday
            {"date": "2026-09-02", "total_sec": 1000},  # Wednesday
        ]
        result = trends.weekday_breakdown(daily)
        assert result[0]["name"] == "Tuesday"
        assert result[0]["avg_sec"] == 5000

    def test_zero_usage_days_pull_the_average_down(self):
        # Same weekday twice: one day with usage, one with none.
        daily = [
            {"date": "2026-08-31", "total_sec": 2000},  # Monday
            {"date": "2026-09-07", "total_sec": 0},      # Monday, one week later
        ]
        result = trends.weekday_breakdown(daily)
        assert result[0]["name"] == "Monday"
        assert result[0]["avg_sec"] == 1000

    def test_drift_pct_is_relative_to_the_overall_average(self):
        daily = [
            {"date": "2026-08-31", "total_sec": 3000},  # Monday
            {"date": "2026-09-01", "total_sec": 1000},  # Tuesday
        ]
        result = trends.weekday_breakdown(daily)
        monday = next(r for r in result if r["name"] == "Monday")
        assert monday["drift_pct"] == 50.0   # 3000 vs overall avg 2000 -> +50%

    def test_drift_pct_is_none_when_overall_average_is_zero(self):
        # A day is still reported — average 0 is a real (if uninteresting)
        # answer — but "how far from an average of 0" isn't a percentage.
        daily = [{"date": "2026-08-31", "total_sec": 0}]
        result = trends.weekday_breakdown(daily)
        assert result == [
            {"weekday": 0, "name": "Monday", "avg_sec": 0, "drift_pct": None},
        ]

    def test_only_weekdays_present_in_the_data_are_returned(self):
        daily = [{"date": "2026-08-31", "total_sec": 100}]  # Monday only
        result = trends.weekday_breakdown(daily)
        assert len(result) == 1
        assert result[0]["name"] == "Monday"

    def test_empty_input_returns_nothing(self):
        assert trends.weekday_breakdown([]) == []
        assert trends.weekday_breakdown(None) == []

    def test_a_malformed_date_is_skipped_not_fatal(self):
        daily = [
            {"date": "not-a-date", "total_sec": 999},
            {"date": "2026-08-31", "total_sec": 100},
        ]
        result = trends.weekday_breakdown(daily)
        assert len(result) == 1
        assert result[0]["name"] == "Monday"
