"use client";

import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, label, type Exposure, type GraphNode } from "@/lib/api";
import { WordDiff } from "./RecordPanel";

const STATE_COLOR: Record<Exposure["state"], string> = {
  valid: "var(--valid)",
  pending: "var(--stale)",
  invalid: "var(--retracted)",
};

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(rows: Exposure[]): string {
  const cols: (keyof Exposure)[] = ["tool_call_id", "tool_name", "at", "record_id", "version", "kind", "state", "latest_version", "read_text", "latest_text"];
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export default function ExposurePanel({
  byId,
  onSelect,
  refreshKey,
}: {
  byId: Map<string, GraphNode>;
  onSelect: (id: string) => void;
  refreshKey: number;
}) {
  const [staleOnly, setStaleOnly] = useState(true);
  const [rows, setRows] = useState<Exposure[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .exposure(staleOnly)
      .then((r) => {
        if (!live) return;
        setRows(r);
        setError(null);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [staleOnly, refreshKey]);

  const calls = useMemo(() => {
    const m = new Map<string, Exposure[]>();
    (rows ?? []).forEach((r) => m.set(r.tool_call_id, [...(m.get(r.tool_call_id) ?? []), r]));
    return m;
  }, [rows]);

  const summary = useMemo(() => {
    const s = { invalid: 0, pending: 0, valid: 0 };
    (rows ?? []).forEach((r) => s[r.state]++);
    return s;
  }, [rows]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Which reads to show" className="inline-flex gap-1 rounded-lg bg-bg p-1">
          {[
            [true, "Invalid reads"],
            [false, "All reads"],
          ].map(([v, text]) => (
            <button
              key={String(v)}
              role="radio"
              aria-checked={staleOnly === v}
              onClick={() => setStaleOnly(v as boolean)}
              className={`rounded-md px-2.5 py-1 text-sm ${staleOnly === v ? "bg-panel text-ink shadow-sm" : "text-muted hover:text-ink"}`}
            >
              {text}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" disabled={!rows?.length} onClick={() => download("exposure.csv", toCsv(rows ?? []), "text/csv")}>
            <Download aria-hidden /> CSV
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!rows?.length}
            onClick={() => download("exposure.json", JSON.stringify(rows, null, 2), "application/json")}
          >
            <Download aria-hidden /> JSON
          </Button>
        </div>
      </div>

      {rows && rows.length > 0 && (
        <dl className="mb-3 grid grid-cols-3 gap-2 text-center">
          {(["invalid", "pending", "valid"] as const).map((k) => (
            <div key={k} className="rounded-lg border border-line px-2 py-1.5">
              <dt className="text-[11px] uppercase tracking-wider text-muted">{k}</dt>
              <dd className="text-lg font-semibold tabular-nums" style={{ color: STATE_COLOR[k] }}>
                {summary[k]}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {error ? (
        <p role="alert" className="text-sm text-retracted">
          Could not load exposure: {error}
        </p>
      ) : rows === null ? (
        <p className="text-sm text-muted" role="status">
          Loading…
        </p>
      ) : calls.size === 0 ? (
        <p className="text-sm text-muted">
          {staleOnly ? "No tool call has read a version that is now invalid." : "No tool calls logged yet."}
        </p>
      ) : null}

      {[...calls.entries()].map(([callId, reads]) => (
        <section className="call mb-2.5 rounded-lg border border-line px-2.5 py-2" key={callId} aria-label={`Tool call ${callId}`}>
          <div className="flex justify-between gap-2 text-xs text-muted">
            <b className="text-ink">{reads[0].tool_name ?? "tool call"}</b>
            <time dateTime={reads[0].at}>{new Date(reads[0].at).toLocaleTimeString([], { hour12: false })}</time>
          </div>
          <div className="truncate font-mono text-[11px] text-muted">{callId}</div>
          {reads.map((r) => {
            const node = byId.get(r.record_id);
            return (
              <div className="mt-2 text-[13px]" key={`${r.record_id}@${r.version}`}>
                <div className="flex items-center justify-between gap-2">
                  <Button variant="link" onClick={() => onSelect(r.record_id)}>
                    {node ? label(node) : r.kind} v{r.version}
                  </Button>
                  <span
                    className="whitespace-nowrap rounded-full border px-2 py-px text-[11px]"
                    style={{ color: STATE_COLOR[r.state], borderColor: STATE_COLOR[r.state] }}
                  >
                    {r.state === "invalid" ? `invalid, now v${r.latest_version}` : r.state}
                  </span>
                </div>
                {r.state !== "valid" && r.read_text !== r.latest_text && (
                  <div className="mt-1">
                    <WordDiff from={r.read_text} to={r.latest_text} />
                  </div>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
