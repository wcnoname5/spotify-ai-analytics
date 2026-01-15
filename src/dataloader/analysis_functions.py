import polars as pl
import logging
from typing import Literal, Optional, Dict, TypedDict, Any, List, Union
from datetime import date

logger = logging.getLogger(__name__)

class SummaryStats(TypedDict):
    total_records: int
    total_listening_time: int  # in minutes
    columns: list[str]
    date_range: Optional[Dict[str, str]]  # {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'}
    unique_tracks: int
    unique_artists: int

def query_data(
    df: pl.DataFrame|pl.LazyFrame,
    where: Optional[Union[pl.Expr, List[pl.Expr]]] = None,
    select: Optional[List[str]] = None,
    limit: Optional[int] = None,
    sort_by: Optional[str] = None,
    descending: bool = True
) -> pl.DataFrame:
    """
    Query the Spotify listening history data with filtering, selection, and sorting.
    """
    if df is None or df.is_empty():
        return pl.DataFrame()

    if where is not None:
        if isinstance(where, list):
            if where:
                df = df.filter(pl.all_horizontal(where))
        else:
            df = df.filter(where)

    if select is not None:
        df = df.select(select)

    if sort_by is not None:
        df = df.sort(sort_by, descending=descending)

    if limit is not None:
        df = df.head(limit)

    return df

def aggregate_table(
    df: pl.DataFrame,
    group_by: List[str],
    metrics: Dict[str, Any],
    where: Optional[Union[pl.Expr, List[pl.Expr]]] = None,
    sort_by: Optional[str] = None,
    descending: bool = True,
    limit: Optional[int] = None,
) -> pl.DataFrame:
    """
    Aggregate the data by grouping and applying metrics.
    """
    if df is None or df.is_empty():
        return pl.DataFrame()

    # Apply filters
    if where is not None:
        if isinstance(where, list):
            if where:
                df = df.filter(pl.all_horizontal(where))
        else:
            df = df.filter(where)

    # Build aggregation expressions
    agg_exprs_dict = {}

    for col, agg_func_specs in metrics.items():
        # Normalize to list of specs for uniform processing
        if not isinstance(agg_func_specs, list):
            specs = [agg_func_specs]
        else:
            specs = agg_func_specs

        for spec in specs:
            # Handle tuple format: (function, custom_alias)
            if isinstance(spec, tuple):
                func, custom_alias = spec
            else:
                func = spec
                custom_alias = None
            
            # Determine alias name
            alias_name = custom_alias if custom_alias else f"{col}_{func}"
            
            # Build aggregation expression
            if func == "sum":
                expr = pl.sum(col).alias(alias_name)
            elif func == "mean":
                expr = pl.mean(col).alias(alias_name)
            elif func == "count":
                expr = pl.count(col).alias(alias_name)
            elif func == "n_unique":
                expr = pl.n_unique(col).alias(alias_name)
            else:
                raise ValueError(f"Unsupported aggregation: {func}")
            
            agg_exprs_dict[alias_name] = expr

    result = df.group_by(group_by).agg(list(agg_exprs_dict.values()))

    if sort_by is not None:
        result = result.sort(sort_by, descending=descending)

    if limit is not None:
        result = result.head(limit)

    return result

def get_summary(
    df: pl.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> SummaryStats:
    """
    Get summary statistics for listening history.
    """
    filters = []
    if start_date:
        filters.append(pl.col("date") >= start_date)
    if end_date:
        filters.append(pl.col("date") <= end_date)
    
    df_filtered = query_data(df, where=filters)

    if df_filtered is None or df_filtered.is_empty():
        return {
            'total_records': 0,
            'total_listening_time': 0,
            'columns': list(df.columns) if df is not None else [],
            'date_range': None,
            'unique_tracks': 0,
            'unique_artists': 0
        }

    # Perform calculations in a single selection for optimal performance
    metrics = []
    if 'ms_played' in df_filtered.columns:
        metrics.append(pl.col('ms_played').sum().dt.total_minutes().alias('total_min'))
    if 'date' in df_filtered.columns:
        metrics.extend([
            pl.col('date').min().alias('start_date'),
            pl.col('date').max().alias('end_date')
        ])
    if 'track_uri' in df_filtered.columns:
        metrics.append(pl.col('track_uri').n_unique().alias('unique_tracks'))
    elif 'track' in df_filtered.columns:
        metrics.append(pl.col('track').n_unique().alias('unique_tracks'))

    if 'artist' in df_filtered.columns:
        metrics.append(pl.col('artist').n_unique().alias('unique_artists'))

    results = df_filtered.select(metrics).to_dicts()[0]

    return {
        'total_records': df_filtered.height,
        'total_listening_time': int(results.get('total_min') or 0),
        'columns': list(df_filtered.columns),
        'date_range': {
            'start': str(results['start_date']),
            'end': str(results['end_date'])
        } if results.get('start_date') else None,
        'unique_tracks': int(results.get('unique_tracks', 0)),
        'unique_artists': int(results.get('unique_artists', 0))
    }

def get_top_artists(
    df: pl.DataFrame,
    k: int = 5,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get top k artists by total listening time in minutes.
    """
    filters = []
    if start_date:
        filters.append(pl.col("date") >= start_date)
    if end_date:
        filters.append(pl.col("date") <= end_date)
        
    result = aggregate_table(
        df,
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
    df: pl.DataFrame,
    k: int = 5,
    artist: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get top k tracks by total listening time in minutes.
    """
    where = []
    if artist:
        where.append(pl.col("artist").str.to_lowercase() == artist.lower())
    if start_date:
        where.append(pl.col("date") >= start_date)
    if end_date:
        where.append(pl.col("date") <= end_date)
        
    result = aggregate_table(
        df,
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
    df: pl.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get monthly listening trend (total listening time per month).
    """
    where = []
    if start_date:
        where.append(pl.col("date") >= start_date)
    if end_date:
        where.append(pl.col("date") <= end_date)

    result = aggregate_table(
        df,
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

def get_weekly_listening_trend(
    df: pl.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> pl.DataFrame:
    """
    Get weekly and daytime listening trend
    grouped by daytime (Night, Morning, Afternoon, Evening)
    """
    where = []
    if start_date:
        where.append(pl.col("date") >= start_date)
    if end_date:
        where.append(pl.col("date") <= end_date)
    
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

def get_raw_df(df: pl.DataFrame,
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

    return query_data(
        df,
        where=filters if filters else None,
        limit=limit
    )
