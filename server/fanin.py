"""Bounded fan-in: summarize many inputs as a tree of partial summaries.

With k inputs per node, retracting one leaf rebuilds one node per level,
about log_k(n) nodes, and each rebuild reads at most k inputs.
"""

from server.db import queries as q
from server.embed import Embedder
from server.llm import LLMProvider


def build_tree(
    conn,
    parents: list[dict],
    recipe: dict,
    rhash: str,
    kind: str,
    meta: dict,
    k: int,
    llm: LLMProvider,
    embedder: Embedder,
) -> dict:
    from server.memory import derive_one

    if k < 2:
        raise ValueError("fan-in k must be at least 2")
    level = 0
    nodes = parents
    partial_ids = []
    while len(nodes) > k:
        level += 1
        next_nodes = []
        for i in range(0, len(nodes), k):
            group = nodes[i : i + k]
            if len(group) == 1:
                next_nodes.append(group[0])
                continue
            out = derive_one(
                conn, group, recipe, rhash, kind,
                {**meta, "partial": True, "level": level}, llm, embedder,
            )
            partial_ids.append(out["id"])
            next_nodes.append(q.get_record(conn, out["id"], out["version"]))
        nodes = next_nodes
    final = derive_one(
        conn, nodes, recipe, rhash, kind,
        {**meta, "fan_in": {"k": k, "leaves": len(parents), "levels": level + 1}},
        llm, embedder,
    )
    return {**final, "partial_ids": partial_ids}
