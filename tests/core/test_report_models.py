"""Tests for spotify_core.report.models.build_chat_model.

_GEMINI_API_KEY is resolved at module import, so the tests patch the module
attribute directly (monkeypatch.setattr) rather than the environment.
"""
import pytest

from spotify_core.report import models
from spotify_core.report.models import build_chat_model


def test_google_returns_chat_model(monkeypatch):
    monkeypatch.setattr(models, "_GEMINI_API_KEY", "fake-key")
    chat = build_chat_model("google", "gemini-2.5-flash")
    from langchain_google_genai import ChatGoogleGenerativeAI
    assert isinstance(chat, ChatGoogleGenerativeAI)


def test_google_missing_key_raises(monkeypatch):
    monkeypatch.setattr(models, "_GEMINI_API_KEY", None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_chat_model("google", "gemini-2.5-flash")


def test_openai_returns_chat_model(monkeypatch):
    monkeypatch.setattr(models, "_OPENAI_API_KEY", "fake-key")
    chat = build_chat_model("openai", "gpt-5.4-mini")
    from langchain_openai import ChatOpenAI
    assert isinstance(chat, ChatOpenAI)


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.setattr(models, "_OPENAI_API_KEY", None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_chat_model("openai", "gpt-5.4-mini")


def test_anthropic_skeleton_raises():
    with pytest.raises(NotImplementedError):
        build_chat_model("anthropic", "claude-sonnet-4-6")


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_chat_model("groq", "whatever")
