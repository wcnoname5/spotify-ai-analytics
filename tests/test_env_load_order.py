import importlib
import sys


def test_env_load_order(tmp_path, monkeypatch):
    """Ensure apps load the .env (via platform config dir) before settings are imported.

    Strategy:
    - Point SPOTIFY_MCP_CONFIG_DIR to a tmp dir
    - Write a .env with SPOTIFY_CLIENT_ID only in that file (not in os.environ)
    - Clear relevant modules from sys.modules so imports re-run
    - Import the app config and confirm get_client_id() reads from the .env
    """
    # Prepare temp config dir and .env
    cfg_dir = tmp_path / "config_dir"
    cfg_dir.mkdir()
    env_file = cfg_dir / ".env"
    env_file.write_text("SPOTIFY_CLIENT_ID=from_env_file\n")

    monkeypatch.setenv("SPOTIFY_MCP_CONFIG_DIR", str(cfg_dir))
    # Ensure process env does NOT already have the key
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    # Remove cached modules so imports happen fresh and Settings re-reads the .env
    # from the temp config dir (env_file is resolved at Settings construction time).
    for mod in [
        "spotify_core.config",
        "spotify_mcp.config",
        "spotify_mcp.dashboard.runtime",
    ]:
        if mod in sys.modules:
            del sys.modules[mod]

    # Import the MCP app config and assert it reads the client id from .env
    mcp_cfg = importlib.import_module("spotify_mcp.config")
    assert mcp_cfg.get_client_id() == "from_env_file"

    # Import the web app config and assert it also reads the same value
    web_cfg = importlib.import_module("spotify_mcp.dashboard.runtime")
    assert web_cfg.get_client_id() == "from_env_file"
