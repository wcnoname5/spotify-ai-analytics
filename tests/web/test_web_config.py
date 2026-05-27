"""Tests for spotify_web.config.get_llm_config."""
from spotify_web import config as web_config


def test_get_llm_config_empty_without_key(monkeypatch):
    monkeypatch.setattr(web_config.settings, "gemini_api_key", None)
    monkeypatch.setattr(web_config.settings, "openai_api_key", None)
    config = web_config.get_llm_config()
    assert config["models"] == []


def test_get_llm_config_lists_google_models_when_key_set(monkeypatch):
    monkeypatch.setattr(web_config.settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(web_config.settings, "openai_api_key", None)
    config = web_config.get_llm_config()
    assert config["models"]
    assert all(m["provider"] == "google" for m in config["models"])


def test_get_llm_config_lists_openai_models_when_key_set(monkeypatch):
    monkeypatch.setattr(web_config.settings, "openai_api_key", "fake-key")
    monkeypatch.setattr(web_config.settings, "gemini_api_key", None)
    config = web_config.get_llm_config()
    assert config["models"]
    assert all(m["provider"] == "openai" for m in config["models"])
