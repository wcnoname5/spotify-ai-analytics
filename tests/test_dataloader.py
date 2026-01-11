"""
Basic tests for Data Loader and project structure.
"""

import pytest
import logging
from pathlib import Path
import tempfile
import json
import shutil
import polars as pl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from dataloader import SpotifyDataLoader

@pytest.fixture
def temp_spotify_data():
    """Fixture to set up temporary test data."""
    logger.info("=" * 80)
    logger.info("Setting up test data...")
    
    # Create temporary directory with sample data
    temp_dir = tempfile.mkdtemp()
    logger.info(f"Created temporary directory: {temp_dir}")
    
    sample_data = [
        {
            "ts": "2024-01-15T08:30:00Z",
            "master_metadata_track_name": "Test Song 1",
            "master_metadata_album_artist_name": "Test Artist 1",
            "master_metadata_album_album_name": "Test Album 1",
            "ms_played": 180000,
            "spotify_track_uri": "spotify:track:001",
            "conn_country": "US",
            "platform": "Web Player",
            "reason_start": "playbtn",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False
        },
        {
            "ts": "2024-01-16T09:00:00Z",
            "master_metadata_track_name": "Another Song",
            "master_metadata_album_artist_name": "Test Artist 1",
            "master_metadata_album_album_name": "Another Album",
            "ms_played": 200000,
            "spotify_track_uri": "spotify:track:002",
            "conn_country": "US",
            "platform": "iOS",
            "reason_start": "unknown",
            "reason_end": "trackdone",
            "shuffle": False,
            "skipped": False
        },
        {
            "ts": "2024-02-10T15:30:00Z",
            "master_metadata_track_name": "Third Song",
            "master_metadata_album_artist_name": "Another Artist",
            "master_metadata_album_album_name": "Test Album 1",
            "ms_played": 150000,
            "spotify_track_uri": "spotify:track:003",
            "conn_country": "UK",
            "platform": "Android",
            "reason_start": "playbtn",
            "reason_end": "endplay",
            "shuffle": False,
            "skipped": False
        }
    ]
    
    # Write sample data to file with "Streaming" prefix for pattern matching
    sample_file = Path(temp_dir) / "Streaming_History_Audio_2024_0.json"
    with open(sample_file, 'w') as f:
        json.dump(sample_data, f)
    logger.info(f"Created sample data file with {len(sample_data)} records")
    
    yield temp_dir
    
    # Clean up test data
    logger.info("\n" + "-" * 80)
    logger.info("Cleaning up test data...")
    shutil.rmtree(temp_dir, ignore_errors=True)
    logger.info(f"✓ Removed temporary directory: {temp_dir}")

@pytest.mark.unit
def test_loader_initialization(temp_spotify_data):
    """Test 1: Can the loader be initialized?"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 1: Loader Initialization")
    logger.info("=" * 80)
    
    loader = SpotifyDataLoader(temp_spotify_data)
    logger.info("✓ SpotifyDataLoader initialized successfully")
    
    # Check if dataframe is loaded
    assert loader.df is not None, "DataFrame should not be None"
    logger.info("✓ DataFrame is not None")
    
    assert not loader.df.is_empty(), "DataFrame should not be empty"
    logger.info(f"✓ DataFrame is not empty - contains {loader.df.height} rows")
    
    # Print DataFrame info
    logger.info("\n--- Initialized DataFrame Info ---")
    logger.info(f"Shape: {loader.df.width} columns x {loader.df.height} rows")
    logger.info(f"\nColumns: {loader.df.columns}")
    
    print("\n" + "=" * 80)
    print("INITIALIZED DATAFRAME AND KEYS:")
    print("=" * 80)
    print(f"\nDataFrame Shape: {loader.df.height} rows × {loader.df.width} columns")
    for i, col in enumerate(loader.df.columns, 1):
        print(f"  {i}. {col}: datatype: {loader.df[col].dtype}")

@pytest.mark.unit
def test_get_summary(temp_spotify_data):
    """Test 2: Does get_summary work?"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: get_summary() Method")
    logger.info("=" * 80)
    
    loader = SpotifyDataLoader(temp_spotify_data)
    summary = loader.get_summary()
    
    # Validate summary structure
    required_keys = ['total_records', 'columns', 'date_range', 'unique_tracks', 'unique_artists']
    for key in required_keys:
        assert key in summary, f"Summary should contain '{key}'"
    
    assert summary['total_records'] == 3
    assert summary['unique_artists'] == 2

@pytest.mark.unit
def test_query_data(temp_spotify_data):
    """Test 3: Does query_data work?"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: query_data() Method")
    logger.info("=" * 80)
    
    loader = SpotifyDataLoader(temp_spotify_data)
    
    # Test 3a: Basic query with limit
    result = loader.query_data(limit=2)
    assert result.height == 2
    
    # Test 3b: Query with filtering
    result = loader.query_data(
        where=pl.col('artist') == 'Test Artist 1',
        select=['track', 'artist', 'ms_played']
    )
    assert result.height == 2
    assert 'track' in result.columns

@pytest.mark.unit
def test_aggregate_table(temp_spotify_data):
    """Test 4: Does aggregate_table work?"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: aggregate_table() Method")
    logger.info("=" * 80)
    
    loader = SpotifyDataLoader(temp_spotify_data)
    
    # Test 4a: Aggregate by artist - total listening time
    result = loader.aggregate_table(
        group_by=['artist'],
        metrics={'ms_played': 'sum'},
        sort_by='ms_played_sum',
        descending=True
    )
    assert result.height == 2
    assert 'ms_played_sum' in result.columns

    # Test 4b: Aggregate by artist - multiple metrics
    result = loader.aggregate_table(
        group_by=['artist'],
        metrics={
            'track': [('count', 'num_plays'), ('n_unique', 'unique_tracks')],
            'ms_played': 'sum'
        }
    )
    assert 'num_plays' in result.columns
    assert 'unique_tracks' in result.columns
    assert 'ms_played_sum' in result.columns
    assert result.height == 2

    # Test 4c: Alias collision warning (manual check of logs if needed, but here just ensure it runs)
    result = loader.aggregate_table(
        group_by=['artist'],
        metrics={
            'track': [('count', 'num_plays'), ('count', 'num_plays')]
        }
    )
    assert 'num_plays' in result.columns

@pytest.mark.unit
def test_required_files_exist():
    """Test that required files exist."""
    # TODO: Update the list below if project structure changes
    project_root = Path(__file__).parent.parent
    required_files = [
        "pyproject.toml",
        # "requirements.txt", # Uncomment if this file is used in the project
        "README.md",
        # "setup.py",
        "src/dataloader/data_loader.py",
        "src/spotify_agent/__init__.py",
        "src/spotify_agent/utils.py",
        "src/spotify_agent/state.py",
        "src/spotify_agent/tools.py",
        "src/spotify_agent/nodes.py",
        "src/spotify_agent/graph.py",
    ]
    
    for file_path in required_files:
        full_path = project_root / file_path
        assert full_path.exists(), f"{file_path} should exist"

@pytest.mark.unit
def test_sample_data_exists():
    """Test that sample data file exists."""
    project_root = Path(__file__).parent.parent
    sample_data = project_root / "data" / "spotify_history" / "sample_history.json"
    
    assert sample_data.exists(), "Sample data file should exist"
    
    with open(sample_data, 'r') as f:
        data = json.load(f)
        assert isinstance(data, list)
        assert len(data) > 0
