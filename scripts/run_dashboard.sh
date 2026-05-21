#!/usr/bin/env bash

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if ! uvx --from spotify-analytics-mcp spotify-mcp doctor; then
  echo "Setup incomplete - launching setup wizard..."
  uvx --from spotify-analytics-mcp spotify-mcp setup
fi

exec uv run streamlit run ../apps/web/ui/main_page.py