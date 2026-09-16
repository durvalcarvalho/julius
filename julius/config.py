from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "julius" / "prices.db"


@dataclass(frozen=True)
class Config:
    db_path: Path
    ai_api_key: str | None
    ai_base_url: str | None
    ai_model: str | None
    ai_budget_usd: float
    ai_input_price_usd_per_1m: float | None
    ai_output_price_usd_per_1m: float | None
    ai_request_extras: dict[str, object] = field(default_factory=dict)

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key and self.ai_base_url and self.ai_model)

    @property
    def ai_log_path(self) -> Path:
        return self.db_path.parent / "ai_calls.jsonl"

    @property
    def query_log_path(self) -> Path:
        return self.db_path.parent / "query_log.jsonl"


def load(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    budget = _optional_float(env, "JULIUS_AI_BUDGET_USD")
    return Config(
        db_path=Path(env.get("JULIUS_DB") or DEFAULT_DB_PATH),
        ai_api_key=env.get("JULIUS_AI_API_KEY") or None,
        ai_base_url=env.get("JULIUS_AI_BASE_URL") or None,
        ai_model=env.get("JULIUS_AI_MODEL") or None,
        ai_budget_usd=1.0 if budget is None else budget,
        ai_input_price_usd_per_1m=_optional_float(env, "JULIUS_AI_INPUT_PRICE_USD_PER_1M"),
        ai_output_price_usd_per_1m=_optional_float(env, "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M"),
        ai_request_extras=_request_extras(env),
    )


def _optional_float(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


def _request_extras(env: Mapping[str, str]) -> dict[str, object]:
    raw = env.get("JULIUS_AI_REQUEST_EXTRAS")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        raise ValueError(f"JULIUS_AI_REQUEST_EXTRAS must be a JSON object, got {raw!r}")
    return parsed
