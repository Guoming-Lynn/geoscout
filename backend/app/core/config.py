from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_origins(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [v.strip() for v in value if v.strip()]
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEOSCOUT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")
    ncbi_tool: str = "GEOScout"
    ncbi_email: str = ""
    ncbi_api_key: str = ""
    ncbi_mode: Literal["live", "mock"] = "live"
    llm_mode: Literal["live", "mock"] = "live"
    allow_demo: bool = False
    demo_mode: bool = False
    internal_token: str = ""
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
        ]
    )
    max_soft_bytes: int = 50_000_000
    request_timeout_s: float = 45.0
    job_lease_s: int = 45
    snapshot_ttl_days: int = 30
    api_url: str = "http://127.0.0.1:8000"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        return _split_origins(value)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "geoscout.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "cache").mkdir(parents=True, exist_ok=True)

    def demo_allowed(self) -> bool:
        return bool(self.allow_demo and self.demo_mode)


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    token_path = settings.data_dir / ".internal_token"
    if settings.internal_token:
        token_path.write_text(settings.internal_token, encoding="utf-8")
    elif token_path.exists():
        settings.internal_token = token_path.read_text(encoding="utf-8").strip()
    else:
        settings.internal_token = secrets.token_urlsafe(32)
        token_path.write_text(settings.internal_token, encoding="utf-8")
    if settings.demo_mode and not settings.allow_demo:
        raise RuntimeError("GEOSCOUT_DEMO_MODE requires GEOSCOUT_ALLOW_DEMO=true")
    return settings


settings = load_settings()
