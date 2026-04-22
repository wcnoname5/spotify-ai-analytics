"""
Initialization utilities for the Spotify AI Agent.

This module manages the lifecycle of core resources:
1. LLM (OpenAI/Gemini)
2. Tools (Data Querying)
3. DataLoader (Spotify History)

ARCHITECTURE:
To support multi-user deployments (Streamlit Cloud), this module uses a 
'Session-aware Singleton' pattern. Resources are cached in `st.session_state` 
to ensure User A never uses User B's API key or data.

A fallback mechanism uses module-level globals for Non-Streamlit 
environments (CLI tools, Unit Tests).
"""

import logging
import os
import hashlib
from typing import Optional, Tuple
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
import google.generativeai as genai
from openai import OpenAI, AuthenticationError, APIConnectionError
from spotify_agent.tools import initialize_tools
from dataloader import SpotifyDataLoader
from config.settings import settings

logger = logging.getLogger(__name__)

# Fallback placeholders for non-Streamlit environments (tests/CLI)
# DO NOT use these for multi-user web apps.
_local_tools_list = None
_local_llm = None
_local_tool_executor = None
_local_shared_loader: Optional[SpotifyDataLoader] = None


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
    Resolve data source in order: session state > injected/local fallback.
    Returns (loader, source_description).
    """
    # 1. User uploaded / session injected (Priority)
    try:
        import streamlit as st
        # Directly use session state if available
        if "loader" in st.session_state and st.session_state["loader"] is not None:
            return st.session_state["loader"], "session"
    except (ImportError, RuntimeError):
        pass

    # 2. Local fallback / Injected (for testing/CLI)
    if _local_shared_loader is not None:
        return _local_shared_loader, "injected_fallback"

    # 3. Local filesystem (last resort)
    if settings.spotify_data_path.exists():
        loader = SpotifyDataLoader(settings.spotify_data_path)
        return loader, "filesystem"
    
    return None, "none"


def inject_shared_loader(loader: SpotifyDataLoader) -> None:
    """
    Inject a SpotifyDataLoader instance. 
    In Streamlit, this is stored in session state. 
    In CLI, it uses a local global to store it.
    """
    try:
        import streamlit as st
        st.session_state["loader"] = loader
        logger.info("Loader injected into Streamlit session state")
    except (ImportError, RuntimeError):
        global _local_shared_loader
        _local_shared_loader = loader
        logger.info("Loader injected into local global (Non-ST)")
        
    # Always reset resources to ensure the new loader is picked up
    reset_resources()


def validate_api_key(provider: str, api_key: str) -> str:
    """
    Validate the API key by listing models. Returns 'valid', 'invalid', or 'network_error'.
    Caches results in st.session_state using a hash of the key.
    """
    if not api_key:
        return "invalid"

    # Quick hash for caching
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    cache_key = f"auth_cache_{provider.lower()}_{key_hash}"

    try:
        import streamlit as st
        if cache_key in st.session_state:
            return st.session_state[cache_key]
    except (ImportError, RuntimeError):
        pass

    status = "invalid"
    # Validate API key using provider SDKs
    try:
        if provider.lower() == "gemini":
            genai.configure(api_key=api_key)
            # Try to list models - minimal impact
            next(iter(genai.list_models()), None)
            status = "valid"
        elif provider.lower() == "openai":
            client = OpenAI(api_key=api_key)
            client.models.list()
            status = "valid"
    except (AuthenticationError, ValueError):
        status = "invalid"
    except APIConnectionError:
        status = "network_error"
    except Exception as e:
        error_str = str(e).lower()
        # Heuristic for network issues in other SDKs (like Gemini)
        if any(term in error_str for term in ["timeout", "connection", "dns", "unreachable", "network", "deadline", "getaddrinfo"]):
            logger.error(f"Potential network error validating {provider} key: {e}")
            status = "network_error"
        # Gemini specific invalid key usually manifests as InvalidArgument or 400
        elif any(term in error_str for term in ["invalid", "api key", "400", "not found"]):
            status = "invalid"
        else:
            logger.error(f"{provider} API Key validation failed: {e}")
            status = "invalid"

    # Save to session cache
    try:
        import streamlit as st
        st.session_state[cache_key] = status
    except (ImportError, RuntimeError):
        pass

    return status


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

    api_key, source = resolve_api_key(provider)
    
    if provider.lower() == "gemini":
        model_name = settings.gemini_model
        if not api_key:
            logger.warning(f"Gemini API Key missing (Provider selected, but no key in {source})")
            return None
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=0)
    else:
        model_name = settings.openai_model
        if not api_key:
            logger.warning(f"OpenAI API Key missing (Provider selected, but no key in {source})")
            return None
        return ChatOpenAI(model=model_name, api_key=api_key, temperature=0)


def get_resources():
    """
    Lazy initialize tools and LLM with session-based caching.
    Ensures user isolation in multi-user environments.
    """
    try:
        import streamlit as st
        # Resolve from session state
        llm = st.session_state.get("agent_llm")
        tools = st.session_state.get("agent_tools")
        executor = st.session_state.get("agent_executor")
        
        if llm is None or tools is None:
            loader, source = resolve_data_loader()
            logger.info(f"Re-initializing agent resources (Session) - Source: {source}")
            
            tools = initialize_tools(loader=loader)
            llm = get_llm()
            executor = {tool.name: tool for tool in tools}
            
            st.session_state["agent_llm"] = llm
            st.session_state["agent_tools"] = tools
            st.session_state["agent_executor"] = executor
            
        return llm, tools, executor

    except (ImportError, RuntimeError):
        # Fallback for non-Streamlit environments
        global _local_tools_list, _local_llm, _local_tool_executor
        
        if _local_tools_list is None or _local_llm is None:
            loader, source = resolve_data_loader()
            logger.info(f"Re-initializing agent resources (Local) - Source: {source}")
            
            _local_tools_list = initialize_tools(loader=loader)
            _local_llm = get_llm()
            _local_tool_executor = {tool.name: tool for tool in _local_tools_list}
            
        return _local_llm, _local_tools_list, _local_tool_executor


def reset_resources() -> None:
    """
    Reset cached resources to trigger re-initialization.
    Crucial when switching API keys or data sources.
    """
    try:
        import streamlit as st
        for key in ["agent_llm", "agent_tools", "agent_executor", "agent_app"]:
            if key in st.session_state:
                del st.session_state[key]
        logger.info("Streamlit agent resources reset")
    except (ImportError, RuntimeError):
        global _local_tools_list, _local_llm, _local_tool_executor
        _local_tools_list = None
        _local_llm = None
        _local_tool_executor = None
        logger.info("Local agent resources reset")
