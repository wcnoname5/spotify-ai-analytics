import logging
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from spotify_agent.tools import initialize_tools
from dataloader import SpotifyDataLoader
from config.settings import settings

logger = logging.getLogger(__name__)

# Global placeholders for lazy initialization
_tools_list = None
_llm = None
_tool_executor = None
_shared_loader: Optional[SpotifyDataLoader] = None


def inject_shared_loader(loader: SpotifyDataLoader) -> None:
    """
    Inject a pre-initialized SpotifyDataLoader instance from the UI.
    This ensures the Agent uses the same cached instance as the Dashboard.
    
    Must be called before the agent graph is invoked for the first time.
    
    Args:
        loader: SpotifyDataLoader instance (typically from st.cache_resource)
    """
    global _shared_loader
    _shared_loader = loader
    logger.info("Shared loader injected into agent utilities")
    # Reset the tools so they will be re-initialized with the new loader
    reset_resources()


def reset_resources() -> None:
    """Reset cached resources (useful for testing or re-initialization)."""
    global _tools_list, _llm, _tool_executor
    _tools_list = None
    _llm = None
    _tool_executor = None
    logger.info("Agent resources reset")


def get_llm():
    """Factory function to get the correct LLM based on settings."""
    if settings.use_gemini:
        model_name = settings.gemini_model
        api_key = settings.gemini_api_key
        logger.info(f"Using Gemini model: {model_name}")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables.")
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=0)
    else:
        model_name = settings.openai_model
        api_key = settings.openai_api_key
        logger.info(f"Using OpenAI model: {model_name}")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables.")
        return ChatOpenAI(model=model_name, api_key=api_key, temperature=0)


def get_resources():
    """
    Lazy initialize tools and LLM. 
    This prevents data loading and LLM initialization from happening 
    at module import time, allowing setup_logging() to be called first.
    """
    global _tools_list, _llm, _tool_executor, _shared_loader
    if _tools_list is None:
        _tools_list = initialize_tools(loader=_shared_loader)
        _llm = get_llm()
        _tool_executor = {tool.name: tool for tool in _tools_list}
    return _llm, _tools_list, _tool_executor
