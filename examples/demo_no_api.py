"""
Demo script to showcase the Spotify AI Analytics Agent capabilities.

demonstrate the queries and the aggregation functions in data_loader

Note: For best results, install the package in development mode:
    pip install -e .

If not installed, this script will attempt to add src to path.
"""
import os
from dotenv import load_dotenv
import sys
import polars as pl
from pathlib import Path

load_dotenv()
data_path = os.getenv("SPOTIFY_DATA_PATH", "data/spotify_history")
# Try importing directly, fall back to path manipulation if not installed
try:
    from dataloader import SpotifyDataLoader, get_summary, query_data, aggregate_table
except ImportError:
    # Add src to path as fallback (not recommended for production)
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from dataloader import SpotifyDataLoader, get_summary, query_data, aggregate_table


def demo_data_loading():
    """Demonstrate data loading and processing capabilities."""
    
    print("=" * 70)
    print("Spotify AI Analytics Agent - Data Loading Demo")
    print("=" * 70)
    print()
    
    # Initialize loader & Load data
    loader = SpotifyDataLoader(data_path)
    print(f"Loading Spotify data from: {data_path}")
    
    # Display summary
    summary = get_summary(loader.df)
    print("\n📊 Data Summary:")
    print("-" * 70)
    print(f"  Total listening records: {summary['total_records']:,}")
    print(f"  Unique tracks: {summary['unique_tracks']:,}")
    print(f"  Unique artists: {summary['unique_artists']:,}")
    print(f"  Columns available: {', '.join(summary['columns'])}")
    
    if summary['date_range']:
        print(f"  Date range: {summary['date_range']['start']}")
        print(f"            to {summary['date_range']['end']}")
    
    # Show sample records
    # where pattern
    print("\n🎵 Sample Listening History (The Smiths, between 2021 and 2023):")
    print("-" * 70)
    df_sample = query_data(
        loader.df,
        where=[pl.col('artist') == 'The Smiths',
               pl.col('year').is_between(2021, 2023)],
        select=['timestamp', 'track', 'artist', 'ms_played', 'reason_end'],
        sort_by='timestamp',
        descending=False,
        limit=10
    )
    print(df_sample)
    
    # Show listening patterns
    print("\n📈 Listening Patterns:")
    print("-" * 70)
    
    # Most played artists by play count
    print("\n  Top 10 Artists (by play count):")
    artist_counts = aggregate_table(
        loader.df,
        group_by=['artist'],
        metrics={'track': ('count', 'total_listening_counts')},
        sort_by='total_listening_counts',
        descending=True,
        limit=10
    )
    print(artist_counts)
    
    # Most played artists by total listening time
    print("\n  Top 10 Artists (by total listening time):")
    artist_time = aggregate_table(
        loader.df,
        group_by=['artist'],
        metrics={'ms_played': 'sum'},
        sort_by='ms_played_sum',
        descending=True,
        limit=10
    ).select(
        pl.col('artist'),
        pl.col("ms_played_sum").dt.total_hours().alias("total_listening_time (hr)")
    )
    print(artist_time)
    
    # Most played tracks
    print("\n  Top 10 Tracks (by play count):")
    track_counts = loader.df.filter(
        pl.col("reason_end").is_in(["trackdone", "endplay"]) # check if the track finished playing
    ).group_by(
        ["artist", "track"]
    ).agg(
        [pl.count("track_uri").alias("track_play_count")]
    ).select(
        [   
            "artist", "track", "track_play_count"
        ]
    ).sort(
        "track_play_count",
        descending=True
    ).head(10)

    track_counts = loader.aggregate_table(
        where=[pl.col("reason_end").is_in(["trackdone", "endplay"])],
        group_by=['artist', 'track'],
        metrics={'track': ('count', 'listening_times')},
        sort_by='listening_times',
        descending=True,
        limit=10
    )

    
    print(track_counts)
    
    # Listening by hour of day
    print("\n  Listening by Hour of Day:")
    
    hour_stats = loader.aggregate_table(
        group_by=['hour'],
        metrics={'track': ('count', 'total_tracks'), 'ms_played': 'sum'},
        sort_by='ms_played_sum',
        descending=True
    ).select(
        pl.col('hour'),
        (pl.col("ms_played_sum")/pl.col("ms_played_sum").sum()).alias("Proportion of listening")
    ).filter(pl.col("Proportion of listening") > 0.04)
    print(hour_stats)
    
    # Listening by platform
    print("\n  Listening by Platform:")
    platform_stats = loader.aggregate_table(
        group_by=['platform'],
        metrics={'track': 'count', 'ms_played': 'sum'},
        sort_by='track_count',
        descending=True
    )
    # print(platform_stats)
    
    # Listening by year
    print("\n  Listening by Year:")
    year_stats = loader.aggregate_table(
        group_by=['year'],
        metrics={'track': ('count', 'total_listening_tracks'),
                 'track_uri': ('n_unique', 'unique_tracks'),
                 'artist': ('n_unique', 'unique_artists')},
        sort_by='year',
        descending=True
    )
    print(year_stats)
    
    # Demonstrate multiple metrics per column
    print("\n  Top 5 Tracks (with multiple metrics):")
    multi_metrics = loader.aggregate_table(
        group_by=['track', 'artist'],
        metrics={
            'track': [('count', 'play_count'), ('n_unique', 'unique_days')], # unique_days isn't quite right here but for demo
            'ms_played': [('sum', 'total_ms'), ('mean', 'avg_ms')]
        },
        sort_by='play_count',
        limit=5
    )
    print(multi_metrics)
    
    
    print("\n" + "=" * 70)
    print("Demo Complete!")
    print("=" * 70)
    print()
    print("To use the full AI agent with natural language queries:")
    print("1. Set up your OpenAI API key in .env file")
    print("2. Install all dependencies: pip install -r requirements.txt")
    print("3. Run: python -m spotify_agent.cli")
    print("   Or if installed: spotify-agent")
    print()


if __name__ == "__main__":
    try:
        demo_data_loading()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nPlease ensure:")
        print("  • You are in the project root directory")
        print("  • Sample data exists in data/spotify_history/")
