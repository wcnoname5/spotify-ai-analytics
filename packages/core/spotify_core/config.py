from loguru import logger
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from spotify_core import paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(paths.env_file()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Model Configuration
    use_gemini: bool = Field(default=True, alias="USE_GEMINI")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    openai_model: str = Field(default="gpt-4", alias="OPENAI_MODEL")
    temperature: float = Field(default=0.7, alias="TEMPERATURE")

    # Data paths — defaults flow through paths.py so platformdirs / env override
    # both work without touching this class.
    spotify_data_path: Path = Field(default_factory=paths.spotify_history_dir, alias="SPOTIFY_DATA_PATH")
    spotify_user_id: str = Field(default="default", alias="SPOTIFY_USER_ID")

    history_db_path: Path = Field(default_factory=paths.history_db, alias="HISTORY_DB_PATH")
    tokens_db_path: Path = Field(default_factory=paths.tokens_db, alias="TOKENS_DB_PATH")
    # Spotify credentials
    spotify_client_id: str = Field(default="", alias="SPOTIFY_CLIENT_ID")
    token_encrypt_key: str = Field(default="", alias="TOKEN_ENCRYPT_KEY")

    # Langfuse (all 3 required to enable tracing)
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: Optional[str] = Field(default=None, alias="LANGFUSE_BASE_URL")

    @field_validator(
        "spotify_data_path",
        "history_db_path",
        "tokens_db_path",
        mode="before",
    )
    @classmethod
    def resolve_path(cls, v: str | Path) -> Path:
        if isinstance(v, str):
            path = Path(v).expanduser()
            if not path.is_absolute():
                # Relative paths resolve against the data dir, not cwd, so behavior
                # is stable regardless of where the user invoked the command from.
                return (paths.data_dir() / path).resolve()
            return path.resolve()
        return v

    def validate_paths(self):
        if not self.spotify_data_path.exists():
            logger.warning("SPOTIFY_DATA_PATH not found: {}", self.spotify_data_path)
            logger.warning("Place your Streaming_History_Audio_*.json files there.")
        else:
            logger.info("Spotify history data path verified: {}", self.spotify_data_path)

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url)

    @property
    def fernet_key_bytes(self) -> bytes:
        return self.token_encrypt_key.encode() if self.token_encrypt_key else b""


settings = Settings()


def get_client_id() -> str:
    """Return SPOTIFY_CLIENT_ID from Settings."""
    return settings.spotify_client_id


def get_fernet_key() -> bytes:
    """Return TOKEN_ENCRYPT_KEY as bytes from Settings."""
    return settings.fernet_key_bytes
