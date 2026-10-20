from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from spotify_core import config_file, paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # No env_file: values come from config.json, copied into os.environ by
        # config_file.load_into_env() below. The desktop app (config.rs) is the
        # only writer; this side only reads.
        extra="ignore",
    )

    # API Keys
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Model Configuration
    gemini_model: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL")
    temperature: float = Field(default=0.7, alias="TEMPERATURE")

    # Fallback for a headless run; the app always passes --db.
    history_db_path: Path = Field(default_factory=paths.history_db, alias="HISTORY_DB_PATH")

    # Langfuse (all 3 required to enable tracing)
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: Optional[str] = Field(default=None, alias="LANGFUSE_BASE_URL")

    @field_validator("history_db_path", mode="before")
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

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url)


config_file.load_into_env()
settings = Settings()
