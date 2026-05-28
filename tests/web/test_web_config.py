"""Tests for spotify_web.config.get_llm_config."""
from spotify_web.config import get_llm_config


def test_get_llm_config_empty_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = get_llm_config()
    assert config["models"] == []


def test_get_llm_config_lists_google_models_when_key_set(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = get_llm_config()
    assert config["models"]
    assert all(m["provider"] == "google" for m in config["models"])


def test_get_llm_config_lists_openai_models_when_key_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = get_llm_config()
    assert config["models"]
    assert all(m["provider"] == "openai" for m in config["models"])
