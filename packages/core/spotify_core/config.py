import os
import logging
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

# Project root directory (spotify-ai-analytics/)
# 4 .parent calls from packages/core/spotify_core/config.py reaches the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding='utf-8',
        extra='ignore'
    )

    # API Keys
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Model Configuration
    use_gemini: bool = Field(default=True, alias="USE_GEMINI")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    openai_model: str = Field(default="gpt-4", alias="OPENAI_MODEL")

    # Data Paths
    _default_data_path: Path = PROJECT_ROOT / "data" / "spotify_history"
    spotify_data_path: Path = Field(default=_default_data_path, alias="SPOTIFY_DATA_PATH")
    spotify_user_id: str = Field(default="default", alias="SPOTIFY_USER_ID")

    # DB paths — overridable via env vars; resolved relative to PROJECT_ROOT when not absolute
    history_db_path: Path = Field(
        default=PROJECT_ROOT / "data" / "history.db", alias="HISTORY_DB_PATH"
    )
    tokens_db_path: Path = Field(
        default=PROJECT_ROOT / "data" / "tokens.db", alias="TOKENS_DB_PATH"
    )
    ltm_db_path: Path = Field(
        default=PROJECT_ROOT / "data" / "ltm.db", alias="LTM_DB_PATH"
    )
    checkpoints_db_path: Path = Field(
        default=PROJECT_ROOT / "data" / "checkpoints.db", alias="CHECKPOINTS_DB_PATH"
    )

    @field_validator(
        "spotify_data_path",
        "history_db_path",
        "tokens_db_path",
        "ltm_db_path",
        "checkpoints_db_path",
        mode="before",
    )
    @classmethod
    def resolve_path(cls, v: str | Path) -> Path:
        if isinstance(v, str):
            path = Path(v)
            if not path.is_absolute():
                return (PROJECT_ROOT / path).resolve()
            return path.resolve()
        return v

    def validate_paths(self):
        """Check if critical paths exist and warn if they don't."""
        logger = logging.getLogger(__name__)
        if not self.spotify_data_path.exists():
            logger.warning(f"SPOTIFY_DATA_PATH not found: {self.spotify_data_path}")
            logger.warning("Please ensure your Spotify history JSON files are in that directory.")
        else:
            logger.info(f"Spotify history data path verified: {self.spotify_data_path}")

# Initialize settings
settings = Settings()
