"""Configuration — file-based, environment-overridable (spec §12).

No credentials anywhere: recon proved collection needs no authentication.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# A realistic desktop-Chrome UA; the api-proxy also requires the x-requested-with header
# defined in adapter.py (attached by the transport layer).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class Settings(BaseSettings):
    """Runtime configuration. Override any field via env var ``PETITIONER_<FIELD>``."""

    model_config = SettingsConfigDict(
        env_prefix="PETITIONER_", env_file=".env", extra="ignore"
    )

    # Politeness / resilience (spec §5.7–5.8)
    requests_per_second: float = Field(default=1.0, gt=0)
    jitter_seconds: float = Field(default=0.5, ge=0)
    max_retries: int = Field(default=4, ge=0)
    backoff_base_seconds: float = Field(default=1.0, gt=0)
    per_domain_request_ceiling: int = Field(default=10_000, gt=0)
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    user_agent: str = DEFAULT_USER_AGENT

    # Storage / output (spec §11, §13)
    db_path: Path = Path("petitioner.db")
    raw_payload_dir: Path = Path("raw_payloads")
    export_dir: Path = Path("exports")
    manifest_dir: Path = Path("manifests")

    # Discovery
    language_allowlist: tuple[str, ...] = ("en",)
    exclude_non_allowed_languages: bool = True

    log_level: str = "INFO"


def load_settings(**overrides: object) -> Settings:
    """Load settings from env/.env, with explicit keyword overrides on top."""
    return Settings(**overrides)  # type: ignore[arg-type]
