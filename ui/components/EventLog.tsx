"use client";

import { label, type GraphNode, type RederiveEvent } from "@/lib/api";

export default function EventLog({ events, byId }: { events: RederiveEvent[]; byId: Map<string, GraphNode> }) {
  if (events.length === 0) {
    return <p className="empty">Waiting for events. Retract, correct, or delete a record to see the rebuild.</p>;
  }
  return (
    <ul className="events">
      {[...events].reverse().map((e) => {
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
          <li key={e.id}>
            <span>{new Date(e.at).toLocaleTimeString([], { hour12: false })}</span>
            <span className={`s-${e.kind === "cut_off" || e.kind === "skipped" ? "equivalent" : e.kind === "rebuilt" ? "valid" : e.kind}`}>
              {e.kind}
            </span>
            <span>
              {node ? label(node) : e.record_id?.slice(0, 8)} {detail}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
