import logging
from pathlib import Path
import pytest
import polars as pl

from spotify_agent.tools import SpotifyQueryTools, initialize_tools
from dataloader import SpotifyDataLoader

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@pytest.mark.unit
def test_initialize_tools():
    """Test the initialize_tools factory function."""
    logger.info("[Test] Testing initialize_tools function.")
    tools = initialize_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    # Verify they are LangChain tools
    for t in tools:
        assert hasattr(t, "name")
        assert hasattr(t, "invoke")

@pytest.mark.unit
def test_langgraph_compatibility(langchain_tools):
    """
    Verify that the tools are compatible with LangGraph's expectations.
    LangGraph tools should have a name, description, and be invokable.
    """
    for name, t in langchain_tools.items():
        assert t.name == name
        assert t.description is not None
        # Test if it can be bound to a model (simulated)
        assert hasattr(t, "args_schema") or hasattr(t, "_run")

@pytest.fixture
def data_loader():
    """Fixture to provide a SpotifyDataLoader instance with sample data."""
    data_path = Path(__file__).parent.parent / "data" / "spotify_history"
    # Use sample_history.json for consistent testing
    return SpotifyDataLoader(data_path, file_pattern="sample_history.json")

@pytest.fixture
def query_tools(data_loader):
    """Fixture to provide a SpotifyQueryTools instance."""
    return SpotifyQueryTools(data_loader)

@pytest.fixture
def langchain_tools(query_tools):
    """Fixture to provide LangChain tool instances."""
    tools = query_tools.get_tools()
    return {t.name: t for t in tools}

@pytest.mark.unit
def test_get_summary_stats(query_tools):
    """Test the get_summary_stats method directly."""
    result = query_tools.get_summary_stats()
    assert isinstance(result, dict)
    assert "total_records" in result
    assert "total_listening_time" in result
    assert type(result.get("total_listening_time")) == int

@pytest.mark.unit
def test_get_top_artists(query_tools):
    """Test the get_top_artists method directly."""
    result = query_tools.get_top_artists(limit=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    if len(result) > 0:
        assert "artist" in result[0]
        assert "hours_played" in result[0]

@pytest.mark.unit
def test_get_top_tracks(query_tools):
    """Test the get_top_tracks method directly."""
    result = query_tools.get_top_tracks(limit=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    if len(result) > 0:
        assert "track" in result[0]
        assert "play_count" in result[0]

@pytest.mark.unit
def test_free_aggregate(query_tools):
    """Test the free_aggregate method directly."""
    result = query_tools.free_aggregate(
        group_by=["artist"],
        metrics={"ms_played": ("sum", "total_ms")},
        limit=5
    )
    assert isinstance(result, list)
    assert len(result) <= 5
    if len(result) > 0:
        assert "artist" in result[0]
        assert "total_ms" in result[0]

@pytest.mark.unit
def test_langchain_tool_invocation(langchain_tools):
    """Verify that the tools can be invoked as LangChain tools."""
    # Test summary stats tool
    summary_tool = langchain_tools["get_summary_stats"]
    result = summary_tool.invoke({})
    assert isinstance(result, dict)
    assert "total_records" in result

    # Test top artists tool
    top_artists_tool = langchain_tools["get_top_artists"]
    result = top_artists_tool.invoke({"limit": 3})
    assert isinstance(result, list)
    assert len(result) <= 3

    top_tracks_tool = langchain_tools["get_top_tracks"]
    result = top_tracks_tool.invoke({"limit": 3,
                                     'artist': 'John Lennon'})
    assert isinstance(result, list)
    assert len(result) <= 3
    assert all('John Lennon' in rec['artist'] for rec in result)
    assert all(type(rec) is dict for rec in result)
    # free_aggregate tool
    # listening_by_time = langchain_tools["get_listening_by_time"]
    free_query_tool = langchain_tools["free_query"]
    result = free_query_tool.invoke({
        "where": "pl.col('artist') == 'The Beatles'",
        "select": ["artist", "track", "ms_played"],
        "limit": 3
    })
    assert isinstance(result, list)
    assert len(result) <= 3
    assert all(rec['artist'] == 'The Beatles' for rec in result)

    free_aggregate_tool = langchain_tools["free_aggregate"]
    result = free_aggregate_tool.invoke({
        "group_by": ["artist"],
        "metrics": {"ms_played": ("sum", "total_ms")},
        "limit": 3
    })
    assert isinstance(result, list)
    assert len(result) <= 3



@pytest.mark.unit
def test_langchain_tool_metadata(query_tools):
    """Verify that the tools have correct LangChain metadata."""
    tools = query_tools.get_tools()
    assert len(tools) == 5
    
    for t in tools:
        assert hasattr(t, "name")
        assert hasattr(t, "description")
        assert t.description is not None
        print(f"Verified LangChain tool metadata: {t.name}")
        print(f"Description: {t.description}")

if __name__ == "__main__":
    # Allow running directly with pytest
    pytest.main([__file__])
