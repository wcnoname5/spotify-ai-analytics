"""DB-backed analytics dashboard (Streamlit page)."""
import datetime

import streamlit as st
from loguru import logger

from spotify_core.config import settings
from spotify_core.db.pipeline import sync_api_to_db
from spotify_core.db.queries import (
    get_daily_activity_pattern,
    get_daily_trend,
    get_listening_summary,
    get_monthly_trend,
    get_recent_plays,
    get_top_artists,
    get_top_tracks,
    get_weekly_trend,
    is_history_empty,
)
from spotify_web.charts import daily_activity_figure, trend_figure
from spotify_web.config import get_sync_args
from spotify_web.formatting import format_duration_ms, spotify_uri_to_url

_DB_PATH = str(settings.history_db_path)
_CACHE_TTL = 30


@st.cache_data(ttl=_CACHE_TTL)
def _summary(start, end):
    return get_listening_summary(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _top_artists(start, end, limit=5):
    return get_top_artists(_DB_PATH, limit=limit, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _top_tracks(start, end, limit=5):
    return get_top_tracks(
        _DB_PATH, limit=limit, start_date=start, end_date=end, show_track_id=True
    )


@st.cache_data(ttl=_CACHE_TTL)
def _activity(start, end):
    return get_daily_activity_pattern(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _daily(start, end):
    return get_daily_trend(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _weekly(start, end):
    return get_weekly_trend(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _monthly(start, end):
    return get_monthly_trend(_DB_PATH, start_date=start, end_date=end)


@st.cache_data(ttl=_CACHE_TTL)
def _recent():
    return get_recent_plays(_DB_PATH, limit=50, show_track_id=True)


def _format_played_at(played_at: str | None) -> str | None:
    if played_at is None:
        return None
    try:
        return (
            datetime.datetime.fromisoformat(played_at.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    except (TypeError, ValueError):
        return played_at


def _period_dates() -> tuple[str, str]:
    """Render the period filter; return (start_iso, end_iso) date strings."""
    today = datetime.date.today()
    choice = st.radio(
        "分析區間",
        ["本周", "本月", "自訂時間"],
        horizontal=True,
        key="period_choice",
    )
    if choice == "本周":
        start = today - datetime.timedelta(days=today.weekday())
        end = today
    elif choice == "本月":
        start = today.replace(day=1)
        end = today
    else:
        c1, c2 = st.columns(2)
        start = c1.date_input(
            "開始", value=today - datetime.timedelta(days=30), key="custom_start"
        )
        end = c2.date_input("結束", value=today, key="custom_end")
    return start.isoformat(), end.isoformat()


def _run_sync() -> None:
    """Pull recent plays from the Spotify API into the local DB."""
    args = get_sync_args()
    if not args["client_id"] or not args["fernet_key"]:
        st.error(
            "缺少 SPOTIFY_CLIENT_ID 或 TOKEN_ENCRYPT_KEY，請先執行 `spotify-mcp setup`。"
        )
        return
    try:
        result = sync_api_to_db(**args)
        st.cache_data.clear()
        st.toast(f"已同步 {result['inserted']} 筆新播放紀錄")
    except RuntimeError as exc:
        st.error(f"同步失敗：{exc}")
    except Exception as exc:  # noqa: BLE001 - surface any sync error in the UI
        logger.exception("Dashboard sync failed")
        st.error(f"同步時發生錯誤：{exc}")


def _stats_section(start: str, end: str) -> None:
    st.subheader("Top Stats")
    col_a, col_t = st.columns(2)
    with col_a:
        st.caption("Top Artists - by listening time")
        artists = _top_artists(start, end, limit=15)
        if artists:
            st.dataframe(
                [
                    {
                        "Artist": a["artist_name"],
                        "Listening time": format_duration_ms(a["total_ms"]),
                    }
                    for a in artists
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("此區間沒有資料。")
    with col_t:
        st.caption("Top Tracks - by play count")
        tracks = _top_tracks(start, end, limit=15)
        if tracks:
            st.dataframe(
                [
                    {
                        "Track": t["track_name"],
                        "Artist": t["artist_name"],
                        "Plays": t["play_count"],
                        "Spotify": spotify_uri_to_url(t.get("track_id")),
                    }
                    for t in tracks
                ],
                column_config={
                    "Spotify": st.column_config.LinkColumn(
                        "Spotify", display_text="Open"
                    )
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("此區間沒有資料。")


def _trend_section(start: str, end: str) -> None:
    """Render Plot 2, picking granularity from the period span."""
    days = (
        datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)
    ).days + 1
    if days <= 14:
        rows, label_key, gran = _daily(start, end), "date", "daily"
    elif days <= 92:
        rows, label_key, gran = _weekly(start, end), "week_label", "weekly"
    else:
        rows, label_key, gran = _monthly(start, end), "month_label", "monthly"
    if rows:
        st.plotly_chart(trend_figure(rows, label_key, gran), width="stretch")
    else:
        st.info("此區間沒有資料。")


def _recent_section() -> None:
    st.subheader("Recently Played (last 50)")
    rows = _recent()
    if not rows:
        st.info("資料庫沒有播放紀錄。")
        return
    st.dataframe(
        [
            {
                "Played at": _format_played_at(r["played_at"]),
                "Track": r["track_name"],
                "Artist": r["artist_name"],
                "Album": r["album_name"],
                "Spotify": spotify_uri_to_url(r.get("track_id")),
            }
            for r in rows
        ],
        column_config={
            "Spotify": st.column_config.LinkColumn("Spotify", display_text="Open")
        },
        hide_index=True,
        width="stretch",
    )


def render_dashboard() -> None:
    st.subheader("Dashboard")

    col_filter, col_sync = st.columns([4, 1], vertical_alignment="top")
    with col_sync:
        if st.button("Sync", width="stretch"):
            _run_sync()
    with col_filter:
        start, end = _period_dates()

    if is_history_empty(_DB_PATH):
        st.warning(
            "資料庫沒有資料。請執行 `spotify-mcp setup` 匯入歷史，"
            "或點右上 Sync 取得最近 50 筆播放。"
        )
        return

    summary = _summary(start, end)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Plays", f"{summary['total_plays']:,}")
    m2.metric("Listening time", format_duration_ms(summary["total_ms_played"]))
    m3.metric("Unique artists", f"{summary['unique_artists'] or 0:,}")
    m4.metric("Unique tracks", f"{summary['unique_tracks'] or 0:,}")

    st.divider()
    _stats_section(start, end)

    st.divider()
    st.subheader("Daily Activity Pattern")
    activity = _activity(start, end)
    if activity:
        st.plotly_chart(daily_activity_figure(activity), width="stretch")
    else:
        st.info("此區間沒有資料。")

    st.subheader("Listening Trend")
    _trend_section(start, end)

    st.divider()
    _recent_section()
