"""LLM provider factory for the report graph.

build_chat_model dispatches on a provider name and returns a LangChain
BaseChatModel. Google is the only implemented provider in v1; OpenAI and
Anthropic are skeletons with a final signature so enabling them later is a
localized change.
"""
import os

from loguru import logger
from langchain_core.language_models import BaseChatModel

from ..env import ensure_dotenv_loaded

# Resolve the provider key once, at import — after the platform .env is loaded.
# Kept at module scope (not inside build_chat_model) so a future config source
# other than .env can be swapped in here without touching the factory.
ensure_dotenv_loaded()
# comment: GEMINI_API_KEY has already existed so let's keep this name instead of GOOGLE_API_KEY.
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def build_chat_model(provider: str, model: str) -> BaseChatModel:
    """Return a chat model for the given provider.

    Args:
        provider: One of "google", "openai", "anthropic".
        model: Provider-specific model name, e.g. "gemini-2.5-flash".

    Raises:
        ValueError: Unknown provider, or the provider's API key is missing.
        NotImplementedError: provider is "openai" or "anthropic" (v1 skeletons).
    """
    logger.debug("build_chat_model: provider={} model={}", provider, model)
    if provider == "google":
        if not _GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is not set. Add it to your .env to use the "
                "AI report block."
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        logger.info("build_chat_model: ChatGoogleGenerativeAI model={}", model)
        return ChatGoogleGenerativeAI(
            model=model, temperature=0.7, google_api_key=_GEMINI_API_KEY
        )
    if provider == "openai":
        # TODO: implement the OpenAI provider branch (ChatOpenAI).
        raise NotImplementedError("OpenAI provider is not implemented yet.")
    if provider == "anthropic":
        # TODO: implement the Anthropic provider branch (ChatAnthropic).
        raise NotImplementedError("Anthropic provider is not implemented yet.")
    raise ValueError(f"Unknown LLM provider: {provider!r}")
