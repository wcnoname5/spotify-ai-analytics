@echo off
cd /d "%~dp0"
uvx --from spotify-analytics-mcp spotify-mcp doctor
if errorlevel 1 (
    echo Setup incomplete - launching setup wizard...
    uvx --from spotify-analytics-mcp spotify-mcp setup
)
uv run streamlit run ../apps/mcp/spotify_mcp/dashboard/main_page.py
