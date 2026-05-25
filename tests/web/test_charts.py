"""Tests for spotify_web.charts figure builders."""
from spotify_web.charts import daily_activity_figure, trend_figure


def test_daily_activity_figure_empty():
    fig = daily_activity_figure([])
    # One stacked-bar trace per time segment.
    assert len(fig.data) == 4


def test_daily_activity_figure_values():
    rows = [
        {"weekday": "Monday", "weekday_idx": 0, "segment": "7-12", "total_mins": 10},
    ]
    fig = daily_activity_figure(rows)
    seg_trace = next(t for t in fig.data if t.name == "7-12")
    assert seg_trace.y[0] == 10
    assert tuple(seg_trace.x) == (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    )


def test_trend_figure_values():
    rows = [{"date": "2024-01-01", "total_mins": 10, "play_count": 3}]
    fig = trend_figure(rows, "date", "daily")
    assert len(fig.data) == 1
    assert tuple(fig.data[0].x) == ("2024-01-01",)
    assert tuple(fig.data[0].y) == (10,)


def test_trend_figure_empty():
    fig = trend_figure([], "week_label", "weekly")
    assert len(fig.data) == 1
    assert tuple(fig.data[0].x) == ()
