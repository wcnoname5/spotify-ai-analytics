"""Plotly figure builders for the dashboard. Pure: data in, Figure out."""
import plotly.graph_objects as go

_SEGMENT_ORDER = ["0-6", "7-12", "13-18", "19-23"]
_SEGMENT_COLORS = {
    "0-6":   "rgba(31, 96, 180, 0.9)",
    "7-12":  "rgba(231, 185, 0, 0.9)",
    "13-18": "rgba(255, 126, 14, 0.9)",
    "19-23": "rgba(214, 39, 39, 0.85)",
}
_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_TREND_TITLES = {
    "daily": "Daily Listening",
    "weekly": "Weekly Listening",
    "monthly": "Monthly Listening",
}


def daily_activity_figure(rows: list[dict]) -> go.Figure:
    """Build the Plot 1 stacked bar: x = Monday..Sunday, y = minutes, stacked by segment.

    Args:
        rows: Output of queries.get_daily_activity_pattern - dicts with
            "weekday", "weekday_idx", "segment", "total_mins".
    """
    fig = go.Figure()
    for segment in _SEGMENT_ORDER:
        minutes_by_day = {
            r["weekday"]: r["total_mins"] or 0
            for r in rows
            if r["segment"] == segment
        }
        fig.add_bar(
            name=segment,
            x=_WEEKDAY_ORDER,
            y=[minutes_by_day.get(day, 0) for day in _WEEKDAY_ORDER],
            marker_color=_SEGMENT_COLORS[segment],
        )
    fig.update_layout(
        barmode="stack",
        xaxis_title="",
        yaxis_title="Minutes",
        legend_title="Time segment",
        height=420,
    )
    return fig


def trend_figure(rows: list[dict], label_key: str, granularity: str) -> go.Figure:
    """Build the Plot 2 bar chart of listening minutes per time bucket.

    Args:
        rows: Output of queries.get_daily/weekly/monthly_trend.
        label_key: Dict key holding the bucket label ("date" / "week_label" /
            "month_label").
        granularity: "daily" | "weekly" | "monthly" - used for the chart title.
    """
    fig = go.Figure(
        go.Bar(
            x=[r[label_key] for r in rows],
            y=[r["total_mins"] or 0 for r in rows],
            marker_color="rgba(30, 160, 90, 0.85)",
        )
    )
    fig.update_layout(
        title=_TREND_TITLES.get(granularity, "Listening Trend"),
        xaxis_title="",
        yaxis_title="Minutes",
        height=420,
    )
    return fig
