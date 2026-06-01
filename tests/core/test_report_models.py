"""Tests for spotify_core.report.models.build_chat_model."""
import pytest

from spotify_core.report.models import build_chat_model


def test_google_returns_chat_model(monkeypatch):
    monkeypatch.setattr("spotify_core.config.settings.gemini_api_key", "fake-key")
    chat = build_chat_model("google", "gemini-2.5-flash")
    from langchain_google_genai import ChatGoogleGenerativeAI
    assert isinstance(chat, ChatGoogleGenerativeAI)


def test_google_missing_key_raises(monkeypatch):
    monkeypatch.setattr("spotify_core.config.settings.gemini_api_key", None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_chat_model("google", "gemini-2.5-flash")


def test_openai_returns_chat_model(monkeypatch):
    monkeypatch.setattr("spotify_core.config.settings.openai_api_key", "fake-key")
    chat = build_chat_model("openai", "gpt-5.4-mini")
    from langchain_openai import ChatOpenAI
    assert isinstance(chat, ChatOpenAI)


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.setattr("spotify_core.config.settings.openai_api_key", None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_chat_model("openai", "gpt-5.4-mini")


def test_anthropic_skeleton_raises():
    with pytest.raises(NotImplementedError):
        build_chat_model("anthropic", "claude-sonnet-4-6")


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_chat_model("groq", "whatever")
