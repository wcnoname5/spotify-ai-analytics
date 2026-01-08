import polars as pl
from typing import Literal, Optional
from datetime import date
from utils.data_loader import SpotifyDataLoader

def get_top_artists(
    loader: SpotifyDataLoader,
    k: int = 5,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get top k artists by total listening time in minutes.
    
    Args:
        loader: Initialized SpotifyDataLoader instance
        k: Number of top artists to return
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
        
    Returns:
        Polars DataFrame with 'artist' and 'minutes_played_sum'
    """
    filters = []
    if start_date:
        filters.append(pl.col("date") >= start_date)
    if end_date:
        filters.append(pl.col("date") <= end_date)
        
    result = loader.aggregate_table(
        group_by=["artist"],
        metrics={
            "ms_played": ("sum", "total_ms"),
            "track": [("count", "total_tracks_played"), ("n_unique", "unique_listened_tracks")]
            },
        where=filters,
        sort_by="total_ms",
        descending=True,
        limit=k
    )
    return result.with_columns(
        minutes_played_sum = pl.col("total_ms").dt.total_minutes(),
        ratio_uniq_over_total = (pl.col("unique_listened_tracks") / pl.col("total_tracks_played")).round(2),
        avg_played_min_of_track = (pl.col("total_ms") / pl.col("total_tracks_played")).dt.total_minutes(),

    ).drop("total_ms")

def get_top_tracks(
    loader: SpotifyDataLoader,
    k: int = 5,
    artist: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get top k tracks by total listening time in minutes.
    
    Args:
        loader: Initialized SpotifyDataLoader instance
        k: Number of top tracks to return
        start_date: Optional start date for filtering
        end_date: Optional end date for filtering
        
    Returns:
        Polars DataFrame with 'artist' and 'minutes_played_sum'
    """
    where = []
    if artist:
        where.append(pl.col("artist").str.to_lowercase() == artist.lower())
    if start_date:
        # Convert string to date for comparison
        where.append(pl.col("date") >= pl.lit(start_date).str.to_date())
    if end_date:
        where.append(pl.col("date") <= pl.lit(end_date).str.to_date())
        
    result = loader.aggregate_table(
        group_by=["track", "artist", "album"],
        metrics={"track": ("count", "play_count")},
        where=where,
        sort_by="play_count",
        descending=True,
        limit=k
    )
    return result.with_columns(
        # minutes_played_sum = pl.col("total_ms").dt.total_minutes(),
        # ratio_uniq_over_total = (pl.col("unique_listened_tracks") / pl.col("total_tracks_played")).round(2),
        # avg_played_min_of_track = (pl.col("total_ms") / pl.col("total_tracks_played")).dt.total_minutes(),

    ).drop("track")

def get_listening_trend_by_time(
    loader: SpotifyDataLoader,
    by: Literal["artist", "track"] = "artist",
    k: int = 5,
    artist: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None):
    '''
    Group by date(or other timescales, month, year, daytime/weekday) and aggregate:
    1. how many times/tracks are played that date
    2. how time scales be binding:
        - for example: daytime should be grouped into intervals

        - season can be binded by multiple months
    ordering: can show top track/artist of the interval
    '''
    df = loader.aggregate_table(
        group_by=["year", "month", by]
    )
    pass
# get listening trend (date-based)

# get listening trend (time-based): week/daytime
# group_by weekday & hour
# hour need to pregrouping into several time intervals

# daily listening time:
# to get the top listening (listened most tracks/time) date of the year

def get_raw_df(loader: SpotifyDataLoader,
                limit: int,
                start_date: Optional[date] = None,
                end_date: Optional[date] = None
            ) -> pl.DataFrame:
    """
    Get raw listening history data with optional filtering and limit.
    """
    filters = []
    if start_date:
        filters.append(pl.col("date") >= start_date)
    if end_date:
        filters.append(pl.col("date") <= end_date)

    return loader.query_data(
        where=filters if filters else None,
        limit=limit
    )


# explorations:

# how many artist listened

# top ten artist/tracks over total listened tracks/artist

