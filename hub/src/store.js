import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api.js";

const MAX_EVENTS = 600;

// One live copy of the studio: a REST snapshot, then the server-sent event stream.
export function useStudio() {
  const [state, setState] = useState(null);
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [handoffs, setHandoffs] = useState([]);
  const listeners = useRef(new Set());

  const resync = useCallback(async () => {
    const [snap, evs] = await Promise.all([get("/api/state"), get("/api/events?limit=300")]);
    setState({
      ...snap,
      agents: Object.fromEntries(snap.agents.map((a) => [a.name, a])),
      jobs: Object.fromEntries(snap.jobs.map((j) => [j.id, j])),
    });
    setEvents(evs);
    setHandoffs(evs.filter((e) => e.type === "handoff").slice(-12));
  }, []);

  useEffect(() => {
    let es;
    let healthTimer;
    resync().catch(() => {});
    const open = () => {
      es = new EventSource("/api/stream");
      es.onopen = () => {
        setConnected(true);
        resync().catch(() => {});
      };
      es.onerror = () => setConnected(false);
      es.onmessage = (m) => {
        const { kind, data } = JSON.parse(m.data);
        if (kind === "event") {
          setEvents((prev) => {
            const next = prev.concat(data);
            return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
          });
          if (data.type === "handoff") setHandoffs((prev) => prev.concat(data).slice(-12));
          listeners.current.forEach((fn) => fn(data));
        } else if (kind === "agent") {
          setState((s) => s && { ...s, agents: { ...s.agents, [data.name]: data } });
        } else if (kind === "job") {
          setState((s) => s && { ...s, jobs: { ...s.jobs, [data.id]: data } });
        } else if (kind === "settings") {
          setState((s) => s && { ...s, settings: data });
        }
      };
    };
    open();
    healthTimer = setInterval(() => {
      get("/api/health")
        .then((health) => setState((s) => s && { ...s, health }))
        .catch(() => {});
    }, 3000);
    return () => {
      es && es.close();
      clearInterval(healthTimer);
    };
  }, [resync]);

  const onEvent = useCallback((fn) => {
    listeners.current.add(fn);
    return () => listeners.current.delete(fn);
  }, []);

  return { state, events, connected, handoffs, onEvent, resync };
}
