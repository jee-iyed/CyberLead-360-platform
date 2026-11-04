"""Application configuration.

All runtime configuration is read from environment variables (optionally loaded
from a local ``.env`` file). Secrets such as API keys are typed as ``SecretStr``
so they are never printed accidentally in logs, tracebacks or the UI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

LLMProviderName = Literal["none", "anthropic", "openai_compatible"]


class Settings(BaseSettings):
    """Typed settings object. Instantiate through :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General -----------------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "CyberLead 360"
    operator_name: str = Field(
        default="demo.user",
        description="Name recorded on audit events. Single-operator demo: no authentication.",
    )
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    # --- Database ----------------------------------------------------------------
    database_url: str = f"sqlite:///{(DEFAULT_DATA_DIR / 'cyberlead360.db').as_posix()}"
    auto_migrate: bool = Field(
        default=True, description="Run Alembic migrations automatically at app start."
    )
    sql_echo: bool = False

    # --- Uploads / exports -------------------------------------------------------
    max_upload_mb: float = 5.0
    max_import_rows: int = 5000
    export_dir: Path = DEFAULT_DATA_DIR / "exports"

    # --- AI provider -------------------------------------------------------------
    llm_provider: LLMProviderName = "none"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 2000
    llm_max_input_chars: int = 12000
    llm_input_price_per_mtok: float = 0.0
    llm_output_price_per_mtok: float = 0.0

    # --- Public-source retrieval -------------------------------------------------
    enable_web_retrieval: bool = False
    retrieval_user_agent: str = "CyberLead360-ResearchBot/1.0 (+https://example.com/bot)"
    retrieval_timeout_seconds: float = 10.0
    retrieval_max_bytes: int = 1_000_000
    retrieval_min_interval_seconds: float = 2.0
    retrieval_allow_any_public_host: bool = False

    # --- Privacy -----------------------------------------------------------------
    contact_retention_days: int = 730
    fact_freshness_days: int = 365

    @field_validator("database_url")
    @classmethod
    def _expand_sqlite_relative_path(cls, value: str) -> str:
        """Resolve ``sqlite:///./relative.db`` against the project root."""
        prefix = "sqlite:///"
        if value.startswith(prefix) and not value.startswith(prefix + "/"):
            raw = value[len(prefix) :]
            if raw and raw != ":memory:" and not Path(raw).is_absolute():
                return prefix + (PROJECT_ROOT / raw).resolve().as_posix()
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key is not None
        if self.llm_provider == "openai_compatible":
            return self.openai_api_key is not None or bool(self.openai_base_url)
        return False

    @property
    def active_model(self) -> str | None:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        if self.llm_provider == "openai_compatible":
            return self.openai_model
        return None

    def public_summary(self) -> dict[str, object]:
        """Non-secret configuration suitable for display in the Settings page."""
        return {
            "Environment": self.app_env,
            "Database backend": "SQLite" if self.is_sqlite else self.database_url.split(":")[0],
            "Automatic migrations": self.auto_migrate,
            "LLM provider": self.llm_provider,
            "LLM model": self.active_model or "—",
            "LLM enabled (key present)": self.llm_enabled,
            "Contact names sent to LLM": "never (placeholder substituted locally)",
            "Web retrieval enabled": self.enable_web_retrieval,
            "Retrieval restricted to company domain": not self.retrieval_allow_any_public_host,
            "Max upload size (MB)": self.max_upload_mb,
            "Max import rows": self.max_import_rows,
            "Contact retention (days)": self.contact_retention_days,
            "Fact freshness threshold (days)": self.fact_freshness_days,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide settings instance (cached)."""
    return Settings()
