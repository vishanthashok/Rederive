"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass, field


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://postgres@localhost:5432/rederive"
        )
    )
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    # fake | anthropic
    llm: str = field(default_factory=lambda: os.environ.get("REDERIVE_LLM", "fake"))
    # hashing | sentence-transformers
    embedder: str = field(
        default_factory=lambda: os.environ.get("REDERIVE_EMBEDDER", "hashing")
    )
    recipe_model: str = field(
        default_factory=lambda: os.environ.get("REDERIVE_RECIPE_MODEL", "claude-sonnet-5")
    )
    judge_model: str = field(
        default_factory=lambda: os.environ.get(
            "REDERIVE_JUDGE_MODEL", "claude-haiku-4-5"
        )
    )
    # Cosine similarity at or above cutoff_equal counts as equal. Below
    # cutoff_different counts as different. The band between goes to the judge.
    cutoff_equal: float = field(default_factory=lambda: _float("REDERIVE_CUTOFF_EQUAL", 0.97))
    cutoff_different: float = field(
        default_factory=lambda: _float("REDERIVE_CUTOFF_DIFFERENT", 0.85)
    )
    fan_in_k: int = field(default_factory=lambda: int(os.environ.get("REDERIVE_FAN_IN_K", 8)))
    # Seconds a worker pauses after marking a record rebuilding. Demo only.
    rebuild_delay: float = field(default_factory=lambda: _float("REDERIVE_REBUILD_DELAY", 0.0))
    allow_reset: bool = field(
        default_factory=lambda: os.environ.get("REDERIVE_ALLOW_RESET", "0") == "1"
    )


settings = Settings()
