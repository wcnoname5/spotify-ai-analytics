"""Wizard LLM key step persists keys or skips cleanly."""
from unittest.mock import MagicMock

from spotify_mcp.wizard import llm_keys


def test_skip_when_user_declines(monkeypatch, tmp_path):
    """User types 'n' at the prompt — no keys persisted."""
    console = MagicMock()
    console.input.return_value = "n"
    env_path = tmp_path / ".env"
    monkeypatch.setattr("spotify_mcp.wizard.llm_keys.paths.env_file", lambda: env_path)
    llm_keys.run_step(console=console)
    env_content = env_path.read_text() if env_path.exists() else ""
    assert "GEMINI_API_KEY" not in env_content
    assert "OPENAI_API_KEY" not in env_content


def test_gemini_key_persisted(monkeypatch, tmp_path):
    """User opts in, chooses Gemini, provides a key — key lands in .env."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    console = MagicMock()
    console.input.side_effect = ["y", "1", "fake-gemini-key"]
    env_path = tmp_path / ".env"
    monkeypatch.setattr("spotify_mcp.wizard.llm_keys.paths.env_file", lambda: env_path)
    llm_keys.run_step(console=console)
    assert "GEMINI_API_KEY=fake-gemini-key" in env_path.read_text()


def test_openai_key_persisted(monkeypatch, tmp_path):
    """User opts in, chooses OpenAI, provides a key — key lands in .env."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    console = MagicMock()
    console.input.side_effect = ["y", "2", "fake-openai-key"]
    env_path = tmp_path / ".env"
    monkeypatch.setattr("spotify_mcp.wizard.llm_keys.paths.env_file", lambda: env_path)
    llm_keys.run_step(console=console)
    assert "OPENAI_API_KEY=fake-openai-key" in env_path.read_text()


def test_skips_when_key_already_configured(monkeypatch, tmp_path):
    """Step is idempotent — pre-existing key short-circuits the prompt."""
    console = MagicMock()
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=already-set\n")
    monkeypatch.setattr("spotify_mcp.wizard.llm_keys.paths.env_file", lambda: env_path)
    llm_keys.run_step(console=console)
    console.input.assert_not_called()
