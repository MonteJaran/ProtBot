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
