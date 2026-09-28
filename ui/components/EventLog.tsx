"use client";

import { Pause, Play, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { label, type GraphNode, type RederiveEvent } from "@/lib/api";
import { eventColor } from "@/lib/status";

export default function EventLog({
  events,
  byId,
  onSelect,
  onClear,
}: {
  events: RederiveEvent[];
  byId: Map<string, GraphNode>;
  onSelect: (id: string) => void;
  onClear: () => void;
}) {
  const [paused, setPaused] = useState<RederiveEvent[] | null>(null);
  const [kind, setKind] = useState<string>("all");

  const shown = paused ?? events;
  const kinds = useMemo(() => [...new Set(events.map((e) => e.kind))].sort(), [events]);
  const filtered = kind === "all" ? shown : shown.filter((e) => e.kind === kind);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Kind
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="h-7 rounded-md border border-line bg-panel px-1.5 text-xs text-ink"
          >
            <option value="all">all</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setPaused((p) => (p ? null : events))} aria-pressed={!!paused}>
            {paused ? <Play aria-hidden /> : <Pause aria-hidden />}
            {paused ? `Resume (${events.length - paused.length} new)` : "Pause"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={events.length === 0}
            onClick={() => {
              setPaused(null);
              onClear();
            }}
          >
            <Trash2 aria-hidden /> Clear
          </Button>
        </div>
      </div>
      {filtered.length === 0 ? (
        <p className="text-sm text-muted">Waiting for events. Retract, correct, or delete a record to see the rebuild.</p>
      ) : (
        <ul className="text-xs tabular-nums" aria-live="polite" aria-relevant="additions">
          {[...filtered].reverse().map((e) => {
            const node = e.record_id ? byId.get(e.record_id) : undefined;
            const detail =
              e.kind === "cut_off" || e.kind === "rebuilt"
                ? `v${e.version} (${e.method}, sim ${e.similarity})`
                : e.kind === "failed"
                  ? String(e.reason)
                  : e.version !== undefined
                    ? `v${e.version}`
                    : "";
            return (
              <li key={e.id} className="grid grid-cols-[64px_84px_1fr] gap-2 border-b border-line py-1">
                <time className="text-muted" dateTime={e.at}>
                  {new Date(e.at).toLocaleTimeString([], { hour12: false })}
                </time>
                <span style={{ color: eventColor(e.kind) }}>{e.kind}</span>
                <span className="min-w-0 truncate">
                  {e.record_id ? (
                    <button className="underline-offset-2 hover:underline" onClick={() => onSelect(e.record_id!)}>
                      {node ? label(node) : e.record_id.slice(0, 8)}
                    </button>
                  ) : null}{" "}
                  <span className="text-muted">{detail}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
