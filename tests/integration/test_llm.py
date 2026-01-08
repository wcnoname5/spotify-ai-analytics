import pytest
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from spotify_agent.utils import get_llm

@pytest.mark.llm
def test_llm_connection():
    """Test connection to the configured LLM."""
    llm = get_llm()
    logger.info("Invoking LLM with 'hi'...")
    response = llm.invoke("hi")
    logger.info(f"Response: {response.content}")
    assert response.content is not None
    assert len(response.content) > 0
