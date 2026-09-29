"use client";

import { Crosshair, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import EventLog from "@/components/EventLog";
import ExposurePanel from "@/components/ExposurePanel";
import GraphView from "@/components/GraphView";
import RecordPanel from "@/components/RecordPanel";
import SearchPalette from "@/components/SearchPalette";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useEvents } from "@/hooks/useEvents";
import { useGraph } from "@/hooks/useGraph";
import type { RederiveEvent, Status } from "@/lib/api";
import { COUNTED, LEGEND, STATUS, statusFromEvent } from "@/lib/status";

type Tab = "record" | "exposure" | "events";

const FLASH_KINDS = new Set(["stale", "rebuilt", "cut_off", "skipped"]);

function readRecordParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("record");
}

export default function Page() {
  const { graph, setGraph, loading, error, load, scheduleLoad, version } = useGraph();
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("record");
  const [flashes, setFlashes] = useState<Record<string, string>>({});
  const [hidden, setHidden] = useState<Set<Status>>(new Set());
  const [focus, setFocus] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  const onEvent = useCallback(
    (ev: RederiveEvent) => {
      const id = ev.record_id;
      if (id) {
        // Apply the status change right away, then reload for the full picture.
        const status = statusFromEvent(ev.kind);
        if (status) {
          setGraph((g) => ({ ...g, nodes: g.nodes.map((n) => (n.id === id ? { ...n, status } : n)) }));
        }
        if (FLASH_KINDS.has(ev.kind)) {
          setFlashes((f) => ({ ...f, [id]: ev.kind }));
          setTimeout(
            () =>
              setFlashes((f) => {
                const { [id]: _, ...rest } = f;
                return rest;
              }),
            1600,
          );
        }
      }
      scheduleLoad();
    },
    [setGraph, scheduleLoad],
  );
  const { events, connected, clear } = useEvents(onEvent);

  // Deep link: ?record=<id> selects a record on load, and selection updates the URL.
  useEffect(() => {
    const id = readRecordParam();
    if (id) setSelected(id);
  }, []);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (selected) url.searchParams.set("record", selected);
    else url.searchParams.delete("record");
    window.history.replaceState(null, "", url);
  }, [selected]);

  // Cmd/Ctrl+K toggles search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    graph.nodes.forEach((n) => (c[n.status] = (c[n.status] ?? 0) + 1));
    return c;
  }, [graph]);
  const rec = selected ? byId.get(selected) ?? null : null;

  const select = useCallback((id: string) => {
    setSelected(id);
    setTab("record");
  }, []);

  const toggleHidden = (s: Status) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });

  return (
    <div className="grid h-screen grid-rows-[auto_1fr]">
      <a
        href="#inspector"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-panel focus:px-3 focus:py-1.5"
      >
        Skip to inspector
      </a>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-4 py-2">
        <h1 className="text-base font-semibold tracking-wide">Rederive</h1>
        <div className="flex flex-wrap items-center gap-1 text-sm tabular-nums" role="group" aria-label="Filter by status">
          <span className="mr-1 text-muted">
            <b className="font-semibold text-ink">{graph.nodes.length}</b> records
          </span>
          {COUNTED.map((s) => (
            <button
              key={s}
              aria-pressed={!hidden.has(s)}
              title={hidden.has(s) ? `Show ${s} records` : `Dim ${s} records`}
              onClick={() => toggleHidden(s)}
              className={`rounded-md px-2 py-0.5 transition-opacity hover:bg-bg ${hidden.has(s) ? "opacity-40 line-through" : ""}`}
              style={{ color: STATUS[s].color }}
            >
              <b className="font-semibold">{counts[s] ?? 0}</b> {s}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="default" size="sm" onClick={() => setSearchOpen(true)} className="text-muted">
            <Search aria-hidden /> Search
            <kbd className="ml-2 hidden rounded border border-line px-1 text-[10px] sm:inline">⌘K</kbd>
          </Button>
          <Button variant="ghost" size="icon" onClick={load} aria-label="Reload graph" title="Reload graph">
            <RefreshCw aria-hidden className={loading ? "animate-spin" : ""} />
          </Button>
          <ThemeToggle />
          <span className="ml-1 flex items-center gap-1.5 text-xs text-muted" role="status">
            <span className={`size-2 rounded-full ${connected ? "bg-valid" : "bg-muted"}`} aria-hidden />
            {connected ? "live" : "offline"}
          </span>
        </div>
      </header>

      <div className="grid min-h-0 grid-cols-1 grid-rows-[55vh_1fr] lg:grid-cols-[1fr_440px] lg:grid-rows-1">
        <main className="relative min-h-0" aria-label="Record graph">
          {error ? (
            <div className="grid h-full place-items-center p-4">
              <div role="alert" className="max-w-md rounded-xl border border-line bg-panel p-5 text-center">
                <p className="font-medium">Cannot reach the Rederive server</p>
                <p className="mt-1 break-words text-sm text-muted">{error}</p>
                <Button className="mt-3" onClick={load}>
                  Retry
                </Button>
              </div>
            </div>
          ) : loading && graph.nodes.length === 0 ? (
            <div className="grid h-full place-items-center text-sm text-muted" role="status">
              Loading graph…
            </div>
          ) : graph.nodes.length === 0 ? (
            <div className="grid h-full place-items-center p-4 text-center text-sm text-muted">
              <p>
                No records yet. Run <code className="rounded bg-panel px-1">make demo</code> to seed the support-chat
                scenario.
              </p>
            </div>
          ) : (
            <GraphView
              graph={graph}
              flashes={flashes}
              selected={selected}
              onSelect={select}
              hiddenStatuses={hidden}
              focusSelected={focus}
            />
          )}
          <div className="absolute left-3 top-3 z-[5] flex flex-wrap items-center gap-2.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs">
            {LEGEND.map((s) => {
              const Icon = STATUS[s].icon;
              return (
                <span key={s} className="flex items-center gap-1" style={{ color: STATUS[s].color }}>
                  <Icon aria-hidden className="size-3" />
                  {STATUS[s].label}
                </span>
              );
            })}
            <span className="text-muted">- - alias edge</span>
            <button
              aria-pressed={focus}
              disabled={!selected}
              onClick={() => setFocus((f) => !f)}
              className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 disabled:opacity-40 ${
                focus ? "border-ink text-ink" : "border-line text-muted"
              }`}
              title="Dim records outside the selected record's lineage"
            >
              <Crosshair aria-hidden className="size-3" /> Lineage only
            </button>
          </div>
        </main>

        <aside id="inspector" tabIndex={-1} className="min-h-0 border-t border-line bg-panel lg:border-l lg:border-t-0">
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="grid h-full min-h-0 grid-rows-[auto_1fr]">
            <div className="border-b border-line px-3 py-2">
              <TabsList aria-label="Inspector">
                <TabsTrigger value="record">Record</TabsTrigger>
                <TabsTrigger value="exposure">Exposure</TabsTrigger>
                <TabsTrigger value="events">Events ({events.length})</TabsTrigger>
              </TabsList>
            </div>
            <div className="min-h-0 overflow-auto px-3.5 py-3">
              <TabsContent value="record">
                <RecordPanel rec={rec} graph={graph} byId={byId} onSelect={select} />
              </TabsContent>
              <TabsContent value="exposure">
                <ExposurePanel byId={byId} onSelect={select} refreshKey={version} />
              </TabsContent>
              <TabsContent value="events">
                <EventLog events={events} byId={byId} onSelect={select} onClear={clear} />
              </TabsContent>
            </div>
          </Tabs>
        </aside>
      </div>

      <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} nodes={graph.nodes} onSelect={select} />
    </div>
  );
}
