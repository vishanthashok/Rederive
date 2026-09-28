"""Recipes for the demo agent.

Each recipe carries a real prompt template (used with REDERIVE_LLM=anthropic)
and a `fake` spec so the offline provider produces deterministic output.
"""

from rederive import Recipe, RecipeRegistry

registry = RecipeRegistry()


def summary(topic: str) -> Recipe:
    return registry.register(
        f"summary:{topic}",
        Recipe(
            f"Summarize what the user said about {topic}. One sentence per fact.\n{{inputs}}",
            params={"fake": {"op": "summarize"}},
        ),
    )


def fact(name: str, question: str, pattern: str, template: str, default: str = "unknown") -> Recipe:
    return registry.register(
        f"fact:{name}",
        Recipe(
            f"{question} Answer in one sentence of the form: {template.format(value='<value>')} "
            f"If the inputs conflict, use the most recent statement. "
            f"If the inputs do not say, use {default!r}.\n{{inputs}}",
            params={"fake": {"op": "format", "template": template,
                             "fields": {"value": {"pattern": pattern, "default": default}}}},
        ),
    )


def select(name: str, instruction: str, pattern: str, empty: str) -> Recipe:
    return registry.register(
        f"select:{name}",
        Recipe(
            f"{instruction} List each as its own sentence. If none, say: {empty}\n{{inputs}}",
            params={"fake": {"op": "select", "pattern": pattern, "empty": empty}},
        ),
    )


def procedure(name: str, instruction: str, fields: dict[str, tuple[str, str]], template: str) -> Recipe:
    return registry.register(
        f"procedure:{name}",
        Recipe(
            f"{instruction}\n{{inputs}}",
            params={"fake": {"op": "format", "template": template,
                             "fields": {k: {"pattern": p, "default": d} for k, (p, d) in fields.items()}}},
        ),
    )


PROFILE = registry.register(
    "profile",
    Recipe("Write a short customer profile from these facts. One sentence per fact.\n{inputs}",
           params={"fake": {"op": "summarize"}}),
)
