import streamlit as st
import polars as pl
import plotly.express as px
import textwrap
from dataloader import get_top_artists, get_top_tracks

@st.cache_data(ttl= 15, max_entries=5)
def _get_top_artists_cached(_loader, k, start_date, end_date):
    return get_top_artists(_loader, k=k, start_date=start_date, end_date=end_date)

@st.cache_data(ttl= 15, max_entries=5)
def _get_top_tracks_cached(_loader, k, artist, start_date, end_date):
    return get_top_tracks(_loader, k=k, artist=artist, start_date=start_date, end_date=end_date)

def wrap_text(text, width=20):
    """Wrap text with newline characters if it exceeds width."""
    if not text:
        return ""
    return "<br>".join(textwrap.wrap(str(text), width=width))

def render_track_artist_analysis(loader, start_date, end_date, show_tables):
    st.header("Track/Artist-Based Analysis")
    
    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap="medium",
    ):
        # Place filters at the top of the section for better interactive flow
        top_k = st.select_slider("Top results to display:",
                                options=list(range(5, 26)), value=5,
                                )
        st.text_input(
            "Filter Tracks by Artist (optional):", 
            key="artist_filter", 
            placeholder="e.g. The Beatles"
        )

    # Define Row with dynamic height for symmetry
    row_height = 400 + (top_k * 16)
    row = st.container()
    
    with row:
        col1, col2 = st.columns(2)
        
        with col1:
            with st.spinner("Calculating top artists..."):
                top_artists_df = _get_top_artists_cached(loader, k=top_k, start_date=start_date, end_date=end_date)
                
                if not top_artists_df.is_empty():
                    # Apply text wrapping to artist names for display
                    display_df = top_artists_df.with_columns(
                        pl.col("artist").map_elements(lambda x: wrap_text(x, 25), return_dtype=pl.Utf8)
                    ).to_pandas()

                    # Create Plotly figure
                    fig = px.bar(
                        display_df, 
                        x="minutes_played", 
                        y="artist",
                        orientation='h',
                        title=f"Top {top_k} Artists (Minutes Played)",
                        labels={"minutes_played": "Minutes Listened", "artist": "Artist"},
                        hover_data=["total_tracks_played", "unique_listened_tracks", "ratio_uniq_over_total"],
                        color="minutes_played",
                        color_continuous_scale="plasma",
                        text="minutes_played",
                    )
                    fig.update_traces(
                        textposition="outside", 
                        cliponaxis=False,
                    )
                    fig.update_layout(
                        yaxis={
                            'type': 'category', # strictly impose the data type
                            'categoryorder':'total ascending',
                            'automargin': True, # 強制自動計算邊距，防止文字被切掉
                            }, 
                        margin=dict(l=50, r=20, t=50, b=50), # l 代表 Left，可以手動給一點基礎空間
                        # 讓標題不會跟 Y 軸標籤疊在一起
                        yaxis_title_standoff=20,
                        coloraxis_showscale=False,
                        height=row_height
                    )
                    st.plotly_chart(fig, width="stretch")
                    
                    # Show table view
                    if show_tables:
                        with st.expander("Show Artist Data Table"):
                            st.dataframe(top_artists_df.to_pandas().set_axis(
                                    range(1, len(top_artists_df)+1), axis=0
                                    ).head(100),
                                    width="stretch")
                else:
                    st.info("No artist data found for the selected date range.")
        # ==================== Show Top Tracks ===============
        with col2:
            with st.spinner("Calculating top tracks..."):
                artist_filter = st.session_state.get("artist_filter", "")
                top_tracks_df = _get_top_tracks_cached(
                    loader, 
                    k=top_k, 
                    artist=artist_filter if artist_filter else None, 
                    start_date=start_date, 
                    end_date=end_date
                )
                
                if not top_tracks_df.is_empty():
                    # Apply text wrapping to track names for display
                    display_df = top_tracks_df.with_columns(
                        pl.col("track").map_elements(lambda x: wrap_text(x, 30), return_dtype=pl.Utf8)
                    ).to_pandas()

                    # Create Plotly figure
                    fig = px.bar(
                        display_df, 
                        x="play_count", 
                        y="track",
                        orientation='h',
                        labels={"track": "Track", "play_count": "Times Played", "minutes_played": "Minutes listened", "artist": "Artist", "album": "Album"},
                        hover_data=["minutes_played", "artist", "album"],
                        color="artist" if not artist_filter else "album",
                        text="play_count"
                    )
                    fig.update_traces(
                        textposition="outside", 
                        cliponaxis=False,
                    )
                    _title = f"Top {top_k} Tracks" + (f" by {artist_filter}" if artist_filter else "")
                    fig.update_layout(
                        title=_title,
                        yaxis={
                            'type': 'category', # strictly impose the data type
                            'categoryorder':'total ascending',
                            'automargin': True, # 強制自動計算邊距，防止文字被切掉
                            }, 
                        margin=dict(l=50, r=20, t=50, b=50), # l 代表 Left，可以手動給一點基礎空間
                        # 讓標題不會跟 Y 軸標籤疊在一起
                        yaxis_title_standoff=20,
                        yaxis_tickfont_size=11,
                        bargap=0.2,
                        coloraxis_showscale=False,
                        showlegend = False,
                        height=row_height
                    )
                    st.plotly_chart(fig, width="stretch")
                    
                    # Show table view
                    if show_tables:
                        with st.expander("Show Track Data Table"):
                            st.dataframe(top_tracks_df.to_pandas().set_axis(
                                    range(1, len(top_tracks_df)+1), axis=0
                                    ).head(100),
                                    width="stretch")
                else:
                    st.info("No track data found for the selected date range.")
