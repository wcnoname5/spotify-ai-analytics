import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from utils.loggings import setup_logging

def pytest_configure(config):
    """Setup logging for the entire pytest session."""
    setup_logging(mode="test", log_name="pytest_session")

@pytest.fixture(scope="function", autouse=True)
def initialize_logging(request):
    """Setup logging for integration tests with specific filenames."""
    # Check if 'integration' marker is present
    if "integration" in request.node.keywords:
        test_file_name = Path(request.node.fspath).stem
        setup_logging(mode="test", log_name=test_file_name)

@pytest.fixture
def mock_llm_chain():
    """
    Fixture to mock LLM calls in nodes.
    Usage:
        def test_my_node(mock_llm_chain):
            mock_llm_chain.invoke.return_value = AIMessage(content="...")
    """
    # Import inside fixture to avoid premature initialization or side effects
    import utils.agent_utils as agent_utils
    
    # 1. Patch get_llm in the utils module 
    with patch("utils.agent_utils.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # 2. Reset the internal cache in utils.py to force re-initialization 
        agent_utils._tools_list = None
        agent_utils._llm = None
        agent_utils._tool_executor = None
        
        # Also mock initialize_tools to ensure we have a consistent toolset for tests
        with patch("utils.agent_utils.initialize_tools") as mock_init_tools:
            mock_tool = MagicMock()
            mock_tool.name = "get_top_artists"
            mock_init_tools.return_value = [mock_tool]
            
            yield mock_llm
