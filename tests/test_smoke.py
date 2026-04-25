"""
Stage 0 Smoke Tests: Verify core subsystems are loadable and functional.

These tests confirm that:
1. SpotifyDataLoader can load sample data from data/spotify_history/sample_history.json
2. build_app() from spotify_agent.graph can be imported and called without raising
3. No actual LLM or network calls are made

All tests run with @pytest.mark.unit (fast, no side effects).
"""

import pytest
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

from dataloader import SpotifyDataLoader
from spotify_agent.graph import build_app

logger = logging.getLogger(__name__)


@pytest.mark.unit
def test_spotify_dataloader_loads_sample_data():
    """Test 1: Verify SpotifyDataLoader can load sample data from data/spotify_history/sample_history.json"""
    # Path to sample data relative to project root
    sample_data_path = Path(__file__).parent.parent / "data" / "spotify_history"

    # Verify sample data file exists
    assert sample_data_path.exists(), f"Sample data directory does not exist: {sample_data_path}"
    sample_file = sample_data_path / "sample_history.json"
    assert sample_file.exists(), f"Sample data file does not exist: {sample_file}"

    # Instantiate loader with sample data
    loader = SpotifyDataLoader(sample_data_path, file_pattern="sample_history.json")
    assert loader is not None, "SpotifyDataLoader failed to instantiate"

    # Verify data was loaded (lazy loading - triggers initialize_data on access)
    df = loader.df
    assert df is not None and df.height > 0, "SpotifyDataLoader failed to load sample data"

    logger.info(f"✓ Loaded {df.height} records from sample data")


@pytest.mark.unit
def test_build_app_returns_compiled_graph():
    """Test 2: Verify build_app() returns a compiled graph with callable invoke method"""
    with patch("utils.agent_utils.get_resources") as mock_get_resources:
        # Mock resources
        mock_llm = MagicMock()
        mock_tools = [MagicMock(name="test_tool")]
        mock_executor = {"test_tool": MagicMock()}

        mock_get_resources.return_value = (mock_llm, mock_tools, mock_executor)

        # Build the app
        app = build_app()

        # Verify it's a compiled LangGraph app with callable invoke method
        assert callable(getattr(app, "invoke", None)), "App missing callable invoke method"

        logger.info("✓ build_app() returns a valid compiled graph object")
