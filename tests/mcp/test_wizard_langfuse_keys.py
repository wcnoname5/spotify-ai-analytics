"""Wizard Langfuse step is skippable and persists all 3 keys when provided."""
from unittest.mock import MagicMock

from spotify_mcp.wizard import langfuse_keys


def test_skip_when_user_declines(monkeypatch, tmp_path):
    console = MagicMock()
    console.input.return_value = "n"
    env_path = tmp_path / ".env"
    monkeypatch.setattr("spotify_mcp.wizard.langfuse_keys.paths.env_file", lambda: env_path)
    langfuse_keys.run_step(console=console)
    env_content = env_path.read_text() if env_path.exists() else ""
    assert "LANGFUSE" not in env_content


def test_all_three_keys_persisted(monkeypatch, tmp_path):
    console = MagicMock()
    console.input.side_effect = ["y", "pk-lf-xxx", "sk-lf-xxx", "https://cloud.langfuse.com"]
    env_path = tmp_path / ".env"
    monkeypatch.setattr("spotify_mcp.wizard.langfuse_keys.paths.env_file", lambda: env_path)
    langfuse_keys.run_step(console=console)
    content = env_path.read_text()
    assert "LANGFUSE_PUBLIC_KEY=pk-lf-xxx" in content
    assert "LANGFUSE_SECRET_KEY=sk-lf-xxx" in content
    assert "LANGFUSE_BASE_URL=https://cloud.langfuse.com" in content


def test_skips_when_already_configured(monkeypatch, tmp_path):
    console = MagicMock()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LANGFUSE_PUBLIC_KEY=pk\nLANGFUSE_SECRET_KEY=sk\nLANGFUSE_BASE_URL=https://x.io\n"
    )
    monkeypatch.setattr("spotify_mcp.wizard.langfuse_keys.paths.env_file", lambda: env_path)
    langfuse_keys.run_step(console=console)
    console.input.assert_not_called()
