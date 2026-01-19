import logging
import os
from typing import Optional, Tuple
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


def is_cloud() -> bool:
    """Detect if running on Streamlit Cloud."""
    # TODO: Extend dot env detection for other cloud providers if needed
    return os.getenv("STREAMLIT_CLOUD") == "true" or os.getenv("STREAMLIT_RUNTIME_ENV") == "cloud"


def resolve_api_key(provider: str) -> Tuple[Optional[str], str]:
    """
    Resolve API key in order: session > env.
    Returns (key, source) where source is: session | env | none
    """
    key_name = "GEMINI_API_KEY" if provider.lower() == "gemini" else "OPENAI_API_KEY"
    session_key = "gemini_api_key" if provider.lower() == "gemini" else "openai_api_key"

    # 1. Session state override
    try:
        import streamlit as st
        val = st.session_state.get(session_key)
        if val:
            logger.info(f"Resolved {key_name} from session state (user override)")
            return val, "session"
    except (ImportError, RuntimeError):
        pass

    # 2. Environment (.env / secrets already loaded into settings)
    val = settings.gemini_api_key if provider.lower() == "gemini" else settings.openai_api_key
    if val:
        logger.info(f"Resolved {key_name} from environment variables / .env")
        return val, "env"

    return None, "none"


def resolve_data_loader() -> Tuple[Optional[SpotifyDataLoader], str]:
    """
    Resolve data source in order: shared loader (session) > local folder (if not cloud).
    Returns (loader, source_description).
    """
    # 1. User uploaded / session injected
    # Priotize ST session state for uploaded data to avoid global state leakage
    try:
        import streamlit as st
        if "loader" in st.session_state and st.session_state["loader"] is not None:
            return st.session_state["loader"], "session upload"
    except (ImportError, RuntimeError):
        pass

    # 2. Local folder (only if NOT in cloud)
    if not is_cloud():
        if settings.spotify_data_path.exists():
            loader = SpotifyDataLoader(settings.spotify_data_path)
            return loader, "local filesystem"
    
    return None, "none"


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
    """Factory function to get the correct LLM using the resolver."""
    # Determine provider from session state if available, default to settings
    provider = "Gemini"
    try:
        import streamlit as st
        if "model_provider" in st.session_state:
            provider = st.session_state["model_provider"]
        else:
            provider = "Gemini" if settings.use_gemini else "OpenAI"
    except (ImportError, RuntimeError):
        provider = "Gemini" if settings.use_gemini else "OpenAI"

    api_key, _ = resolve_api_key(provider)
    
    if provider.lower() == "gemini":
        model_name = settings.gemini_model
        if not api_key:
            raise ValueError("Gemini API Key not resolved. Please provide it in the sidebar.")
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=0)
    else:
        model_name = settings.openai_model
        if not api_key:
            raise ValueError("OpenAI API Key not resolved. Please provide it in the sidebar.")
        return ChatOpenAI(model=model_name, api_key=api_key, temperature=0)


def get_resources():
    """
    Lazy initialize tools and LLM. 
    """
    global _tools_list, _llm, _tool_executor, _shared_loader
    if _tools_list is None:
        # Re-resolve loader if not already injected
        loader, source = resolve_data_loader()
        logger.info(f"Agent initializing tools with data source: {source}")
        
        _tools_list = initialize_tools(loader=loader)
        _llm = get_llm()
        _tool_executor = {tool.name: tool for tool in _tools_list}
    return _llm, _tools_list, _tool_executor
