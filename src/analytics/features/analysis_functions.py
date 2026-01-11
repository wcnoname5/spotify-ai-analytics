import polars as pl
from typing import Literal, Optional, Dict, TypedDict
from datetime import date
from utils.data_loader import SpotifyDataLoader

class SummaryStats(TypedDict):
    total_records: int
    total_listening_time: int  # in minutes
    columns: list[str]
    date_range: Optional[Dict[str, str]]  # {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'}
    unique_tracks: int
    unique_artists: int
    

def get_summary_by_time(
    loader: SpotifyDataLoader,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
)-> SummaryStats:
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
            'unique_tracks': 0,
            'unique_artists': 0
        }

    # Perform calculations in a single selection for optimal performance
    metrics = []
    if 'ms_played' in df.columns:
        metrics.append(pl.col('ms_played').sum().dt.total_minutes().alias('total_min'))
    if 'date' in df.columns:
        metrics.extend([
            pl.col('date').min().alias('start_date'),
            pl.col('date').max().alias('end_date')
        ])
    if 'track_uri' in df.columns:
        metrics.append(pl.col('track_uri').n_unique().alias('unique_tracks'))
    if 'artist' in df.columns:
        metrics.append(pl.col('artist').n_unique().alias('unique_artists'))

    results = df.select(metrics).to_dicts()[0]

    return {
        'total_records': df.height,
        'total_listening_time': int(results.get('total_min') or 0),
        'columns': list(df.columns),
        'date_range': {
            'start': str(results['start_date']),
            'end': str(results['end_date'])
        } if results.get('start_date') else None,
        'unique_tracks': int(results.get('unique_tracks', 0)),
        'unique_artists': int(results.get('unique_artists', 0))
    }


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