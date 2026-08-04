"""The LLM/Langfuse wizard steps run only when the [dashboard] extra is present."""
import spotify_mcp.wizard as wiz


def _mark_all_steps_done(monkeypatch):
    import spotify_mcp.wizard.state as state

    for name in (
        "has_client_id",
        "has_fernet_key",
        "dbs_initialized",
        "tokens_valid",
        "history_has_data",
    ):
        monkeypatch.setattr(state, name, lambda: True)


def _record_steps(monkeypatch, called):
    import spotify_mcp.wizard.claude_desktop as cdk
    import spotify_mcp.wizard.langfuse_keys as lfk
    import spotify_mcp.wizard.llm_keys as lk

    monkeypatch.setattr(lk, "run_step", lambda **k: called.append("llm"))
    monkeypatch.setattr(lfk, "run_step", lambda **k: called.append("langfuse"))
    monkeypatch.setattr(cdk, "run_step", lambda **k: called.append("claude_desktop"))


def test_dashboard_installed_requires_all_startup_dependencies(monkeypatch):
    import spotify_mcp.wizard.dependencies as deps

    def fake_find_spec(name):
        return object() if name == deps._REPORT_IMPORTS[0] else None

    monkeypatch.setattr(deps.importlib.util, "find_spec", fake_find_spec)

    assert wiz._dashboard_installed() is False


def test_dashboard_installed_true_when_all_present(monkeypatch):
    import spotify_mcp.wizard.dependencies as deps

    monkeypatch.setattr(deps.importlib.util, "find_spec", lambda name: object())

    assert wiz._dashboard_installed() is True


def test_wizard_skips_llm_steps_without_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path / "data"))
    _mark_all_steps_done(monkeypatch)
    monkeypatch.setattr(wiz, "_dashboard_installed", lambda: False)
    called: list[str] = []
    _record_steps(monkeypatch, called)

    wiz.run_wizard()

    assert "llm" not in called
    assert "langfuse" not in called
    assert called == ["claude_desktop"]


def test_wizard_runs_llm_steps_with_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("SPOTIFY_DATA_DIR", str(tmp_path / "data"))
    _mark_all_steps_done(monkeypatch)
    monkeypatch.setattr(wiz, "_dashboard_installed", lambda: True)
    called: list[str] = []
    _record_steps(monkeypatch, called)

    wiz.run_wizard()

    assert called == ["llm", "langfuse", "claude_desktop"]
