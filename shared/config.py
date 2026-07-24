"""
Shared configuration for HealthLink microservices using Pydantic Settings.

Values are loaded from environment variables (injected as Azure Container App
secrets/env-vars in the cloud, or via docker-compose `env_file` locally). A
local `.env` in the working directory is also read if present. There are NO
cloud-hosting settings here anymore - hosting is Azure Container Apps, driven
entirely by the deploy scripts; only model/vector/db config lives in code.
"""
from typing import List
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Configuration (Gemini via langchain-google-genai)
    # Accept GEMINI_API_KEY or the legacy GEMINI_API_KEY_Orig from shared .env files.
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_API_KEY", "GEMINI_API_KEY_Orig")
    )
    llm_model_name: str = "gemini-2.5-flash"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048

    # Embedding Configuration
    embedding_model_name: str = "models/gemini-embedding-001"

    # Pinecone Configuration
    pinecone_api_key: str = ""
    pinecone_environment: str = ""  # e.g. "us-east-1"
    pinecone_index_name: str = "healthlink"

    # RAG Configuration
    rag_top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 50

    # Database Configuration (doctor-agent). Local dev defaults to SQLite.
    # For production set DATABASE_URL to Azure Database for PostgreSQL, e.g.
    #   postgresql+psycopg://user:pass@host:5432/healthlink
    database_url: str = "sqlite:///./data/healthlink.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800

    # Logging Configuration
    log_level: str = "INFO"

    # Security
    secret_key: str = "dev-secret-key-change-in-production"

    # Feature Flags
    enable_metrics: bool = True


def get_settings() -> Settings:
    """Return a fresh Settings instance (each service process is independent)."""
    return Settings()
