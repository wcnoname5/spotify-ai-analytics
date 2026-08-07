# spotify-analytics-mcp

An MCP server that lets Claude Desktop / Claude Code query your Spotify listening
history in natural language.

> **Orphaned, and not a v1 feature.** Checkout-only, not in the installer. The stats
> and history tools work; the playback tools do not: they read a local token store
> that nothing writes any more.

## Requirements

A working install of the desktop app first — the MCP server reads the same config file
and the same local SQLite cache. See [the project README](../../README.md).

Then, from a checkout:

```bash
uv sync
uv run spotify-mcp doctor      # check readiness
uv run spotify-mcp cloud pull  # refresh the local cache from D1
```

## Connect Claude Desktop

Get the config snippet:

```bash
uv run spotify-mcp mcp-config
```

It prints something like:

```json
{
  "mcpServers": {
    "spotify-mcp": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/spotify-ai-analytics", "spotify-mcp", "serve"]
    }
  }
}
```

To add it:

1. Open Claude Desktop, click the menu (☰) in the top-left.
2. Go to **Developer → Open App Config File…** to open `claude_desktop_config.json`.
   > If developer mode isn't on yet, enable it under
   > **Help → Troubleshooting → Enable Developer Mode** first.
3. Paste the snippet (merge into the existing `mcpServers` object if you have others).
4. Click **Developer → Reload MCP Configuration**, or restart Claude Desktop.
5. In a new chat, click **+ → Connectors** — **spotify-mcp** should be listed.

## Tools

Stats and history (working) · playback control (broken until it fetches tokens from
the Worker).

```bash
uv run spotify-mcp --help
```
