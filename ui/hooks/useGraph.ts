"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Graph } from "@/lib/api";

/** Loads the graph, tracks loading and error state, and offers a debounced reload. */
export function useGraph() {
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      setGraph(await api.graph());
      setError(null);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // A rebuild cascade emits many events in a burst. Coalesce them into one reload.
  const scheduleLoad = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, 300);
  }, [load]);

  useEffect(() => {
    load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  return { graph, setGraph, loading, error, load, scheduleLoad, version };
}
