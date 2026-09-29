import type { Graph } from "./api";

/** All records that transitively derive from `id`. */
export function descendants(graph: Graph, id: string): Set<string> {
  const children = new Map<string, string[]>();
  graph.edges.forEach((e) => children.set(e.parent_id, [...(children.get(e.parent_id) ?? []), e.child_id]));
  const out = new Set<string>();
  const stack = [id];
  while (stack.length) {
    for (const c of children.get(stack.pop()!) ?? []) {
      if (!out.has(c)) {
        out.add(c);
        stack.push(c);
      }
    }
  }
  return out;
}

/** All records that `id` transitively derives from. */
export function ancestors(graph: Graph, id: string): Set<string> {
  const parents = new Map<string, string[]>();
  graph.edges.forEach((e) => parents.set(e.child_id, [...(parents.get(e.child_id) ?? []), e.parent_id]));
  const out = new Set<string>();
  const stack = [id];
  while (stack.length) {
    for (const p of parents.get(stack.pop()!) ?? []) {
      if (!out.has(p)) {
        out.add(p);
        stack.push(p);
      }
    }
  }
  return out;
}
