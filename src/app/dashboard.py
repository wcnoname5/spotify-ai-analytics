import streamlit as st
from config.settings import settings
from dataloader import (
    SpotifyDataLoader,
    get_summary_by_time, 
    get_raw_df
)
from app.track_analysis import render_track_artist_analysis
from app.time_analysis import render_time_analysis

# return loader as a global instance (cached resource)
@st.cache_resource
def get_loader():
    """
    Cached loader that returns a singleton instance across page reruns.
    Data is loaded lazily on first access.
    """
    # Use path from centralized settings
    loader = SpotifyDataLoader(settings.spotify_data_path)
    return loader

# Cached wrapper for summary by time (using hash table)
# use start_date& end_date to generate cache keys (fingerprint)
# Upon activation, it would check if fingerprint exists
# if yes, it would use figerprint to retrieve cached result
# else it would perform a new query and cache the result
@st.cache_data
def _get_summary_by_time_cached(_loader, start_date=None, end_date=None):
    return get_summary_by_time(_loader, start_date=start_date, end_date=end_date)

def render_dashboard():
    st.title("Analytics Dashboard for Spotify Data")

    # Initialize session state for filtering
    if "artist_filter" not in st.session_state:
        st.session_state.artist_filter = ""
    
    loader = get_loader()
    summary = loader.get_summary()
    
    if summary['total_records'] == 0:
        st.warning("No Spotify history data found. Please check your data/spotify_history folder.")
        return

    # ===================== Header ================= 
    st.header("Full Listening History")
    # Use summary from loader to avoid redundant calculation
    full_summary = summary
    
    date_range = full_summary['date_range']
    if date_range:
        st.caption(f"Full Data Range: {date_range['start']} to {date_range['end']}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Tracks", f"{full_summary['total_records']:,}")
    m2.metric("Listening Time (min)", f"{full_summary['total_listening_time']:,}")
    m3.metric("Unique Artists", f"{full_summary['unique_artists'] or 0:,}")
    m4.metric("Unique Tracks", f"{full_summary['unique_tracks'] or 0:,}")

    st.divider()
    # ===================== global filters ================= 
    with st.expander("Global Filters", expanded=True):
        # Toggle for data tables
        show_tables = not st.checkbox("Hide Data Tables", value=False)
        # Get range from data (strings)
        min_date_str = full_summary['date_range']['start'] if full_summary['date_range'] else None
        max_date_str = full_summary['date_range']['end'] if full_summary['date_range'] else None
        
        if min_date_str and max_date_str:
            import datetime
            # Convert to date objects
            min_d = datetime.date.fromisoformat(min_date_str)
            max_d = datetime.date.fromisoformat(max_date_str)
            with st.container(horizontal=True, gap="large"):
                start_date = st.date_input("Start Date", value=min_d, min_value=min_d, max_value=max_d)
                end_date = st.date_input("End Date", value=max_d, min_value=min_d, max_value=max_d)
            
            # Optimization: Check if filters are active
            is_filtered = (start_date > min_d) or (end_date < max_d)
        else:
            start_date = None
            end_date = None
            is_filtered = False

    # ===================== Summary =================
    # Extra query is activated only if when filters are applied 
    st.header("Selected Date Range Summary")
    
    if not is_filtered:
        st.info("💡 Showing results for full date range.")
        time_summary = full_summary
    else:
        with st.spinner("Calculating filtered summary..."):
            time_summary = _get_summary_by_time_cached(loader, start_date=start_date, end_date=end_date)
    
    date_range_f = time_summary['date_range']
    if date_range_f and is_filtered:
        st.caption(f"Filtered Range: {date_range_f['start']} to {date_range_f['end']}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tracks Listened", f"{time_summary['total_records']:,}")
    m2.metric("Listening Time (min)", f"{time_summary['total_listening_time']:,}")
    m3.metric("Unique Artists", f"{time_summary['unique_artists'] or 0:,}")
    m4.metric("Unique Tracks", f"{time_summary['unique_tracks'] or 0:,}")

    # =============== Track/Artist-Based Analysis ===============
    st.divider()
    render_track_artist_analysis(loader, start_date, end_date, show_tables)

    #  =============== Time-Based Analysis ===============
    st.divider()
    render_time_analysis(loader, start_date, end_date, show_tables)

    # Raw Data Preview
    if show_tables:
        st.divider() # horizontal line
        st.header("Raw Data Preview")
        with st.spinner("Loading raw data..."):
            raw_df = get_raw_df(loader, limit=100, start_date=start_date, end_date=end_date)
            if not raw_df.is_empty():
                st.dataframe(raw_df.to_pandas().set_axis(
                        range(1, len(raw_df)+1), axis=0
                    ),
                    width="stretch"
                )
            else:
                st.info("No data found for the selected date range.")

if __name__ == "__main__":
    # This is for standalone debugging only
    st.set_page_config(page_title="Spotify AI Analytics", page_icon="🎵", layout="wide")
    render_dashboard()