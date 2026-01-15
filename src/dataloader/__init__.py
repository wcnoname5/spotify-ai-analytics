'''
Initialize the dataloader package for Spotify data analysis.
The package include:
- `SpotifyDataLoader` object provides methods to load and query Spotify listening history data.
- `analysis_fucntions` offer various summary statistics and trends based on the loaded data.
'''
from .data_loader import SpotifyDataLoader
from .analysis_functions import (
    SummaryStats,
    query_data,
    aggregate_table,
    get_summary,
    get_top_artists,
    get_top_tracks,
    get_monthly_listening_trend,
    get_weekly_listening_trend,
    get_raw_df
)
