"use client";

import { useEffect, useRef, useState } from "react";
import { eventsUrl, type RederiveEvent } from "@/lib/api";

const MAX_EVENTS = 300;

/** Subscribes to the live event stream, reconnecting on close. */
export function useEvents(onEvent: (ev: RederiveEvent) => void) {
  const [events, setEvents] = useState<RederiveEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

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
        let ev: RederiveEvent;
        try {
          ev = JSON.parse(msg.data) as RederiveEvent;
        } catch {
          return;
        }
        setEvents((prev) => [...prev.slice(-(MAX_EVENTS - 1)), ev]);
        handler.current(ev);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return { events, connected, clear: () => setEvents([]) };
}
