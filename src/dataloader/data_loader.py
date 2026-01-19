"""
Data loader module for Spotify JSON history files.
"""
import logging
import polars as pl
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
from pydantic import ValidationError
from config.settings import settings
from .models import JsonTrackRecord, Track, MONTHS, WEEKDAYS

class SpotifyDataLoader:
    """
    Loads and processes Spotify listening history from JSON files.
    The schema of the processed DataFrame matches the `Track` Pydantic model.
    See `src/dataloader/models.py` for full field definitions.
    """
    
    def __init__(
        self, 
        directory: Optional[Path] = None, 
        file_pattern: str = "Streaming*.json",
        strict_validation: bool = False,
        timezone: str = "Asia/Taipei"
    ):
        """
        Initialize the data loader.
        
        Args:
            directory: Path to directory containing Spotify JSON files. If None, uses settings.spotify_data_path.
            file_pattern: Glob pattern for files to load (default: "Streaming*.json")
            strict_validation: If True, raises ValidationError on failed sample validation.
            timezone: Timezone for timestamp conversion (default: "Asia/Taipei").
        """
        if directory is None:
            self.data_dir = settings.spotify_data_path
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
        self._is_initialized: bool = False
        # NOTE: Lazy loading - initialize_data() is called on first access via the df property

    def _get_logger(self, method_name: str):
        return logging.getLogger(f"{self._logger_prefix}.{method_name}")

    # methods to get dataframes    
    @property
    def df(self) -> Optional[pl.DataFrame]:
        """Lazy loading: initialize data on first access."""
        if not self._is_initialized:
            self.initialize_data()
            self._is_initialized = True
        return self._df
    
    @property
    def lazy(self) -> pl.LazyFrame:
        if self.df is None:  # Use the property to trigger lazy initialization
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
        # Use rglob to recursively find files matching the pattern
        json_files = list(directory.rglob(pattern))
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

