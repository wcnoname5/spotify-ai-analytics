"""
Data loader module for Spotify JSON history files.
"""
import logging
import polars as pl
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
from pydantic import ValidationError
from config.settings import PROJECT_ROOT
from .models import JsonTrackRecord, Track, MONTHS, WEEKDAYS

class SpotifyDataLoader:
    """
    Loads and processes Spotify listening history from JSON files.
    The schema of the processed DataFrame matches the `Track` Pydantic model.
    See `src/dataloader/models.py` for full field definitions.
    """
    
    def __init__(
        self, 
        directory: Path, 
        file_pattern: str = "Streaming*.json",
        strict_validation: bool = False,
        timezone: str = "Asia/Taipei"
    ):
        """
        Initialize the data loader.
        
        Args:
            directory: Path to directory containing Spotify JSON files
            file_pattern: Glob pattern for files to load (default: "Streaming*.json")
            strict_validation: If True, raises ValidationError on failed sample validation.
            timezone: Timezone for timestamp conversion (default: "Asia/Taipei").
        """
        # Resolve path relative to PROJECT_ROOT if it's not absolute
        if not Path(directory).is_absolute():
            self.data_dir = (PROJECT_ROOT / directory).resolve()
        else:
            self.data_dir = Path(directory).resolve()
            
        self.file_pattern = file_pattern
        self.strict_validation = strict_validation
        self.timezone = timezone

        # intialize logging pattern
        self._logger_prefix = (
            f"{self.__class__.__module__}."
            f"{self.__class__.__name__}"
        )
        # initialize df
        self._df: pl.DataFrame | None = None
        self.initialize_data()

    def _get_logger(self, method_name: str):
        return logging.getLogger(f"{self._logger_prefix}.{method_name}")

    # methods to get dataframes    
    @property
    def df(self) -> Optional[pl.DataFrame]:
        # TODO: can use cache in future improvements?
        return self._df
    
    @property
    def lazy(self) -> pl.LazyFrame:
        if self._df is None:
            raise RuntimeError("Data not loaded")
        return self._df.lazy()

    def initialize_data(self) -> None:
        """
        Process raw JSON data into a structured Polars DataFrame.
        """
        logger = self._get_logger('initialize_data')
        logger.info("Processing raw JSON data into structured DataFrame")
        df = self._read_json_files(self.data_dir, self.file_pattern)
        if df.is_empty():
            self._df = pl.DataFrame()
        else:
            self._df = self._preprocess(df)
    
    def _read_json_files(self, directory: Path, pattern: str = "Streaming*.json") -> pl.DataFrame:
        """Read JSON files in a directory matching the pattern into a Polars DataFrame."""
        logger = self._get_logger('_read_json_files')
        json_files = list(directory.glob(pattern))
        logger.info(f"Found {len(json_files)} JSON files matching '{pattern}' in {directory}")
        if not json_files:
            logger.warning(f"No JSON files found in {directory}")
            return pl.DataFrame()
        else:
            dfs = []
            for file in json_files:
                try:
                    # Increase infer_schema_length to handle mixed data types
                    df = pl.read_json(file, infer_schema_length=10000)
                    dfs.append(df)
                    logger.info(f"Loaded {file.name}: {df.height} records")
                except Exception as e:
                    logger.error(f"Failed to load {file.name}: {e}")
                    continue
            
            if not dfs:
                logger.warning("No valid JSON files could be loaded")
                return pl.DataFrame()
            
            combined_df = pl.concat(dfs, how="diagonal_relaxed")  # Use diagonal_relaxed for mismatched schemas
            logger.info(f"Total {combined_df.height} records loaded.")
            return combined_df

    def _preprocess(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Normalize Spotify history to the standard schema with staged validation.
        """
        logger = self._get_logger('_preprocess')
        initial_count = df.height
        logger.info(f"Starting preprocessing of {initial_count} raw records")

        # --- Stage 1: Cleanup & Raw Validation ---
        working_df = df
        if "ms_played" not in working_df.columns and "msPlayed" in working_df.columns:
            working_df = working_df.rename({"msPlayed": "ms_played"})
        
        # Validate raw data sample
        if not working_df.is_empty():
            # Filter non-nulls for raw validation sample
            raw_sample_pool = working_df.filter(pl.col("master_metadata_track_name").is_not_null())
            self._validate_sample(raw_sample_pool, JsonTrackRecord, sample_size=10)

        # --- Stage 2: Filtering ---
        logger.info("Filtering records: removing null tracks and zero playtime")
        working_df = working_df.filter(
            (pl.col("master_metadata_track_name").is_not_null()) &
            (pl.col("ms_played") > 0)
        )
        filtered_count = working_df.height
        logger.info(f"Filtered records: {initial_count} -> {filtered_count} (Dropped {initial_count - filtered_count})")

        # --- Stage 3: Transformation ---
        # Note: timezone conversion is configurable via self.timezone
        processed_df = (
            working_df
            .select([
                pl.col("ts").str.strptime(
                        pl.Datetime,
                        format="%+"
                    ).dt.replace_time_zone(
                        "UTC"
                    ).dt.convert_time_zone(
                        self.timezone
                    ).alias("timestamp"),
                pl.col("ts").cast(pl.Utf8).alias("ts"), 
                pl.col("ms_played").cast(pl.Duration("ms")),
                pl.col("master_metadata_track_name").alias("track"),
                pl.col("master_metadata_album_artist_name").alias("artist"),
                pl.col("master_metadata_album_album_name").alias("album"),
                pl.col("spotify_track_uri").alias("track_uri"),
                pl.col("conn_country"),
                pl.col("platform"),
                pl.col("reason_start"),
                pl.col("reason_end"),
                pl.col("shuffle"),
                pl.col("skipped")
            ])
            .with_columns(
                year = pl.col("timestamp").dt.year(),
                # Use pl.Enum for month and weekday for:
                # 1. Memory Efficiency: Stores as integers internally, strings only for display.
                # 2. Performance: Faster grouping, filtering, and sorting than strings.
                # 3. Logical Sorting: Ensures 'Jan' < 'Feb' and 'Mon' < 'Tue' instead of alphabetical.
                # 4. Data Integrity: Strictly enforces that only values in our constants are allowed.
                month = pl.col("timestamp").dt.strftime("%b").cast(pl.Enum(MONTHS)), 
                weekday = pl.col("timestamp").dt.strftime("%a").cast(pl.Enum(WEEKDAYS)),
                hour = pl.col("timestamp").dt.hour(),
                date = pl.col("timestamp").dt.date(),
            )
        )

        # --- Stage 4: Processed Validation ---
        if not processed_df.is_empty():
            self._validate_sample(processed_df, Track, sample_size=10)
                
        logger.info("Preprocessing complete")
        return processed_df
    
    # Validation helper
    def _validate_sample(self, df: pl.DataFrame, model_class: Any, sample_size: int = 1):
        """
        Validate a sample of the data against a Pydantic model.
        
        Args:
            df: Polars DataFrame to sample from
            model_class: Pydantic model class to validate against
            sample_size: Number of records to sample (default: 10)
        """
        logger = self._get_logger('_validate_sample')
        if df.is_empty():
            return

        # Take a sample (use head if df is small, otherwise sample)
        sample_df = df.head(sample_size) if df.height <= sample_size else df.sample(n=sample_size)
        records = sample_df.to_dicts()
        
        errors = []
        for i, record in enumerate(records):
            try:
                model_class.model_validate(record)
            except ValidationError as e:
                # Capture the first few errors for the log
                error_details = e.errors()[0]
                msg = f"Row {i} | Field: {error_details['loc']} | Error: {error_details['msg']}"
                errors.append(msg)
        
        if errors:
            err_msg = f"Validation failed for {model_class.__name__} in {len(errors)}/{len(records)} sampled rows:\n" + "\n".join(errors[:5])
            if self.strict_validation:
                logger.error(err_msg)
                raise ValidationError(err_msg)
            else:
                logger.warning(err_msg)
        else:
            logger.info(f"Successfully validated {len(records)} rows against {model_class.__name__}")


    # Methods:
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the loaded data.
        should consider how to merge with `get_summary_by_time` in analysis_functions in the future:
        problem: start_date and end_date type should be date or string
            - LLM may fit latter
        """
        if self._df is None or self._df.is_empty():
            return {
                'total_records': 0,
                'total_listening_time': 0,
                'columns': [],
                'date_range': None,
                'unique_tracks': None,
                'unique_artists': None
            }

        summary = {
            'total_records': self._df.height, # total listening records
            'total_listening_time': 0, # in minutes
            'columns': list(self._df.columns), 
            'date_range': None, # start and end dates{'start': ..., 'end': ...}
            'unique_tracks': None,
            'unique_artists': None
        }
        if 'ms_played' in self._df.columns:
            # Use Polars duration methods for unit conversion
            total_minutes = self._df.select(
                pl.col('ms_played').sum().dt.total_minutes()
            ).item()
            summary['total_listening_time'] = int(total_minutes)

        if 'date' in self._df.columns:
            arr = self._df.select(pl.col('date')).to_series()
            summary['date_range'] = {
                'start': str(arr.min()),
                'end': str(arr.max())
            }

        track_identifier = 'track_uri' # use track URI for uniqueness ()
        if track_identifier:
            summary['unique_tracks'] = int(self._df.select(pl.col(track_identifier).n_unique()).item())

        artist_col_name = 'artist'
        if artist_col_name:
            summary['unique_artists'] = int(self._df.select(pl.col(artist_col_name).n_unique()).item())

        return summary


    def query_data(self,
        where: pl.Expr | list[pl.Expr] | None = None,
        select: list[str] | None = None,
        limit: int | None = None,
        sort_by: str | None = None,
        descending: bool = True
    ) -> pl.DataFrame:
        """
        Query the Spotify listening history data with filtering, selection, and sorting.
        
        Args:
            where: Polars expression(s) to filter the data. Can be a single expression or
                a list of expressions (combined with AND logic).
                Examples:
                    - Single expression: pl.col('artist') == 'Taylor Swift'
                    - List of expressions: [pl.col('year') == 2023, pl.col('ms_played') > pl.duration(seconds=30)]
                    - Comparison: pl.col('ms_played') > pl.duration(seconds=60)
                    - String matching: pl.col('track').str.contains('love')
                    - Date filtering: pl.col('year').is_in([2023, 2024])
            select: List of column names to include in result. If None, returns all columns.
                Example: ['track', 'artist', 'ms_played']
            limit: Maximum number of rows to return. If None, returns all rows.
            sort_by: Column name to sort by. If None, maintains original order.
            descending: If True, sort in descending order. Default is True.
        
        Returns:
            Polars DataFrame with filtered, selected, and sorted data.
        """

        if self._df is None or self._df.is_empty():
            return pl.DataFrame()

        df = self._df

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
        self,
        group_by: list[str],
        metrics: dict[str, Literal["sum", "mean", "count", "n_unique"] | tuple[Literal["sum", "mean", "count", "n_unique"], str] | list[Literal["sum", "mean", "count", "n_unique"] | tuple[Literal["sum", "mean", "count", "n_unique"], str]]],
        where=None,
        sort_by=None,
        descending=True,
        limit=None,
    ) -> pl.DataFrame:
        """
        Aggregate the data by grouping and applying metrics.
        
        Args:
            group_by: List of column names to group by.
                Example: ['artist'] or ['year', 'month']
            metrics: Dictionary mapping column names to aggregation functions.
                Supported functions: 'sum', 'mean', 'count', 'n_unique'
                Value can be either:
                    - String: Uses default naming pattern (e.g., 'sum' -> 'column_sum')
                    - Tuple: (function, custom_alias) for custom column naming
                    - List: A list of the above (string or tuple) for multiple metrics on same column
                Examples:
                    - Default: {'ms_played': 'sum', 'track': 'n_unique'}
                    - Custom: {'ms_played': ('sum', 'total_time')}
                    - Multiple: {'track': [('count', 'num_plays'), ('n_unique', 'unique_tracks')]}
                    - Mixed: {'ms_played': ('sum', 'listening_time'), 'track': 'n_unique'}
            where: Polars expression(s) to filter data before aggregation.
                Can be a single expression or list of expressions.
                Examples:
                    - Single: pl.col('year') == 2023
                    - List: [pl.col('year') == 2023, pl.col('ms_played') > pl.duration(seconds=30)]
                    - String matching: pl.col('platform').is_in(['iOS', 'Android'])
            sort_by: Column name in the result to sort by.
            descending: If True, sort in descending order. Default is True.
            limit: Maximum number of rows in result.
        
        Returns:
            Polars DataFrame with aggregated results.
        """

        if self._df is None or self._df.is_empty():
            return pl.DataFrame()

        df = self._df

        # Apply filters
        if where is not None:
            if isinstance(where, list):
                if where: # if not empty list
                    df = df.filter(pl.all_horizontal(where))
            else:
                df = df.filter(where)

        # Build aggregation expressions
        agg_exprs_dict = {}
        logger = self._get_logger('aggregate_table')

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
                
                # Check for alias collisions
                if alias_name in agg_exprs_dict:
                    logger.warning(f"Alias collision detected: '{alias_name}' already exists. Overwriting previous expression.")
                
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


    def create_text_documents(self) -> List[str]:
        """
        Create text documents for RAG indexing.
        deprecating
        """
        if self._df is None:
            self.initialize_data()
        if self._df is None or self._df.is_empty():
            return []

        documents: List[str] = []

        for row in self._df.iter_rows(named=True):
            track = row.get('track', 'Unknown Track')
            artist = row.get('artist', 'Unknown Artist')
            album = row.get('album', None)
            timestamp = row.get('timestamp')
            duration = row.get('ms_played', 0)

            doc_text = f"Track: {track} by {artist}"
            if album:
                doc_text += f" from album {album}"
            if timestamp:
                doc_text += f" played on {timestamp}"
            if duration:
                # duration is a timedelta object if it's a Duration column
                doc_text += f" for {duration}"

            documents.append(doc_text)

        return documents

    # This method seems can be replaced by property df
    def get_listening_history_df(self) -> pl.DataFrame:
        """Return the processed listening history DataFrame."""
        return self._df if self._df is not None else pl.DataFrame()
