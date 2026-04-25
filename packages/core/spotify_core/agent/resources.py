"""Pure resource factory. No Streamlit dependency."""
import logging
from typing import Optional, Tuple
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from spotify_dataloader import SpotifyDataLoader
from .tools import initialize_tools
from ..config import settings

logger = logging.getLogger(__name__)

def build_llm(provider: str, api_key: str):
    """Build LLM instance from provider name and API key."""
    if provider.lower() == "gemini":
        return ChatGoogleGenerativeAI(model=settings.gemini_model, google_api_key=api_key, temperature=0)
    return ChatOpenAI(model=settings.openai_model, api_key=api_key, temperature=0)

def build_resources(provider: str, api_key: str, loader: Optional[SpotifyDataLoader] = None):
    """Build LLM, tools list, and tool executor dict.

    Returns:
        (llm, tools_list, tool_executor) tuple
    """
    llm = build_llm(provider, api_key)
    tools_list = initialize_tools(loader=loader)
    tool_executor = {t.name: t for t in tools_list}
    return llm, tools_list, tool_executor
