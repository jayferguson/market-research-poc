"""Configuration and LLM client builder for Market Research PoC.

Supports:
- xAI / Grok via official OpenAI-compatible endpoint (XAI_API_KEY)
- Local LLM servers (LM Studio, Ollama, llama.cpp server) via OPENAI_BASE_URL
- Brave Search API key (preferred for discovery)
- Model override via env or CLI
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


@dataclass
class Settings:
    xai_api_key: str = ""
    openai_base_url: str = "https://api.x.ai/v1"
    openai_api_key: str = "not-needed"
    brave_api_key: str = ""
    model: str = "grok-4.3-latest"
    db_path: str = "market_research.db"
    target_company: str = "Harvard BioScience"  # The single company this PoC is configured for (plus subsidiaries)


def load_settings(env_path: str | None = None) -> Settings:
    """Load from .env (if present) + os.environ. Sensible defaults."""
    if env_path:
        load_dotenv(env_path, override=True)
    else:
        # Try local .env then parent
        for p in (".env", "../.env"):
            if Path(p).exists():
                load_dotenv(p, override=True)
                break
        else:
            load_dotenv(override=True)  # last resort

    s = Settings()
    s.xai_api_key = os.getenv("XAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    s.openai_base_url = os.getenv("OPENAI_BASE_URL", s.openai_base_url)
    s.openai_api_key = os.getenv("OPENAI_API_KEY", s.openai_api_key)
    s.brave_api_key = os.getenv("BRAVE_API_KEY", "")
    s.model = os.getenv("MODEL", s.model)
    s.db_path = os.getenv("DB_PATH", s.db_path)
    s.target_company = os.getenv("TARGET_COMPANY", s.target_company)
    return s


def build_llm_client(settings: Settings | None = None) -> OpenAI:
    """Return OpenAI client configured for xAI or local endpoint."""
    if settings is None:
        settings = load_settings()

    api_key = settings.xai_api_key or settings.openai_api_key
    base_url = settings.openai_base_url

    if "x.ai" in base_url.lower() or settings.xai_api_key:
        # Prefer xAI endpoint when key present
        base_url = "https://api.x.ai/v1"
        api_key = settings.xai_api_key or api_key

    return OpenAI(
        api_key=api_key or "not-needed",
        base_url=base_url,
    )


def get_brave_key(settings: Settings | None = None) -> str:
    if settings is None:
        settings = load_settings()
    return settings.brave_api_key
