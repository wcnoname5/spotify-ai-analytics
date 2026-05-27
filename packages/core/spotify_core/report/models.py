"""LLM provider factory for the report graph.

build_chat_model dispatches on a provider name and returns a LangChain
BaseChatModel. Google is the only implemented provider in v1; OpenAI and
Anthropic are skeletons with a final signature so enabling them later is a
localized change.
"""
from loguru import logger
from langchain_core.language_models import BaseChatModel


def build_chat_model(provider: str, model: str) -> BaseChatModel:
    """Return a chat model for the given provider.

    Args:
        provider: One of "google", "openai", "anthropic".
        model: Provider-specific model name, e.g. "gemini-2.5-flash".

    Raises:
        ValueError: Unknown provider, or the provider's API key is missing.
        NotImplementedError: provider is "openai" or "anthropic" (v1 skeletons).
    """
    from spotify_core.config import settings

    logger.debug("build_chat_model: provider={} model={}", provider, model)
    if provider == "google":
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Add it to your .env or run `spotify-mcp setup` to configure LLM keys."
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        logger.info("build_chat_model: ChatGoogleGenerativeAI model={}", model)
        return ChatGoogleGenerativeAI(
            model=model, temperature=0.7, google_api_key=settings.gemini_api_key
        )
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to your .env or run `spotify-mcp setup` to configure LLM keys."
            )
        from langchain_openai import ChatOpenAI
        logger.info("build_chat_model: ChatOpenAI model={}", model)
        return ChatOpenAI(model=model, temperature=0.7, api_key=settings.openai_api_key)
    if provider == "anthropic":
        # TODO: implement the Anthropic provider branch (ChatAnthropic).
        raise NotImplementedError("Anthropic provider is not implemented yet.")
    raise ValueError(f"Unknown LLM provider: {provider!r}")
