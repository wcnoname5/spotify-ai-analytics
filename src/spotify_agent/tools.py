"""
Query tools for Spotify analytics agent.
Provides structured tools for querying and aggregating listening history data.
"""
import logging
import polars as pl
from typing import Optional, Any, List, Dict
from langchain_core.tools import tool
from spotify_agent.schemas import ToolFreeQueryArgs, ToolFreeAggrgateArgs
from dataloader import SpotifyDataLoader


class SpotifyQueryTools:
    """Tools for querying Spotify listening history data."""
    # TODO: 
    # 1. add caching for frequent queries to improve performance
    # 2. Consider adding schema validation for tool inputs when transfer pl.DataFrame into dicts
    # 3. Consider adding more complex analysis tools in the future
    
    def __init__(self, data_loader: SpotifyDataLoader):
        """
        Initialize query tools with a data loader instance.
        
        Args:
            data_loader: SpotifyDataLoader instance with loaded data
        """
        self.loader = data_loader
        self._logger_prefix = (
            f"{self.__class__.__module__}."
            f"{self.__class__.__name__}"
        )

    def _get_logger(self, method_name: str):
        return logging.getLogger(f"{self._logger_prefix}.{method_name}")
    
    def _check_limit(self, limit: Optional[int]):
        """
        Check if the limit is too high for the LLM's context window.
        Large result sets can overwhelm the LLM and increase token usage.
        """
        logger = self._get_logger('_check_limit')
        if limit is not None and limit > 15:
            logger.warning(f"Large limit requested: {limit}. This may exceed the LLM's context window or increase token costs.")

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get overall listening summary statistics.
        
        Returns:
            Dictionary of listening statistics, including:
            'total_records'
            'total_listening_time' (in minutes) 
            'date_range'
            'unique_tracks'
            'unique_artists'
        """
        logger = self._get_logger('get_summary_stats')
        logger.info("Getting listening history summary statistics")
        summary = self.loader.get_summary()
        summary.pop("columns", None)  # Remove raw data from summary
        return summary
    
    def get_top_artists(self, limit: int = 5, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get top artists by listening time.
        
        Args:
            limit: Number of top artists to return (Warning: limits > 15 may overwhelm LLM context)
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)

        Returns:
            List of dictionaries containing top artists and their total listening time
        """
        logger = self._get_logger('get_top_artists')
        logger_msg = f"Getting top {limit} artists"
        if start_date: 
            logger_msg += f" from {start_date}"
        if end_date:
            logger_msg += f" to {end_date}"
        logger.info(logger_msg)
        # Check limit to avoid overwhelming LLM
        self._check_limit(limit)
        where = []
        if start_date:
            # Convert string to date for comparison
            where.append(pl.col("date") >= pl.lit(start_date).str.to_date())
        if end_date:
            where.append(pl.col("date") <= pl.lit(end_date).str.to_date())
        # Check limit to avoid overwhelming LLM
        self._check_limit(limit)
        where = []
        if start_date:
            # Convert string to date for comparison
            where.append(pl.col("date") >= pl.lit(start_date).str.to_date())
        if end_date:
            where.append(pl.col("date") <= pl.lit(end_date).str.to_date())

        result = self.loader.aggregate_table(
            group_by=["artist"],
            metrics={"ms_played": ("sum", "total_ms")},
            where=where if where else None,
            sort_by="total_ms",
            descending=True,
            limit=limit
        )
        
        return result.with_columns(
            hours_played = pl.col("total_ms").dt.total_hours().cast(pl.Int64)
        ).select(["artist", "hours_played"]).to_dicts()
    
    def get_top_tracks(self, limit: int = 5, artist: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get top tracks by play count.
        
        Args:
            limit: Number of tracks to return (Warning: limits > 15 may overwhelm LLM context)
            artist: Filter by specific artist (optional)
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)
        
        Returns:
            List of dictionaries containing top tracks
        """
        logger = self._get_logger('get_top_tracks')
        logger_msg = f"Getting top {limit} tracks"
        if artist:
            logger_msg += f" for artist: {artist}"
        if start_date:
            logger_msg += f" from {start_date}"
        if end_date:
            logger_msg += f' to {end_date}'
        logger.info(logger_msg)

        # Check limit to avoid overwhelming LLM
        self._check_limit(limit)
        where = []
        if artist:
            where.append(pl.col("artist").str.to_lowercase() == artist.lower())
        if start_date:
            # Convert string to date for comparison
            where.append(pl.col("date") >= pl.lit(start_date).str.to_date())
        if end_date:
            where.append(pl.col("date") <= pl.lit(end_date).str.to_date())
            
        result = self.loader.aggregate_table(
            group_by=["track", "artist"],
            metrics={"track": ("count", "play_count")},
            where=where,
            sort_by="play_count",
            descending=True,
            limit=limit
        )
        
        return result.to_dicts()
    
    # TODO: This funtion still need to refined its logic to fetch useful time-based patterns 
    def get_listening_by_time(self, group_by: str = "hour") -> List[Dict[str, Any]]:
        """
        Get listening patterns by time of day or month.
        
        Args:
            group_by: 'hour' for time of day, 'month' for monthly, 'weekday' for day pattern
        
        Returns:
            List of dictionaries containing listening activity by time
        """
        logger = self._get_logger('get_listening_by_time')
        valid_groups = ["hour", "month", "weekday"]
        if group_by not in valid_groups:
            group_by = "hour"
        
        result = self.loader.aggregate_table(
            group_by=[group_by],
            metrics={"ms_played": ("sum", "total_ms"), "track": ("count", "num_plays")},
            sort_by="total_ms",
            descending=True
        )
        
        return result.with_columns(
            hours_played = pl.col("total_ms").dt.total_hours().cast(pl.Int64)
        ).select([group_by, "hours_played", "num_plays"]).to_dicts()

    def free_query(self, where: Optional[str] = None, select: Optional[List[str]] = None, 
                   limit: Optional[int] = None, sort_by: Optional[str] = None, 
                   descending: bool = True) -> List[Dict[str, Any]]:
        """
        Execute a free-form query on the listening history data.
        
        Args:
            where: Polars filter expression as a string
            select: List of column names to include
            limit: Maximum number of rows to return
            sort_by: Column name to sort by
            descending: Whether to sort in descending order
        Returns:
            List of dictionaries containing the query results
        Example Useage:
        {
            "where": "pl.col('artist') == 'The Beatles'",
            "select": ["artist", "track", "ms_played"],
             "limit": 3
            }
        """
        logger = self._get_logger('free_query')
        logger.info(f"Executing free query with where: {where}, select: {select}, limit: {limit}")
        self._check_limit(limit)
        
        where_expr = None
        if where:
            try:
                # Safely evaluate the string as a Polars expression
                where_expr = eval(where, {"pl": pl})
            except Exception as e:
                logger.error(f"Error evaluating where expression: {e}")
                raise ValueError(f"Invalid filter expression: {where}")

        result = self.loader.query_data(
            where=where_expr,
            select=select,
            limit=limit,
            sort_by=sort_by,
            descending=descending
        )
        return result.to_dicts()

    def free_aggregate(self, group_by: List[str], metrics: Dict[str, Any], 
                       where: Optional[str] = None, sort_by: Optional[str] = None, 
                       descending: bool = True, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Perform a free-form aggregation on the listening history data.
        
        WARNING: This tool may be deprecated in the future in favor of more specific tools.
        
        Args:
            group_by: List of columns to group by
            metrics: Dictionary of metrics to compute
            where: Optional filter condition as a string
            sort_by: Column to sort results by
            descending: Sort order
            limit: Limit number of results
        Returns:
            List of dictionaries containing aggregated results
        Example Useage:
            {group_by = ["artist"],
            metrics = {"ms_played": ("sum", "total_ms")},
            where = "pl.col('date') >= pl.lit('2023-01-01').str.to_date()",
            sort_by = "total_ms",
            descending = True,
            }
        """ 
        logger = self._get_logger('free_aggregate')
        logger.info(f"Executing free aggregate with group_by: {group_by}, metrics: {metrics}, limit: {limit}")
        self._check_limit(limit)
        
        where_expr = None
        if where:
            try:
                where_expr = eval(where, {"pl": pl})
            except Exception as e:
                logger.error(f"Error evaluating where expression: {e}")
                raise ValueError(f"Invalid filter expression: {where}")

        # Convert metrics if they are lists (representing tuples from JSON/LLM)
        processed_metrics = {}
        for col, spec in metrics.items():
            if isinstance(spec, list) and len(spec) == 2:
                processed_metrics[col] = tuple(spec)
            else:
                processed_metrics[col] = spec

        result = self.loader.aggregate_table(
            group_by=group_by,
            metrics=processed_metrics,
            where=where_expr,
            sort_by=sort_by,
            descending=descending,
            limit=limit
        )
        return result.to_dicts()

    def get_tools(self):
        """Return all tools for integration with LangGraph agent."""
        return [
            tool(self.get_summary_stats),
            tool(self.get_top_artists),
            tool(self.get_top_tracks),
            # tool(self.get_listening_by_time), # Disabled for now to reduce toolset size for now
            tool(self.free_query, args_schema=ToolFreeQueryArgs),
            tool(self.free_aggregate, args_schema=ToolFreeAggrgateArgs)
        ]

# --- The Instantiation Part (Run this once) ---
# Ideally, load your data here or in a config file
# If data loading is heavy, do this inside a "initialize_tools" function

def initialize_tools(loader: Optional[SpotifyDataLoader] = None):
    """
    Factory function to create the toolset.
    
    Args:
        loader: Optional SpotifyDataLoader instance. If provided, uses it instead of creating new.
                This allows sharing a cached loader from the UI with the Agent.
    
    Returns:
        List of LangChain tools.
    """
    from config.settings import settings
    
    logger = logging.getLogger(f'{__name__}.initialize_tools')
    
    # If loader is provided (injected), use it
    if loader is not None:
        logger.info("Using injected SpotifyDataLoader instance")
        tool_service = SpotifyQueryTools(loader)
        return tool_service.get_tools()
    
    # Otherwise, create a new instance (original behavior for CLI/scripts)
    data_path = settings.spotify_data_path
    logger.info(f"Initializing SpotifyQueryTools with data path: {data_path}")

    # 1. Load Data
    loader = SpotifyDataLoader(data_path)
    
    # 2. Init Service
    tool_service = SpotifyQueryTools(loader)
    
    # 3. Return the list of callable tools
    return tool_service.get_tools()
