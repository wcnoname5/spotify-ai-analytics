"""LLM provider factory for the report graph.

build_chat_model dispatches on a provider name and returns a LangChain BaseChatModel.
"""
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

    if provider == "google":
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set."
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model, temperature=settings.temperature, google_api_key=settings.gemini_api_key
        )
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set."
            )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=settings.temperature, api_key=settings.openai_api_key)
    if provider == "anthropic":
        # TODO: implement the Anthropic provider branch (ChatAnthropic).
        raise NotImplementedError("Anthropic provider is not implemented yet.")
    raise ValueError(f"Unknown LLM provider: {provider!r}")
