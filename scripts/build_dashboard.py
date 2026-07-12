"""Generate the static dashboard site (Cloudflare Pages) from history.db.

Reuses the pure query + chart builders behind the local Streamlit dashboard;
output is a handful of HTML pages in site/ (plotly.js loaded from CDN).
Pages: fixed rolling windows (7/30/90 days) plus an all-time page whose trend
chart has a rangeslider for arbitrary-range zooming.
"""
import datetime
import html
from pathlib import Path

from spotify_core.config import settings
from spotify_core.db.queries import (
    get_daily_activity_pattern,
    get_daily_trend,
    get_data_range,
    get_listening_summary,
    get_monthly_trend,
    get_recent_plays,
    get_top_artists,
    get_top_tracks,
    get_weekly_trend,
    is_history_empty,
)
from spotify_mcp.dashboard.charts import daily_activity_figure, trend_figure
from spotify_mcp.dashboard.formatting import format_duration_mins, spotify_uri_to_url

# (filename, nav label, rolling window in days; None = all history)
PERIODS = [
    ("last7.html", "7 days", 7),
    ("index.html", "30 days", 30),
    ("last90.html", "90 days", 90),
    ("all.html", "All time", None),
]

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spotify Dashboard — {label}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" integrity="sha384-cCVCZkAjYNxaYKbM8lsArLznDF/SvMFr1jcZrvOpSTCa0W40ZAdLzHCEulnUa5i7" crossorigin="anonymous"></script>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 1100px; padding: 0 1rem; color: #222; }}
 nav a {{ margin-right: 1rem; text-decoration: none; color: #1a7f37; }}
 nav a.current {{ font-weight: 700; text-decoration: underline; }}
 .metrics {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1.5rem 0; }}
 .metric {{ flex: 1 1 180px; border: 1px solid #ddd; border-radius: 8px; padding: 1rem; }}
 .metric .value {{ font-size: 1.6rem; font-weight: 600; }}
 .metric .delta {{ font-size: .9rem; }}
 .delta.up {{ color: #1a7f37; }} .delta.down {{ color: #c0392b; }}
 .cols {{ display: flex; gap: 2rem; flex-wrap: wrap; }}
 .cols > div {{ flex: 1 1 420px; min-width: 0; }}
 table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
 th, td {{ text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #eee; }}
 footer {{ margin-top: 2rem; color: #888; font-size: .85rem; }}
</style>
</head>
<body>
<h1>Spotify Listening Dashboard</h1>
<nav>{nav}</nav>
<p>Period: {start} ~ {end}</p>
{body}
<footer>Last updated {updated} UTC</footer>
</body>
</html>
"""


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _nav(current: str) -> str:
    return "".join(
        f'<a href="{f}" class="{"current" if f == current else ""}">{label}</a>'
        for f, label, _ in PERIODS
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Rows must already be safe HTML (escape text cells with _esc)."""
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in row)}</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _spotify_link(track_id) -> str:
    url = spotify_uri_to_url(track_id)
    return f'<a href="{_esc(url)}">Open</a>' if url else ""


def _metric(label: str, value: str, delta_pct: float | None) -> str:
    delta = ""
    if delta_pct is not None:
        cls = "up" if delta_pct >= 0 else "down"
        delta = f'<div class="delta {cls}">{delta_pct:+.1f}%</div>'
    return f'<div class="metric"><div>{_esc(label)}</div><div class="value">{_esc(value)}</div>{delta}</div>'


def _delta(summary: dict, prev: dict | None, key: str) -> float | None:
    if prev is None or not prev.get(key):
        return None
    return ((summary.get(key) or 0) - prev[key]) / prev[key] * 100


def _fig_html(fig) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _trend_html(db_path: str, start: str, end: str, all_time: bool) -> str:
    days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1
    if days <= 14:
        rows, key, gran = get_daily_trend(db_path, start_date=start, end_date=end), "date", "daily"
    elif days <= 92:
        rows, key, gran = get_weekly_trend(db_path, start_date=start, end_date=end), "week_label", "weekly"
    else:
        rows, key, gran = get_monthly_trend(db_path, start_date=start, end_date=end), "month_label", "monthly"
    if not rows:
        return "<p>No data in this period.</p>"
    fig = trend_figure(rows, key, gran)
    if all_time:
        fig.update_xaxes(rangeslider_visible=True)
    return _fig_html(fig)


def _render_page(db_path: str, filename: str, label: str, start: str, end: str,
                 prev_range: tuple[str, str] | None, updated: str) -> str:
    summary = get_listening_summary(db_path, start_date=start, end_date=end)
    prev = get_listening_summary(db_path, start_date=prev_range[0], end_date=prev_range[1]) if prev_range else None

    metrics = '<div class="metrics">' + "".join([
        _metric("Plays", f"{summary['total_plays']:,}", _delta(summary, prev, "total_plays")),
        _metric("Listening time", format_duration_mins(summary["total_mins_played"]),
                _delta(summary, prev, "total_mins_played")),
        _metric("Unique artists", f"{summary['unique_artists'] or 0:,}", _delta(summary, prev, "unique_artists")),
        _metric("Unique tracks", f"{summary['unique_tracks'] or 0:,}", _delta(summary, prev, "unique_tracks")),
    ]) + "</div>"

    artists = get_top_artists(db_path, limit=15, start_date=start, end_date=end)
    tracks = get_top_tracks(db_path, limit=15, start_date=start, end_date=end, show_track_id=True)
    tops = (
        '<div class="cols"><div><h3>Top Artists — by listening time</h3>'
        + _table(["Artist", "Listening time"],
                 [[_esc(a["artist_name"]), _esc(format_duration_mins(a["total_mins"]))] for a in artists])
        + '</div><div><h3>Top Tracks — by play count</h3>'
        + _table(["Track", "Artist", "Plays", "Spotify"],
                 [[_esc(t["track_name"]), _esc(t["artist_name"]), _esc(t["play_count"]),
                   _spotify_link(t.get("track_id"))] for t in tracks])
        + "</div></div>"
    )

    activity = get_daily_activity_pattern(db_path, start_date=start, end_date=end)
    activity_html = _fig_html(daily_activity_figure(activity)) if activity else "<p>No data in this period.</p>"

    recent = get_recent_plays(db_path, limit=50, show_track_id=True)
    recent_html = _table(
        ["Played at (UTC)", "Track", "Artist", "Album", "Spotify"],
        [[_esc((r["played_at"] or "").replace("T", " ").rstrip("Z")), _esc(r["track_name"]),
          _esc(r["artist_name"]), _esc(r["album_name"]), _spotify_link(r.get("track_id"))] for r in recent],
    )

    body = (
        metrics
        + tops
        + "<h3>Daily Activity Pattern</h3>" + activity_html
        + "<h3>Listening Trend</h3>" + _trend_html(db_path, start, end, all_time=prev_range is None)
        + "<h3>Recently Played (last 50)</h3>" + recent_html
    )
    return _PAGE.format(label=_esc(label), nav=_nav(filename), start=start, end=end,
                        body=body, updated=updated)


def build(db_path: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    updated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    written: list[Path] = []

    if is_history_empty(db_path):
        page = _PAGE.format(label="Empty", nav=_nav("index.html"), start="-", end="-",
                            body="<p>No listening history in the database yet.</p>", updated=updated)
        target = out_dir / "index.html"
        target.write_text(page, encoding="utf-8")
        return [target]

    today = datetime.datetime.now(datetime.timezone.utc).date()
    data_range = get_data_range(db_path)
    for filename, label, days in PERIODS:
        if days is not None:
            start = (today - datetime.timedelta(days=days - 1)).isoformat()
            end = today.isoformat()
            prev_range = (
                (today - datetime.timedelta(days=2 * days - 1)).isoformat(),
                (today - datetime.timedelta(days=days)).isoformat(),
            )
        else:
            start, end = data_range[0][:10], data_range[1][:10]
            prev_range = None
        target = out_dir / filename
        target.write_text(
            _render_page(db_path, filename, label, start, end, prev_range, updated),
            encoding="utf-8",
        )
        written.append(target)
    return written


if __name__ == "__main__":
    for path in build(str(settings.history_db_path), Path("site")):
        print(f"wrote {path}")
