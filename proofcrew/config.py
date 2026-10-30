"""Configuration from environment variables. No secrets in code, ever.

Required:
  TOKENFACTORY_API_KEY  Nebius Token Factory API key.

Optional:
  TAVILY_API_KEY        Tavily key. If unset, worker B runs ungrounded and the
                        receipts record ``grounded: false`` — honestly.
  TOKENFACTORY_BASE_URL Defaults to the Token Factory endpoint.
  MODEL_PLANNER / MODEL_WORKER / MODEL_SCREENER
                        Model IDs (defaults are the Nemotron 3 tiers).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_PLANNER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_WORKER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_SCREENER_MODEL = "nvidia/nemotron-3-nano-30b-a3b"


@dataclass(frozen=True)
class Config:
    api_key: str | None
    tavily_api_key: str | None
    base_url: str = DEFAULT_BASE_URL
    planner_model: str = DEFAULT_PLANNER_MODEL
    worker_model: str = DEFAULT_WORKER_MODEL
    screener_model: str = DEFAULT_SCREENER_MODEL

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            api_key=env.get("TOKENFACTORY_API_KEY") or None,
            tavily_api_key=env.get("TAVILY_API_KEY") or None,
            base_url=env.get("TOKENFACTORY_BASE_URL", DEFAULT_BASE_URL),
            planner_model=env.get("MODEL_PLANNER", DEFAULT_PLANNER_MODEL),
            worker_model=env.get("MODEL_WORKER", DEFAULT_WORKER_MODEL),
            screener_model=env.get("MODEL_SCREENER", DEFAULT_SCREENER_MODEL),
        )
