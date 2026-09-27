"use client";

import { useEffect, useState } from "react";
import { api, label, type Exposure, type GraphNode } from "@/lib/api";
import { WordDiff } from "./RecordPanel";

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
  const [rows, setRows] = useState<Exposure[]>([]);

  useEffect(() => {
    api.exposure(staleOnly).then(setRows).catch(() => setRows([]));
  }, [staleOnly, refreshKey]);

  const calls = new Map<string, Exposure[]>();
  rows.forEach((r) => calls.set(r.tool_call_id, [...(calls.get(r.tool_call_id) ?? []), r]));

  return (
    <div>
      <div className="actions" style={{ marginTop: 0, marginBottom: 12 }}>
        <button className={staleOnly ? "active" : ""} onClick={() => setStaleOnly(true)}>
          Invalid reads
        </button>
        <button className={!staleOnly ? "active" : ""} onClick={() => setStaleOnly(false)}>
          All reads
        </button>
      </div>
      {calls.size === 0 && (
        <p className="empty">
          {staleOnly ? "No tool call has read a version that is now invalid." : "No tool calls logged yet."}
        </p>
      )}
      {[...calls.entries()].map(([callId, reads]) => (
        <div className="call" key={callId}>
          <div className="head">
            <b>{reads[0].tool_name ?? "tool call"}</b>
            <span>{new Date(reads[0].at).toLocaleTimeString([], { hour12: false })}</span>
          </div>
          <div className="note" style={{ marginTop: 0 }}>{callId}</div>
          {reads.map((r) => {
            const node = byId.get(r.record_id);
            return (
              <div className="read" key={`${r.record_id}@${r.version}`}>
                <div className="row">
                  <button className="link" onClick={() => onSelect(r.record_id)}>
                    {node ? label(node) : r.kind} v{r.version}
                  </button>
                  <span className={`chip s-${r.state}`}>
                    {r.state === "invalid" ? `invalid, now v${r.latest_version}` : r.state}
                  </span>
                </div>
                {r.state !== "valid" && r.read_text !== r.latest_text && (
                  <WordDiff from={r.read_text} to={r.latest_text} />
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
