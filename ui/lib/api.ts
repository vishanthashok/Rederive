export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Status =
  | "valid"
  | "stale"
  | "rebuilding"
  | "retracted"
  | "superseded"
  | "equivalent";

export interface GraphNode {
  id: string;
  version: number;
  kind: string;
  status: Status;
  deleted: boolean;
  text: string;
  content_version: number;
  meta: Record<string, unknown> & { name?: string; topic?: string; partial?: boolean };
}

export interface GraphEdge {
  child_id: string;
  parent_id: string;
  parent_version: number;
  alias: boolean;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Version {
  version: number;
  status: Status;
  content_version: number;
  deleted: boolean;
  created_at: string;
  recipe_hash: string | null;
}

export interface Exposure {
  tool_call_id: string;
  tool_name: string | null;
  at: string;
  record_id: string;
  version: number;
  kind: string;
  read_status: Status;
  read_text: string;
  latest_version: number;
  latest_status: Status;
  latest_text: string;
  state: "valid" | "pending" | "invalid";
}

export interface RebuildJob {
  id: number;
  record_id: string;
  state: string;
  depth: number;
  result: Record<string, unknown>;
}

export interface RederiveEvent {
  id: number;
  kind: string;
  at: string;
  record_id?: string;
  version?: number;
  [key: string]: unknown;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {}
    throw new Error(`${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  graph: () => call<Graph>("/graph"),
  versions: (id: string) => call<Version[]>(`/records/${id}/versions`),
  record: (id: string, version?: number) =>
    call<GraphNode>(`/records/${id}${version ? `?version=${version}` : ""}`),
  lineage: (id: string) =>
    call<{
      root: string;
      nodes: Record<string, GraphNode>;
      edges: { child_id: string; parent_id: string; parent_version: number; alias: boolean; depth: number }[];
    }>(`/records/${id}/lineage`),
  diff: (id: string, from: number, to: number) =>
    call<{ from: GraphNode; to: GraphNode; unified: string[] }>(`/records/${id}/diff?from=${from}&to=${to}`),
  exposure: (staleOnly: boolean) => call<Exposure[]>(`/exposure?stale_only=${staleOnly}`),
  jobs: () => call<{ summary: Record<string, number>; jobs: RebuildJob[] }>("/jobs"),
  retract: (id: string) => call<{ stale_count: number }>(`/records/${id}/retract`, { method: "POST" }),
  correct: (id: string, text: string) =>
    call<{ stale_count: number }>(`/records/${id}/correct`, { method: "POST", body: JSON.stringify({ text }) }),
  remove: (id: string) =>
    call<{ stale_count: number }>(`/records/${id}/delete`, { method: "POST", body: JSON.stringify({}) }),
  recentEvents: (after = 0) => call<{ id: number; kind: string; payload: Record<string, unknown>; at: string }[]>(
    `/events/recent?after=${after}`,
  ),
};

export function eventsUrl(): string {
  return API_URL.replace(/^http/, "ws") + "/events";
}

export function label(n: GraphNode): string {
  const name = (n.meta?.name as string | undefined) ?? `${n.kind} ${n.id.slice(0, 6)}`;
  // Partial summaries in a fan-in tree share their parent's name.
  return n.meta?.partial ? `${name} (part, level ${n.meta.level})` : name;
}
