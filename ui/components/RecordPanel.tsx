"use client";

import { diffWords } from "diff";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/alert-dialog";
import { StatusBadge } from "@/components/ui/status-badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, label, type Graph, type GraphNode, type Version } from "@/lib/api";
import { descendants } from "@/lib/graph";

export function WordDiff({ from, to }: { from: string; to: string }) {
  return (
    <div className="diff">
      {diffWords(from, to).map((part, i) =>
        part.added ? <ins key={i}>{part.value}</ins> : part.removed ? <del key={i}>{part.value}</del> : <span key={i}>{part.value}</span>,
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 mt-4 text-xs font-medium uppercase tracking-wider text-muted">{children}</h3>;
}

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function RecordPanel({
  rec,
  graph,
  byId,
  onSelect,
}: {
  rec: GraphNode | null;
  graph: Graph;
  byId: Map<string, GraphNode>;
  onSelect: (id: string) => void;
}) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [pair, setPair] = useState<[number, number] | null>(null);
  const [texts, setTexts] = useState<[string, string] | null>(null);
  const [parents, setParents] = useState<GraphNode[]>([]);
  const [ancestorCount, setAncestorCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    setEditing(false);
    setPair(null);
    setTexts(null);
  }, [rec?.id]);

  // Refetch when the record changes, gains a version, or changes status.
  useEffect(() => {
    if (!rec) return;
    let live = true;
    setLoadError(null);
    api
      .versions(rec.id)
      .then((vs) => {
        if (!live) return;
        setVersions(vs);
        if (vs.length === 0) return;
        const last = vs[vs.length - 1].version;
        setPair((p) => (p && p[1] <= last ? p : [Math.max(1, last - 1), last]));
      })
      .catch((e) => live && setLoadError(errText(e)));
    api
      .lineage(rec.id)
      .then((lin) => {
        if (!live) return;
        const direct = lin.edges
          .filter((e) => e.depth === 1)
          .map((e) => lin.nodes[`${e.parent_id}@${e.parent_version}`])
          .filter(Boolean);
        setParents(direct);
        setAncestorCount(Object.keys(lin.nodes).length - 1);
      })
      .catch((e) => live && setLoadError(errText(e)));
    return () => {
      live = false;
    };
  }, [rec?.id, rec?.version, rec?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!rec || !pair || pair[0] === pair[1]) {
      setTexts(null);
      return;
    }
    let live = true;
    api
      .diff(rec.id, pair[0], pair[1])
      .then((d) => live && setTexts([d.from.text, d.to.text]))
      .catch(() => live && setTexts(null));
    return () => {
      live = false;
    };
  }, [rec?.id, pair]); // eslint-disable-line react-hooks/exhaustive-deps

  const blast = useMemo(() => (rec ? descendants(graph, rec.id).size : 0), [graph, rec]);

  if (!rec) {
    return (
      <p className="text-sm text-muted">
        Select a node in the graph, or press <kbd className="rounded border border-line px-1 text-xs">⌘K</kbd> to
        search for a record.
      </p>
    );
  }

  const act = async (fn: () => Promise<{ stale_count: number }>, verb: string) => {
    setPending(true);
    try {
      const out = await fn();
      toast.success(`${verb} ${label(rec)}`, {
        description: `${out.stale_count} descendant${out.stale_count === 1 ? "" : "s"} marked stale. Rebuild started.`,
      });
      setEditing(false);
    } catch (e) {
      toast.error(`${label(rec)}: action failed`, { description: errText(e) });
    } finally {
      setPending(false);
    }
  };

  const ancestorsShown = parents.filter((p) => byId.has(p.id));
  const isObservation = rec.kind === "observation";
  const retracted = rec.status === "retracted";
  const blastText = (
    <>
      <b className="text-ink">{blast}</b> derived record{blast === 1 ? "" : "s"} will be marked stale and rebuilt.
    </>
  );

  return (
    <div>
      <h2 className="text-[15px] font-semibold">{label(rec)}</h2>
      <div className="mb-3 mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
        <StatusBadge status={rec.status} />
        <span>{rec.kind}</span>
        <span>v{rec.version}</span>
        {typeof rec.meta?.topic === "string" && <span>topic: {rec.meta.topic}</span>}
        <span className="font-mono" title={rec.id}>
          {rec.id.slice(0, 8)}
        </span>
      </div>

      {!retracted && (
        <div className="flex flex-wrap gap-2">
          <ConfirmDialog
            trigger={
              <Button variant="danger" size="sm" disabled={pending}>
                Retract
              </Button>
            }
            title={`Retract ${label(rec)}?`}
            description={<p>The record stays in history but stops counting as true. {blastText}</p>}
            confirmLabel="Retract"
            onConfirm={() => act(() => api.retract(rec.id), "Retracted")}
          />
          {isObservation && (
            <>
              <Button
                size="sm"
                disabled={pending}
                aria-expanded={editing}
                onClick={() => {
                  setDraft(rec.text);
                  setEditing((v) => !v);
                }}
              >
                Correct
              </Button>
              <ConfirmDialog
                trigger={
                  <Button variant="danger" size="sm" disabled={pending}>
                    Delete
                  </Button>
                }
                title={`Delete ${label(rec)}?`}
                description={<p>The text is erased from every version and cannot be restored. {blastText}</p>}
                confirmLabel="Delete"
                onConfirm={() => act(() => api.remove(rec.id), "Deleted")}
              />
            </>
          )}
        </div>
      )}
      {editing && (
        <form
          className="mt-2"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.correct(rec.id, draft), "Corrected");
          }}
        >
          <label htmlFor="correction" className="mb-1 block text-xs text-muted">
            Corrected text. {blast} derived record{blast === 1 ? "" : "s"} will rebuild.
          </label>
          <textarea
            id="correction"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full rounded-md border border-line bg-bg p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink"
          />
          <div className="mt-2 flex gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={pending || draft.trim() === "" || draft === rec.text}>
              {pending ? "Saving…" : "Save correction"}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {loadError && (
        <p role="alert" className="mt-2 text-xs text-retracted">
          Could not load history: {loadError}
        </p>
      )}

      <Tabs defaultValue="content" className="mt-4">
        <TabsList aria-label="Record details">
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="versions">Versions ({versions.length})</TabsTrigger>
          <TabsTrigger value="lineage">Inputs ({ancestorsShown.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="content">
          <div className="mt-3 whitespace-pre-wrap rounded-md bg-bg px-2.5 py-2">{rec.text}</div>
          {texts && pair && (
            <>
              <SectionTitle>
                Last change, v{pair[0]} → v{pair[1]}
              </SectionTitle>
              <WordDiff from={texts[0]} to={texts[1]} />
            </>
          )}
        </TabsContent>

        <TabsContent value="versions">
          <p className="mt-3 text-xs text-muted">Pick two versions to compare.</p>
          <ol className="mt-2 space-y-1">
            {[...versions].reverse().map((v) => {
              const active = pair && (pair[0] === v.version || pair[1] === v.version);
              return (
                <li key={v.version}>
                  <button
                    aria-pressed={!!active}
                    className={`flex w-full items-center gap-2 rounded-md border px-2 py-1 text-left text-xs transition-colors ${
                      active ? "border-ink bg-bg" : "border-line hover:border-muted"
                    }`}
                    onClick={() =>
                      setPair((p) => {
                        if (!p) return [v.version, v.version];
                        const [, b] = p;
                        return v.version < b ? [v.version, b] : [b, v.version];
                      })
                    }
                  >
                    <b className="w-7">v{v.version}</b>
                    <StatusBadge status={v.status} />
                    <span className="text-muted">{new Date(v.created_at).toLocaleString([], { hour12: false })}</span>
                    {v.recipe_hash && (
                      <span className="ml-auto font-mono text-muted" title={`recipe ${v.recipe_hash}`}>
                        {v.recipe_hash.slice(0, 7)}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
          {texts && pair && (
            <>
              <SectionTitle>
                Diff v{pair[0]} → v{pair[1]}
              </SectionTitle>
              <WordDiff from={texts[0]} to={texts[1]} />
            </>
          )}
        </TabsContent>

        <TabsContent value="lineage">
          {ancestorsShown.length === 0 ? (
            <p className="mt-3 text-sm text-muted">
              {isObservation ? "Observations are sources. They have no inputs." : "No inputs found."}
            </p>
          ) : (
            <>
              <SectionTitle>
                {ancestorsShown.length} direct input{ancestorsShown.length === 1 ? "" : "s"}, {ancestorCount} ancestors in
                total
              </SectionTitle>
              <ul className="space-y-1">
                {ancestorsShown.map((a) => (
                  <li key={`${a.id}@${a.version}`}>
                    <button
                      onClick={() => onSelect(a.id)}
                      title={a.text}
                      className="flex w-full items-center gap-2 rounded-md border border-line px-2 py-1 text-left text-xs hover:border-muted"
                    >
                      <StatusBadge status={byId.get(a.id)?.status ?? a.status} />
                      <span className="font-medium">{label(a)}</span>
                      <span className="text-muted">v{a.version}</span>
                      <span className="ml-auto truncate text-muted">{a.text}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="mt-3 text-xs text-muted">
            {blast} record{blast === 1 ? "" : "s"} derive from this one.
          </p>
        </TabsContent>
      </Tabs>
    </div>
  );
}
