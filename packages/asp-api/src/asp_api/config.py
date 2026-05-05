"""Typed runtime configuration. All env-var access goes through here.

Downstream code must never call `os.environ[...]` directly — import `Settings`
instead. That keeps secrets auditable (one import to grep) and makes tests
deterministic (override via fixture).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API ---
    asp_api_host: str = "0.0.0.0"  # noqa: S104 — containerized; bind explicit
    asp_api_port: int = 8000
    asp_api_log_level: str = "INFO"
    asp_api_environment: Literal["development", "staging", "production"] = "development"
    asp_api_cors_origins: str = "http://localhost:3000"

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="changeme", repr=False)
    neo4j_database: str = "neo4j"

    # --- Ontology ---
    asp_ontology_version: str = "v1"

    # --- OPA (optional in v0.1) ---
    opa_url: str = "http://localhost:8181"

    # --- Security hardening toggles ---
    asp_require_tls: bool = False
    asp_require_signed_policies: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.asp_api_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Tests can clear the cache to re-read env."""
    return Settings()
