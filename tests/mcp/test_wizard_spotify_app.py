"""Tests for the Spotify-app wizard step (port probe + dashboard checklist)."""
import socket

import pytest
from rich.console import Console

from spotify_mcp.wizard import spotify_app


def test_port_available_returns_true_when_free(monkeypatch):
    # Pick a port we know is unbound: bind ephemeral, free it, ask.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert spotify_app.port_available(port) is True


def test_port_available_returns_false_when_bound():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        assert spotify_app.port_available(port) is False
    finally:
        s.close()


def test_run_step_aborts_when_port_in_use(monkeypatch):
    monkeypatch.setattr(spotify_app, "port_available", lambda p: False)
    console = Console(record=True, width=120)
    with pytest.raises(spotify_app.PortInUseError):
        spotify_app.run_step(console=console, port=spotify_app.OAUTH_PORT)


def test_run_step_prints_checklist_when_port_free(monkeypatch):
    monkeypatch.setattr(spotify_app, "port_available", lambda p: True)
    monkeypatch.setattr(spotify_app, "_open_browser", lambda url: None)
    console = Console(record=True, width=120)
    spotify_app.run_step(console=console, port=spotify_app.OAUTH_PORT)
    output = console.export_text()
    assert "Create app" in output
    assert "http://127.0.0.1:8888/callback" in output
