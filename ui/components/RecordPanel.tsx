"use client";

import { diffWords } from "diff";
import { useEffect, useState } from "react";
import { api, label, type GraphNode, type Version } from "@/lib/api";

export function WordDiff({ from, to }: { from: string; to: string }) {
  return (
    <div className="diff">
      {diffWords(from, to).map((part, i) =>
        part.added ? <ins key={i}>{part.value}</ins> : part.removed ? <del key={i}>{part.value}</del> : <span key={i}>{part.value}</span>,
      )}
    </div>
  );
}

export default function RecordPanel({
  rec,
  byId,
  onSelect,
  refreshKey,
}: {
  rec: GraphNode | null;
  byId: Map<string, GraphNode>;
  onSelect: (id: string) => void;
  refreshKey: number;
}) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [pair, setPair] = useState<[number, number] | null>(null);
  const [texts, setTexts] = useState<[string, string] | null>(null);
  const [parents, setParents] = useState<GraphNode[]>([]);
  const [ancestorCount, setAncestorCount] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEditing(false);
    setMessage(null);
    setError(null);
  }, [rec?.id]);

  useEffect(() => {
    if (!rec) return;
    let live = true;
    api.versions(rec.id).then((vs) => {
      if (!live) return;
      setVersions(vs);
      const last = vs[vs.length - 1].version;
      setPair((p) => (p && p[1] <= last ? p : [Math.max(1, last - 1), last]));
    });
    api.lineage(rec.id).then((lin) => {
      if (!live) return;
      const direct = lin.edges
        .filter((e) => e.depth === 1)
        .map((e) => lin.nodes[`${e.parent_id}@${e.parent_version}`])
        .filter(Boolean);
      setParents(direct);
      setAncestorCount(Object.keys(lin.nodes).length - 1);
    });
    return () => {
      live = false;
    };
  }, [rec?.id, rec?.version, rec?.status, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!rec || !pair) return;
    if (pair[0] === pair[1]) {
      setTexts(null);
      return;
    }
    api.diff(rec.id, pair[0], pair[1]).then((d) => setTexts([d.from.text, d.to.text])).catch(() => setTexts(null));
  }, [rec?.id, pair]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!rec) {
    return <p className="empty">Select a node to see its text, versions, and lineage.</p>;
  }

  const act = async (fn: () => Promise<{ stale_count: number }>, verb: string) => {
    setError(null);
    try {
      const out = await fn();
      setMessage(`${verb}. ${out.stale_count} descendant${out.stale_count === 1 ? "" : "s"} marked stale.`);
      setEditing(false);
    } catch (e) {
      setError(String(e));
    }
  };

  const ancestors = parents.filter((p) => byId.has(p.id));
  const isObservation = rec.kind === "observation";
  const retracted = rec.status === "retracted";

  return (
    <div className="record">
      <h2>{label(rec)}</h2>
      <div className="meta">
        <span className={`chip s-${rec.status}`}>{rec.status}</span>
        <span>{rec.kind}</span>
        <span>v{rec.version}</span>
        {typeof rec.meta?.topic === "string" && <span>topic: {rec.meta.topic}</span>}
      </div>
      <div className="body">{rec.text}</div>

      {!retracted && (
        <div className="actions">
          <button className="danger" onClick={() => act(() => api.retract(rec.id), "Retracted")}>
            Retract
          </button>
          {isObservation && (
            <>
              <button
                onClick={() => {
                  setDraft(rec.text);
                  setEditing((v) => !v);
                }}
              >
                Correct
              </button>
              <button className="danger" onClick={() => act(() => api.remove(rec.id), "Deleted")}>
                Delete
              </button>
            </>
          )}
        </div>
      )}
      {editing && (
        <div style={{ marginTop: 8 }}>
          <textarea rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <div className="actions">
            <button onClick={() => act(() => api.correct(rec.id, draft), "Corrected")}>Save correction</button>
          </div>
        </div>
      )}
      {message && <p className="note">{message}</p>}
      {error && <p className="error">{error}</p>}

      <h3>Versions</h3>
      <div className="versions">
        {versions.map((v) => (
          <button
            key={v.version}
            className={pair && (pair[0] === v.version || pair[1] === v.version) ? "active" : ""}
            title={v.status}
            onClick={() =>
              setPair((p) => {
                if (!p) return [v.version, v.version];
                const [, b] = p;
                return v.version < b ? [v.version, b] : [b, v.version];
              })
            }
          >
            v{v.version} <span className={`s-${v.status}`}>{v.status}</span>
          </button>
        ))}
      </div>
      {texts && pair && (
        <>
          <h3>
            Diff v{pair[0]} → v{pair[1]}
          </h3>
          <WordDiff from={texts[0]} to={texts[1]} />
        </>
      )}

      {ancestors.length > 0 && (
        <>
          <h3>
            Inputs ({ancestors.length}), {ancestorCount} ancestors in total
          </h3>
          <div className="versions">
            {ancestors.map((a) => (
              <button key={`${a.id}@${a.version}`} onClick={() => onSelect(a.id)} title={a.text}>
                {label(a)} v{a.version}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
