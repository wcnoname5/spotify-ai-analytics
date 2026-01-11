import streamlit as st
from pathlib import Path
from utils.data_loader import SpotifyDataLoader
from analytics.features.analysis_functions import (
    get_summary_by_time, 
    get_raw_df
)
from analytics.dashboard.track_artist import render_track_artist_analysis
from analytics.dashboard.time_analysis import render_time_analysis

@st.cache_resource
def get_loader():
    # Assuming data is in the default data/spotify_history directory
    data_dir = Path("data/spotify_history")
    loader = SpotifyDataLoader(data_dir)
    return loader

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
    with st.spinner("Calculating summary..."):
        time_summary = get_summary_by_time(loader)
        # TODO: add more metrics if needed
        date_range = summary['date_range']
        if date_range:
            st.write(f"Data Range: {date_range['start']} to {date_range['end']}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Tracks Listened", f"{time_summary['total_records']:,}")
        m2.metric("Total Listiening Time (min)", f"{time_summary['total_listening_time']:,}")
        m3.metric("Unique Artists", f"{time_summary['unique_artists']:,}")
        m4.metric("Unique Tracks", f"{time_summary['unique_tracks']:,}")

    st.divider()
    # ===================== global filters ================= 
    # TODO: replace it with self-defined Sticky Header using CSS via markdown
    # CSS position: sticky;/position: fixed; 
    with st.expander("Global Filters", expanded=True):
        # Toggle for data tables
        show_tables = not st.checkbox("Hide Data Tables", value=False)
        # Get range from data
        min_date = summary['date_range']['start'] if summary['date_range'] else None
        max_date = summary['date_range']['end'] if summary['date_range'] else None
        # add date range picker
        if min_date and max_date:
            import datetime
            min_d = datetime.date.fromisoformat(min_date)
            max_d = datetime.date.fromisoformat(max_date)
            with st.container(horizontal=True, gap="large"):
                start_date = st.date_input("Start Date", value=min_d, min_value=min_d, max_value=max_d)
                end_date = st.date_input("End Date", value=max_d, min_value=min_d, max_value=max_d)
        else:
            start_date = None
            end_date = None
    # ===================== Summary ================= 
    st.divider()
    # Analysis Summary 
    st.header("Listening Stats Summary from Selected Date Range")
    with st.spinner("Calculating summary..."):
        time_summary = get_summary_by_time(loader, start_date=start_date, end_date=end_date)
        date_range = time_summary['date_range']
        if date_range:
            st.write(f"Data Range: {date_range['start']} to {date_range['end']}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Tracks Listened", f"{time_summary['total_records']:,}")
        m2.metric("Total Listiening Time (min)", f"{time_summary['total_listening_time']:,}")
        m3.metric("Unique Artists", f"{time_summary['unique_artists']:,}")
        m4.metric("Unique Tracks", f"{time_summary['unique_tracks']:,}")

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
    st.set_page_config(page_title="Spotify AI Analytics", page_icon="🎵", layout="wide")
    render_dashboard()