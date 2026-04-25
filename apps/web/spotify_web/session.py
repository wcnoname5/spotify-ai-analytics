"""Streamlit session wrapper for agent resources."""
import logging
import hashlib
from typing import Optional, Tuple
import streamlit as st
from spotify_core.config import settings
from spotify_core.agent.resources import build_llm, build_resources
from spotify_core.agent.graph import build_app
from spotify_dataloader import SpotifyDataLoader

logger = logging.getLogger(__name__)

def resolve_api_key(provider: str) -> Tuple[Optional[str], str]:
    session_key = "gemini_api_key" if provider.lower() == "gemini" else "openai_api_key"
    try:
        val = st.session_state.get(session_key)
        if val:
            return val, "session"
    except (ImportError, RuntimeError):
        pass
    val = settings.gemini_api_key if provider.lower() == "gemini" else settings.openai_api_key
    if val:
        return val, "env"
    return None, "none"

def resolve_data_loader() -> Tuple[Optional[SpotifyDataLoader], str]:
    try:
        loader = st.session_state.get("loader")
        if loader is not None:
            return loader, "session"
    except (ImportError, RuntimeError):
        pass
    if settings.spotify_data_path.exists():
        return SpotifyDataLoader(settings.spotify_data_path), "filesystem"
    return None, "none"

def inject_shared_loader(loader: SpotifyDataLoader) -> None:
    try:
        st.session_state["loader"] = loader
    except (ImportError, RuntimeError):
        pass
    reset_resources()

def validate_api_key(provider: str, api_key: str) -> str:
    if not api_key:
        return "invalid"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    cache_key = f"auth_cache_{provider.lower()}_{key_hash}"
    try:
        if cache_key in st.session_state:
            return st.session_state[cache_key]
    except (ImportError, RuntimeError):
        pass

    status = "invalid"
    try:
        if provider.lower() == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            next(iter(genai.list_models()), None)
            status = "valid"
        elif provider.lower() == "openai":
            from openai import OpenAI, AuthenticationError, APIConnectionError
            OpenAI(api_key=api_key).models.list()
            status = "valid"
    except Exception as e:
        err = str(e).lower()
        if any(t in err for t in ["timeout", "connection", "dns", "unreachable", "network", "deadline", "getaddrinfo"]):
            status = "network_error"
        elif any(t in err for t in ["invalid", "api key", "400", "not found", "authentication"]):
            status = "invalid"
        else:
            try:
                from openai import AuthenticationError, APIConnectionError
                if isinstance(e, AuthenticationError):
                    status = "invalid"
                elif isinstance(e, APIConnectionError):
                    status = "network_error"
            except ImportError:
                pass
            logger.error(f"{provider} API key validation failed: {e}")

    try:
        st.session_state[cache_key] = status
    except (ImportError, RuntimeError):
        pass
    return status

def get_resources():
    """Get (llm, tools_list, tool_executor) from session state, building if needed."""
    try:
        llm = st.session_state.get("agent_llm")
        tools = st.session_state.get("agent_tools")
        executor = st.session_state.get("agent_executor")
        if llm is None or tools is None:
            provider = st.session_state.get("model_provider", "Gemini" if settings.use_gemini else "OpenAI")
            api_key, _ = resolve_api_key(provider)
            if not api_key:
                logger.warning(f"No API key for {provider}")
                return None, [], {}
            loader, _ = resolve_data_loader()
            llm, tools, executor = build_resources(provider, api_key, loader)
            st.session_state["agent_llm"] = llm
            st.session_state["agent_tools"] = tools
            st.session_state["agent_executor"] = executor
        return llm, tools, executor
    except (ImportError, RuntimeError) as e:
        # This module is Streamlit-only. Non-Streamlit callers should use
        # spotify_core.agent.resources.build_resources() directly.
        logger.error(f"Session state unavailable: {e}")
        return None, [], {}

def get_app():
    """Get or build the compiled LangGraph app from session state."""
    try:
        if "agent_app" not in st.session_state:
            llm, tools_list, _ = get_resources()
            if llm is None:
                return None
            st.session_state["agent_app"] = build_app(llm, tools_list)
        return st.session_state["agent_app"]
    except (ImportError, RuntimeError):
        return None

def reset_resources() -> None:
    try:
        for key in ["agent_llm", "agent_tools", "agent_executor", "agent_app"]:
            if key in st.session_state:
                del st.session_state[key]
    except (ImportError, RuntimeError):
        pass
