from rederive import Recipe

SUMMARY = Recipe("Summarize the facts in these inputs.\n{inputs}", params={"fake": {"op": "summarize"}})


def extract(field: str, pattern: str, template: str, default: str = "unknown") -> Recipe:
    return Recipe(
        f"Extract the user's {field}.\n{{inputs}}",
        params={"fake": {"op": "format", "template": template,
                         "fields": {field: {"pattern": pattern, "default": default}}}},
    )


EMPLOYER = extract("employer", r"work(?:s|ing)? (?:at|for) ([A-Z]\w+)", "User works at {employer}.")
TIMEZONE = extract("tz", r"\b(Central|Eastern|Pacific|Mountain) time\b", "User is on {tz} time.")
