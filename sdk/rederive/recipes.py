"""Recipes: the template, model, and params that turn inputs into a record.

The hash is the recipe's identity. The server computes it with the same
function, so a recipe hashed locally matches the stored row.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def recipe_hash(template: str, model: str, params: dict[str, Any] | None = None) -> str:
    canonical = json.dumps(
        {"template": template, "model": model, "params": params or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Recipe:
    template: str
    model: str = "default"
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def hash(self) -> str:
        return recipe_hash(self.template, self.model, self.params)

    def to_json(self) -> dict[str, Any]:
        return {"template": self.template, "model": self.model, "params": self.params}


class RecipeRegistry:
    """Named recipes for an agent. Names are local, hashes are global."""

    def __init__(self) -> None:
        self._by_name: dict[str, Recipe] = {}

    def register(self, name: str, recipe: Recipe) -> Recipe:
        existing = self._by_name.get(name)
        if existing is not None and existing.hash != recipe.hash:
            raise ValueError(f"recipe {name!r} already registered with a different hash")
        self._by_name[name] = recipe
        return recipe

    def get(self, name: str) -> Recipe:
        return self._by_name[name]

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def names(self) -> list[str]:
        return sorted(self._by_name)
