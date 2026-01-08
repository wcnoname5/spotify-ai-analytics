import streamlit as st
import plotly.express as px
from pathlib import Path
from utils.data_loader import SpotifyDataLoader
from analytics.features.analysis_functions import get_top_artists, get_raw_df

st.set_page_config(page_title="Spotify AI Analytics", page_icon="🎵", layout="wide")

@st.cache_resource
def get_loader():
    # Assuming data is in the default data/spotify_history directory
    data_dir = Path("data/spotify_history")
    loader = SpotifyDataLoader(data_dir)
    return loader

def main():
    st.title("🎵 Spotify Listening Analytics")
    
    loader = get_loader()
    summary = loader.get_summary()
    
    if summary['total_records'] == 0:
        st.warning("No Spotify history data found. Please check your data/spotify_history folder.")
        return

    # Sidebar filters
    st.sidebar.header("Filters")
    
    # Get range from data
    min_date = summary['date_range']['start'] if summary['date_range'] else None
    max_date = summary['date_range']['end'] if summary['date_range'] else None
    
    if min_date and max_date:
        import datetime
        min_d = datetime.date.fromisoformat(min_date)
        max_d = datetime.date.fromisoformat(max_date)
        
        start_date = st.sidebar.date_input("Start Date", value=None, min_value=min_d, max_value=max_d)
        end_date = st.sidebar.date_input("End Date", value=None, min_value=min_d, max_value=max_d)
    else:
        start_date = None
        end_date = None

    # Analysis Section
    st.header("Top 5 Artists by Listening Time")
    
    with st.spinner("Calculating top artists..."):
        top_artists_df = get_top_artists(loader, k=None, start_date=start_date, end_date=end_date)
        
        if not top_artists_df.is_empty():
            # Create Plotly figure
            fig = px.bar(
                top_artists_df.head(10).to_pandas(), 
                x="minutes_played_sum", 
                y="artist",
                orientation='h',
                title="Top 5 Artists (Minutes Played)",
                labels={"minutes_played_sum": "Minutes Listened", "artist": "Artist"},
                color="minutes_played_sum",
                color_continuous_scale="Viridis"
            )
            fig.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig, width="stretch")
            
            # Show table view
            st.subheader("Data Table: `get_top_artists`")
            st.dataframe(top_artists_df.to_pandas().set_axis(
                    range(1, len(top_artists_df)+1), axis=0
                    ).head(100),
                    width="stretch", )
        else:
            st.info("No data found for the selected date range.")

    # playground
    st.header("Raw Data Preview")    
    with st.spinner("Calculating top artists..."):
        raw_df = get_raw_df(loader, limit=100, start_date=start_date, end_date=end_date)
        st.subheader("Table ")
        if not top_artists_df.is_empty():
            st.dataframe(raw_df.to_pandas().set_axis(
                    range(1, len(raw_df)+1), axis=0
                ),
                width="stretch")
        else:
            st.info("No data found for the selected date range.")

# plot: line plot:
# x axis: time(montly/weekly)
# y axis: listenlingtime (or normalized to proportion of total listening time) / rank 
# lines: favrotite artists / tracks (this may not work)
# lines can be selectively shown or not



if __name__ == "__main__":
    main()
