"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import EventLog from "@/components/EventLog";
import ExposurePanel from "@/components/ExposurePanel";
import GraphView from "@/components/GraphView";
import RecordPanel from "@/components/RecordPanel";
import { api, eventsUrl, type Graph, type RederiveEvent } from "@/lib/api";

type Tab = "record" | "exposure" | "events";

const FLASH_KINDS = new Set(["stale", "rebuilt", "cut_off", "skipped"]);

export default function Page() {
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("record");
  const [events, setEvents] = useState<RederiveEvent[]>([]);
  const [flashes, setFlashes] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      setGraph(await api.graph());
      setLoadError(null);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setLoadError(String(e));
    }
  }, []);

  const scheduleLoad = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, 200);
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      ws = new WebSocket(eventsUrl());
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 2000);
      };
      ws.onmessage = (msg) => {
        const ev = JSON.parse(msg.data) as RederiveEvent;
        setEvents((prev) => [...prev.slice(-299), ev]);
        const id = ev.record_id;
        if (id) {
          // Apply the status change right away, then reload for the full picture.
          setGraph((g) => ({
            ...g,
            nodes: g.nodes.map((n) =>
              n.id !== id
                ? n
                : {
                    ...n,
                    status:
                      ev.kind === "stale" ? "stale"
                      : ev.kind === "rebuilding" ? "rebuilding"
                      : ev.kind === "retracted" ? "retracted"
                      : ["rebuilt", "cut_off", "skipped"].includes(ev.kind) ? "valid"
                      : n.status,
                  },
            ),
          }));
          if (FLASH_KINDS.has(ev.kind)) {
            setFlashes((f) => ({ ...f, [id]: ev.kind }));
            setTimeout(() => setFlashes((f) => {
              const { [id]: _, ...rest } = f;
              return rest;
            }), 1600);
          }
        }
        scheduleLoad();
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [scheduleLoad]);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    graph.nodes.forEach((n) => (c[n.status] = (c[n.status] ?? 0) + 1));
    return c;
  }, [graph]);
  const rec = selected ? byId.get(selected) ?? null : null;

  const select = (id: string) => {
    setSelected(id);
    setTab("record");
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>Rederive</h1>
        <div className="counts">
          <span><b>{graph.nodes.length}</b> records</span>
          {(["valid", "stale", "rebuilding", "retracted"] as const).map((s) => (
            <span key={s} className={`s-${s}`}>
              <b>{counts[s] ?? 0}</b> {s}
            </span>
          ))}
        </div>
        <button onClick={load}>Reload</button>
        <span className="live">
          <span className={`dot ${connected ? "on" : ""}`} />
          {connected ? "live" : "offline"}
        </span>
      </header>
      <div className="main">
        <div className="graph">
          {loadError ? (
            <p className="empty" style={{ padding: 16 }}>
              Cannot reach the server: {loadError}
            </p>
          ) : (
            <GraphView graph={graph} flashes={flashes} selected={selected} onSelect={select} />
          )}
          <div className="legend">
            <span className="s-valid">valid</span>
            <span className="s-stale">stale</span>
            <span className="s-rebuilding">rebuilding</span>
            <span className="s-equivalent">cut off</span>
            <span className="s-retracted">retracted</span>
            <span>- - alias edge</span>
          </div>
        </div>
        <aside className="side">
          <div className="tabs">
            {(["record", "exposure", "events"] as const).map((t) => (
              <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
                {t === "record" ? "Record" : t === "exposure" ? "Exposure" : `Events (${events.length})`}
              </button>
            ))}
          </div>
          <div className="panel">
            {tab === "record" && <RecordPanel rec={rec} byId={byId} onSelect={select} refreshKey={refreshKey} />}
            {tab === "exposure" && <ExposurePanel byId={byId} onSelect={select} refreshKey={refreshKey} />}
            {tab === "events" && <EventLog events={events} byId={byId} />}
          </div>
        </aside>
      </div>
    </div>
  );
}
