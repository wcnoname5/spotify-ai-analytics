import polars as pl
from typing import Literal, Optional, Dict
from datetime import date
from utils.data_loader import SpotifyDataLoader

def get_summary_by_time(
    loader: SpotifyDataLoader,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
)-> Dict:
    filters = []
    if start_date:
        filters.append(pl.col("date") >= start_date)
    if end_date:
        filters.append(pl.col("date") <= end_date)
    df = loader.query_data(where=filters)

    if df is None or df.is_empty():
        return {
            'total_records': 0,
            'total_listening_time': 0,
            'columns': [],
            'date_range': None,
            'unique_tracks': None,
            'unique_artists': None
        }

    summary = {
        'total_records': df.height, # total listening records
        'total_listening_time': 0, # in minutes
        'columns': list(df.columns), 
        'date_range': None, # start and end dates{'start': ..., 'end': ...}
        'unique_tracks': None,
        'unique_artists': None
    }
    if 'ms_played' in df.columns:
        # Use Polars duration methods for unit conversion
        total_minutes = df.select(
            pl.col('ms_played').sum().dt.total_minutes()
        ).item()
        summary['total_listening_time'] = int(total_minutes)

    if 'date' in df.columns:
        arr = df.select(pl.col('date')).to_series()
        summary['date_range'] = {
            'start': str(arr.min()),
            'end': str(arr.max())
        }

    track_identifier = 'track_uri' # use track URI for uniqueness ()
    if track_identifier:
        summary['unique_tracks'] = int(df.select(pl.col(track_identifier).n_unique()).item())

    artist_col_name = 'artist'
    if artist_col_name:
        summary['unique_artists'] = int(df.select(pl.col(artist_col_name).n_unique()).item())

    return summary

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
        Polars DataFrame with 'artist' and 'minutes_played'
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
        minutes_played = pl.col("total_ms").dt.total_minutes().round(0).cast(pl.Int64),
        hours_played = pl.col("total_ms").dt.total_hours().round(0).cast(pl.Int64),
        ratio_uniq_over_total = (pl.col("unique_listened_tracks") / pl.col("total_tracks_played")).round(2),
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
        Polars DataFrame with 'artist' and 'minutes_played'
    """
    where = []
    if artist:
        # TODO: maybe cahnge to partial match?
        where.append(pl.col("artist").str.to_lowercase() == artist.lower())
    if start_date:
        # Convert string to date for comparison
        where.append(pl.col("date") >= start_date)
    if end_date:
        where.append(pl.col("date") <= end_date)
        
    result = loader.aggregate_table(
        group_by=["track", "artist", "album"],
        metrics={"track": ("count", "play_count"),
                 "ms_played": ("sum", "total_ms")},
        where=where,
        sort_by="play_count",
        descending=True,
        limit=k
    )
    return result.with_columns(
        minutes_played = pl.col("total_ms").dt.total_minutes().round(0).cast(pl.Int64)  
    ).drop("total_ms")

def get_monthly_listening_trend(
    loader: SpotifyDataLoader,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get monthly listening trend (total listening time per month).
    Inspired by R script's monthly aggregation.
    """
    # Filter for > 30s as in the R script
    # where = [pl.col("ms_played") > pl.duration(seconds=30)]
    where = []
    if start_date:
        where.append(pl.col("date") >= start_date)
    if end_date:
        where.append(pl.col("date") <= end_date)

    result = loader.aggregate_table(
        group_by=["year", "month"],
        metrics={"ms_played": ("sum", "total_ms"),
                 "track": [
                     ("count", "total_tracks_played"),
                     ("n_unique", "unique_listened_tracks")
                           ]
                },
        where=where,
    )
    
    if result.is_empty():
        return result
    
    return result.with_columns(
        total_minutes = pl.col("total_ms").dt.total_minutes().round(0).cast(pl.Int64),
        total_hours = pl.col("total_ms").dt.total_hours().round(0).cast(pl.Int64),
        month_label = pl.format("{}-{}-1", pl.col("year"), pl.col("month"))
                  .str.to_date("%Y-%b-%d")
    ).sort("month_label")


# get listening trend (date-based)

# get listening trend (time-based): week/daytime
# group_by weekday & hour
# hour need to pregrouping into several time intervals

def get_weekly_listening_trend(
    loader: SpotifyDataLoader,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get weekly and daytime listening trend
    grouped by daytime (Night, Morning, Afternoon, Evening)
    """
    # Filter for > 30s as in the R script
    # where = [pl.col("ms_played") > pl.duration(seconds=30)]
    where = []
    if start_date:
        where.append(pl.col("date") >= start_date)
    if end_date:
        where.append(pl.col("date") <= end_date)
    
    df = loader.df
    if df is None or df.is_empty():
        return pl.DataFrame()

    # Apply filters
    if where:
        df = df.filter(pl.all_horizontal(where))

    result = df.with_columns(
        time_range=pl.col("hour").cut(
            breaks=[5, 11, 17, 23], # breaks into 0-5, 6-11, 12-17, 18-23
            labels=["Night", "Morning", "Afternoon", "Evening", "Night"]
            ),
        weekday_idx=pl.col("timestamp").dt.weekday()
    ).group_by(
        ["weekday", "weekday_idx", "time_range"]
    ).agg(
        total_minutes=pl.col("ms_played").sum().dt.total_minutes().round(0).cast(pl.Int64),
        total_tracks_played=pl.count("track"),
        unique_listened_tracks=pl.n_unique("track")
    ).sort(["weekday_idx", "time_range"])
    
    return result

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