"""Tests for wizard.history_import — GUI picker with cwd-scan fallback."""
from pathlib import Path

import pytest
from rich.console import Console

from spotify_mcp.wizard import history_import as hi


def test_scan_dir_finds_streaming_files(tmp_path):
    (tmp_path / "Streaming_History_Audio_2023.json").write_text("[]")
    (tmp_path / "Streaming_History_Audio_2024.json").write_text("[]")
    (tmp_path / "other.json").write_text("[]")
    found = hi.scan_dir(tmp_path)
    assert len(found) == 2
    assert all(p.name.startswith("Streaming_History_Audio_") for p in found)


def test_scan_dir_returns_empty_when_no_match(tmp_path):
    assert hi.scan_dir(tmp_path) == []


def test_pick_dir_via_gui_returns_none_when_tkinter_unavailable(monkeypatch):
    # Simulate "no GUI" by making the GUI helper raise.
    monkeypatch.setattr(hi, "_tk_askdirectory", lambda: (_ for _ in ()).throw(RuntimeError("no display")))
    assert hi.pick_dir_via_gui() is None


def test_pick_dir_via_gui_returns_none_when_user_cancels(monkeypatch):
    # askdirectory returns "" when the user cancels.
    monkeypatch.setattr(hi, "_tk_askdirectory", lambda: "")
    assert hi.pick_dir_via_gui() is None


def test_pick_dir_via_gui_returns_path_when_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(hi, "_tk_askdirectory", lambda: str(tmp_path))
    assert hi.pick_dir_via_gui() == tmp_path


def test_run_step_skip_choice_does_nothing(monkeypatch):
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "skip")
    called = {"import": False, "sync": False}
    monkeypatch.setattr(hi, "_do_import", lambda console, files, db_target=None: called.__setitem__("import", True))
    monkeypatch.setattr(hi, "_do_sync_recent", lambda console: called.__setitem__("sync", True))
    hi.run_step(console=Console(record=True))
    assert called == {"import": False, "sync": False}


def test_run_step_import_uses_gui_when_available(tmp_path, monkeypatch):
    (tmp_path / "Streaming_History_Audio_2023.json").write_text("[]")
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "import")
    monkeypatch.setattr(hi, "pick_dir_via_gui", lambda: tmp_path)
    captured = {}
    monkeypatch.setattr(hi, "_do_import", lambda console, files, db_target=None: captured.update(files=files))
    hi.run_step(console=Console(record=True))
    assert len(captured["files"]) == 1


def test_run_step_falls_back_to_cwd_scan_when_gui_unavailable(tmp_path, monkeypatch):
    (tmp_path / "Streaming_History_Audio_2023.json").write_text("[]")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "import")
    monkeypatch.setattr(hi, "pick_dir_via_gui", lambda: None)  # GUI unavailable / cancelled
    monkeypatch.setattr(hi, "_confirm_use_cwd", lambda console, files, db_target=None: True)
    captured = {}
    monkeypatch.setattr(hi, "_do_import", lambda console, files, db_target=None: captured.update(files=files))
    hi.run_step(console=Console(record=True))
    assert len(captured["files"]) == 1


def test_run_step_skips_when_gui_cancelled_and_cwd_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hi, "_prompt_choice", lambda console: "import")
    monkeypatch.setattr(hi, "pick_dir_via_gui", lambda: None)
    called = {"import": False}
    monkeypatch.setattr(hi, "_do_import", lambda console, files, db_target=None: called.__setitem__("import", True))
    hi.run_step(console=Console(record=True))
    assert called["import"] is False
