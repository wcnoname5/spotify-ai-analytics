import os
from pathlib import Path

# Project root directory (spotify-ai-analytics/)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# Default data path relative to project root
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "spotify_history"