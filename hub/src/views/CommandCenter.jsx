import React, { useEffect, useMemo, useRef, useState } from "react";
import { get, post } from "../api.js";
import { portrait } from "../cast.js";
import { ago, clock, money, useNow } from "../util.js";

// Game Day Brain's home screen: a holographic command center over the studio's real data. The owner's call, 2026-11-09.
const ORDER = ["showrunner", "research", "script", "qa", "studio", "packaging", "publisher"];
const QUIET = new Set(["progress", "cost", "tool_call", "output"]);
const TAG = { error: "ALERT", warn: "WARN" };
const DONE = new Set(["approved", "created", "handoff"]);
const MODELS = [
  ["Claude Opus", "Scripts", "cloud"],
  ["Claude Sonnet", "Research, packaging", "cloud"],
  ["Claude Haiku", "Picture descriptions", "cloud"],
  ["FLUX.1 schnell", "Pictures, on this Mac", "flux"],
  ["Kokoro", "Narrator voice, on this Mac", "local"],
  ["Whisper", "Caption timing, on this Mac", "local"],
];

export default function CommandCenter({ studio, openJob, goTo }) {
  const { state, events } = studio;
  const now = useNow();
  const machine = useMachine();
  const [topics, setTopics] = useState([]);
  useEffect(() => { get("/api/topics").then(setTopics).catch(() => {}); }, [Object.keys(state.jobs).length]);

  const agents = ORDER.map((n) => state.agents[n]).filter(Boolean);
  const working = agents.filter((a) => a.status === "working");
  const jobs = Object.values(state.jobs);
  const active = jobs.filter((j) => j.status === "active" || j.status === "blocked").sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  const labels = Object.fromEntries(state.stages.map((s) => [s.id, s.label]));
  const order = state.stages.map((s) => s.id);
  const h = state.health;
  const paused = state.settings.paused;
  const budget = h.daily_budget ? Math.round((h.spent_today / h.daily_budget) * 100) : 0;
  const feed = useMemo(() => events.filter((e) => !QUIET.has(e.type)).slice(-9).reverse(), [events]);

  return (
    <div className="cc">
      <section className="cc-panel cc-overview">
        <h2 className="cc-title">Core overview</h2>
        <ul className="cc-rows">
          <Row icon="core" label="Studio" value={paused ? "Paused" : "Online"} tone={paused ? "warn" : "ok"} />
          <Row icon="agents" label="Agents" value={working.length ? `${working.length} working` : "Standing by"} tone={working.length ? "ok" : "idle"} />
          <Row icon="flow" label="Pipeline" value={`${active.length} in production`} tone="idle" />
          <Row icon="inbox" label="Your review" value={h.awaiting_you ? `${h.awaiting_you} waiting` : "Clear"} tone={h.awaiting_you ? "warn" : "ok"} />
          <Row icon="coin" label="Budget" value={`${money(h.spent_today)} of ${money(h.daily_budget)}`} tone={budget >= 90 ? "warn" : "ok"} />
          <Row icon="eye" label="Image model" value={machine?.image_model ? "FLUX ready" : "Not installed"} tone={machine?.image_model ? "ok" : "warn"} />
          {h.blocked > 0 && <Row icon="alert" label="Blocked" value={`${h.blocked} need you`} tone="bad" />}
        </ul>
      </section>

      <section className="cc-core" aria-label={`Game Day Brain core: ${paused ? "paused" : working.length ? `${working.length} agents working` : "standing by"}`}>
        <Hologram busy={working.length > 0 && !paused} />
        <div className="cc-core-text">
          <div className="cc-core-name">{state.channel}</div>
          <div className="cc-core-sub">AI core</div>
          <div className="cc-core-status mono">{paused ? "Paused" : working.length ? working.map((a) => a.label).join(" · ") : "Standing by"}</div>
        </div>
      </section>

      <section className="cc-panel cc-feed">
        <h2 className="cc-title">Live intelligence feed <span className="cc-live">Live</span></h2>
        <ol className="cc-feed-list">
          {feed.map((e) => (
            <li key={e.id} className={`sev-${e.severity}`}>
              <button className="cc-feed-item" onClick={() => e.job_id && openJob(e.job_id)} disabled={!e.job_id}>
                <span className="cc-feed-msg">{e.message}</span>
                <span className="cc-feed-meta mono">{clock(e.ts)} · {e.agent}</span>
              </button>
              <span className={`cc-tag ${e.severity}`}>{TAG[e.severity] || (DONE.has(e.type) ? "DONE" : "INFO")}</span>
            </li>
          ))}
          {feed.length === 0 && <li className="muted">Quiet so far today.</li>}
        </ol>
      </section>

      <PictureProgress studio={studio} now={now} openJob={openJob} />

      <section className="cc-panel cc-agents">
        <h2 className="cc-title">Active agents</h2>
        <div className="cc-agent-grid">
          {agents.map((a) => (
            <button key={a.name} className={`cc-agent ${a.status}`} onClick={() => a.job_id && openJob(a.job_id)} style={{ "--agent": `var(--c-${a.name})` }}>
              <img src={portrait(a.name, a.status, state.workspace)} alt="" />
              <span className="cc-agent-text">
                <b>{a.label}</b>
                <small className={a.status}>{a.paused ? "Paused" : a.status === "working" ? (a.task || "Working") : a.status}</small>
              </span>
              <i className="cc-agent-bar" style={{ width: `${Math.round((a.progress || 0) * 100)}%` }} />
            </button>
          ))}
        </div>
      </section>

      <section className="cc-panel cc-timeline">
        <h2 className="cc-title">Mission timeline</h2>
        <ol className="cc-missions">
          {active.slice(0, 6).map((j) => (
            <li key={j.id}>
              <button onClick={() => openJob(j.id)} className={j.status}>
                <span className="mono cc-when">{ago(j.updated_at, now)}</span>
                <span className="cc-mission-title">{j.title}</span>
                <span className="cc-mission-stage">{j.status === "blocked" ? "Blocked" : labels[j.stage]}</span>
                <i className="cc-mission-bar"><em style={{ width: `${((order.indexOf(j.stage) + 1) / order.length) * 100}%` }} /></i>
              </button>
            </li>
          ))}
          {active.length === 0 && <li className="muted cc-empty">No missions running. Pitch one below, or start an idea from the backlog.</li>}
        </ol>
        <button className="cc-link" onClick={() => goTo("pipeline")}>View full pipeline ›</button>
      </section>

      <section className="cc-panel cc-commands">
        <h2 className="cc-title">Quick commands</h2>
        <div className="cc-command-list">
          <button onClick={() => document.getElementById("cc-pitch")?.focus()}><Glyph name="plus" /> New video</button>
          <button onClick={() => goTo("approvals")}><Glyph name="inbox" /> Review approvals{h.awaiting_you > 0 && <span className="cc-count">{h.awaiting_you}</span>}</button>
          <button onClick={() => goTo("health")}><Glyph name="flow" /> Backlog and controls</button>
          <button onClick={() => post(`/api/control/${paused ? "resume" : "pause"}`)} className={paused ? "go" : "stop"}><Glyph name="core" /> {paused ? "Resume studio" : "Pause studio"}</button>
        </div>
      </section>

      <section className="cc-panel cc-monitor">
        <h2 className="cc-title">System monitor</h2>
        <div className="cc-rings">
          <Ring label="CPU" value={machine?.cpu} />
          <Ring label="Memory" value={machine?.memory} />
          <Ring label="Disk" value={machine?.disk} note={machine ? `${machine.disk_free_gb} GB free` : ""} />
          <Ring label="Budget" value={budget} note={money(h.spent_today)} />
        </div>
      </section>

      <section className="cc-panel cc-memory">
        <h2 className="cc-title">Idea constellation</h2>
        <div className="cc-memory-body">
          <Constellation topics={topics} />
          <dl className="cc-stats">
            <div><dt>Ideas waiting</dt><dd className="mono">{topics.filter((t) => t.status === "backlog").length}</dd></div>
            <div><dt>Videos made</dt><dd className="mono">{jobs.length}</dd></div>
            <div><dt>Approved</dt><dd className="mono">{jobs.filter((j) => ["scheduled", "published"].includes(j.stage)).length}</dd></div>
          </dl>
        </div>
      </section>

      <section className="cc-panel cc-models">
        <h2 className="cc-title">Model status</h2>
        <ul className="cc-model-grid">
          {MODELS.map(([name, job, kind]) => {
            const ready = kind !== "flux" || machine?.image_model;
            return (
              <li key={name}>
                <span className={`cc-dot ${ready ? "ok" : "warn"}`} />
                <span><b>{name}</b><small>{job}</small></span>
                <span className={`cc-kind ${kind === "cloud" ? "cloud" : "local"}`}>{kind === "cloud" ? "Pay per use" : ready ? "Free" : "Missing"}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <Pitch />
    </div>
  );
}

function useMachine() {
  const [machine, setMachine] = useState(null);
  useEffect(() => {
    const load = () => get("/api/system").then(setMachine).catch(() => {});
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);
  return machine;
}

function Row({ icon, label, value, tone }) {
  return (
    <li className="cc-row">
      <span className="cc-row-icon"><Glyph name={icon} /></span>
      <span className="cc-row-text"><b>{label}</b><small className={tone}>{value}</small></span>
    </li>
  );
}

function Glyph({ name }) {
  const paths = {
    core: <><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="8.5" strokeDasharray="3 3" /></>,
    agents: <><rect x="6" y="7" width="12" height="10" rx="2" /><path d="M9 11h.01M15 11h.01M12 4v3M9 17v3M15 17v3" /></>,
    flow: <><path d="M4 7h10M4 12h16M4 17h7" /><circle cx="18" cy="7" r="2" /><circle cx="15" cy="17" r="2" /></>,
    inbox: <><path d="M4 13l2.5-7h11L20 13v5H4z" /><path d="M4 13h5l1 2h4l1-2h5" /></>,
    coin: <><circle cx="12" cy="12" r="8" /><path d="M14.5 9.5c-.5-1-1.5-1.5-2.5-1.5-1.7 0-2.5 1-2.5 2s1 1.6 2.5 2 2.5 1 2.5 2-1 2-2.5 2c-1.2 0-2-.6-2.5-1.5M12 6.5v11" /></>,
    eye: <><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" /><circle cx="12" cy="12" r="2.5" /></>,
    alert: <><path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17h.01" /></>,
    plus: <><circle cx="12" cy="12" r="8.5" /><path d="M12 8v8M8 12h8" /></>,
  };
  return <svg viewBox="0 0 24 24" className="cc-glyph" aria-hidden="true">{paths[name]}</svg>;
}

export function Ring({ label, value, note }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.min(value, 100);
  return (
    <figure className={`cc-ring ${v >= 85 ? "hot" : ""}`}>
      <svg viewBox="0 0 80 80" role="img" aria-label={`${label} ${value ?? "unknown"}%`}>
        <circle cx="40" cy="40" r={r} className="cc-ring-track" />
        <circle cx="40" cy="40" r={r} className="cc-ring-fill" strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 40 40)" />
        <text x="40" y="45" textAnchor="middle" className="cc-ring-value">{value == null ? "—" : `${value}%`}</text>
      </svg>
      <figcaption>{label}{note && <small>{note}</small>}</figcaption>
    </figure>
  );
}

// The holographic core: a wireframe globe whose meridians turn, with orbit rings and a scan line.
function Hologram({ busy }) {
  const meridians = [0, 1, 2, 3, 4, 5];
  const latitudes = [-60, -30, 0, 30, 60];
  return (
    <svg className={`cc-holo ${busy ? "busy" : ""}`} viewBox="0 0 400 400" aria-hidden="true">
      <defs>
        <radialGradient id="cc-orb" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#3ee7ff" stopOpacity="0.32" />
          <stop offset="60%" stopColor="#0a6fa8" stopOpacity="0.14" />
          <stop offset="100%" stopColor="#02121f" stopOpacity="0" />
        </radialGradient>
        <filter id="cc-glow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="2.4" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <ellipse cx="200" cy="330" rx="150" ry="22" className="cc-holo-base" />
      <ellipse cx="200" cy="330" rx="105" ry="14" className="cc-holo-base inner" />
      <circle cx="200" cy="190" r="120" fill="url(#cc-orb)" />
      <g filter="url(#cc-glow)" className="cc-holo-wire">
        <circle cx="200" cy="190" r="120" />
        {latitudes.map((lat) => {
          const y = 190 + 120 * Math.sin((lat * Math.PI) / 180);
          const rx = 120 * Math.cos((lat * Math.PI) / 180);
          return <ellipse key={lat} cx="200" cy={y} rx={rx} ry={rx * 0.16} />;
        })}
        {meridians.map((k) => (
          <ellipse key={k} cx="200" cy="190" rx="120" ry="120">
            <animate attributeName="rx" values="120;0;120" dur="9s" begin={`${-k * 1.5}s`} repeatCount="indefinite" />
          </ellipse>
        ))}
      </g>
      <g className="cc-holo-orbit slow"><ellipse cx="200" cy="190" rx="175" ry="52" /><circle cx="375" cy="190" r="4" /></g>
      <g className="cc-holo-orbit fast"><ellipse cx="200" cy="190" rx="155" ry="150" strokeDasharray="2 10" /><circle cx="200" cy="40" r="3.5" /></g>
      <line x1="80" x2="320" y1="190" y2="190" className="cc-holo-scan" />
      {[...Array(18)].map((_, i) => {
        const a = (i / 18) * Math.PI * 2;
        return <circle key={i} cx={200 + Math.cos(a) * (140 + (i % 3) * 18)} cy={190 + Math.sin(a) * (70 + (i % 4) * 22)} r={i % 4 === 0 ? 2.2 : 1.3} className="cc-holo-spark" style={{ animationDelay: `${(i % 6) * 0.4}s` }} />;
      })}
    </svg>
  );
}

// Each backlog idea is a star; nearby ones join up. Hover a star for its title.
function Constellation({ topics }) {
  const stars = useMemo(() => topics.slice(0, 40).map((t, i) => {
    const seed = Math.sin((t.id + 1) * 12.9898) * 43758.5453;
    const r = seed - Math.floor(seed);
    const s2 = Math.sin((t.id + 7) * 78.233) * 12543.21;
    const q = s2 - Math.floor(s2);
    return { id: t.id, title: t.title, done: t.status !== "backlog", x: 12 + r * 196, y: 12 + q * 96, big: i % 5 === 0 };
  }), [topics]);
  const lines = [];
  stars.forEach((a, i) => stars.slice(i + 1).forEach((b) => {
    if (Math.hypot(a.x - b.x, a.y - b.y) < 46) lines.push([a, b]);
  }));
  return (
    <svg className="cc-constellation" viewBox="0 0 220 120" role="img" aria-label={`${stars.length} ideas in the backlog`}>
      {lines.map(([a, b]) => <line key={`${a.id}-${b.id}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />)}
      {stars.map((s) => (
        <circle key={s.id} cx={s.x} cy={s.y} r={s.big ? 2.8 : 1.9} className={s.done ? "done" : ""}>
          <title>{s.title}</title>
        </circle>
      ))}
    </svg>
  );
}

// The command bar: pitch a video in one line. Research costs money, so it always asks before starting.
function Pitch() {
  const [text, setText] = useState("");
  const [format, setFormat] = useState("long");
  const [step, setStep] = useState("idle");
  const [error, setError] = useState(null);
  const send = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    if (step !== "confirm") return setStep("confirm");
    setStep("saving");
    post("/api/ideas", { title: text.trim(), notes: "", format })
      .then(() => { setText(""); setStep("sent"); setError(null); setTimeout(() => setStep("idle"), 3000); })
      .catch((err) => { setError(err.message); setStep("idle"); });
  };
  return (
    <form className={`cc-pitch ${step}`} onSubmit={send}>
      <span className="cc-wave" aria-hidden="true">{[...Array(14)].map((_, i) => <i key={i} style={{ animationDelay: `${(i % 7) * 0.12}s` }} />)}</span>
      <label className="cc-pitch-field">
        <span>Pitch Game Day Brain</span>
        <input id="cc-pitch" value={text} onChange={(e) => { setText(e.target.value); setStep("idle"); }} placeholder="Why do fans cry when their team wins?" maxLength={120} />
      </label>
      <div className="cc-pitch-actions">
        <div className="seg" role="group" aria-label="Format">
          {[["long", "Long"], ["short", "Short"]].map(([id, label]) => (
            <button type="button" key={id} className={format === id ? "active" : ""} onClick={() => setFormat(id)}>{label}</button>
          ))}
        </div>
        {step === "confirm" ? (
          <>
            <button className="btn go">Start research, about {format === "long" ? "40" : "15"}¢</button>
            <button type="button" className="btn ghost" onClick={() => setStep("idle")}>Cancel</button>
          </>
        ) : (
          <button className="btn cc-send" disabled={!text.trim() || step === "saving"}>{step === "saving" ? "Sending…" : step === "sent" ? "Sent to the studio" : "Send"}</button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

// How far FLUX has got with a video's pictures. The Studio reports "Drawing pictures: 12 of 99" in its task;
// a server started before that existed only reports its progress bar, so the count is worked out from that
// and the "99 pictures to draw" event (the Studio's steps are one per picture, plus one before and one after).
export function pictureProgress(agent, events) {
  if (!agent || agent.status !== "working") return null;
  const said = /Drawing pictures: (\d+) of (\d+)/.exec(agent.task || "");
  const planned = [...events].reverse().find((e) => e.agent === "studio" && e.job_id === agent.job_id && /(\d+) pictures to draw/.test(e.message));
  const began = [...events].reverse().find((e) => e.agent === "studio" && e.job_id === agent.job_id && e.message.startsWith("Drawing the pictures"));
  if (!said && !(planned && began && agent.task === "Building the storyboard")) return null;
  const total = said ? Number(said[2]) : Number(/(\d+) pictures to draw/.exec(planned.message)[1]);
  const done = said ? Number(said[1]) : Math.min(Math.max(Math.round(agent.progress * (total + 2)) - 1, 0), total);
  return { done, total, began: began?.ts };
}

function PictureProgress({ studio, now, openJob }) {
  const agent = studio.state.agents.studio;
  const p = pictureProgress(agent, studio.events);
  const each = usePace(p, now);
  if (!p || p.total === 0) return null;
  const left = p.total - p.done;
  const minutes = Math.max(1, Math.round((left * each) / 60));
  const share = Math.round((p.done / p.total) * 100);
  return (
    <section className="cc-panel cc-forge" aria-label={`Drawing pictures: ${p.done} of ${p.total}`}>
      <h2 className="cc-title">
        Picture forge
        <button className="cc-link" onClick={() => openJob(agent.job_id)}>{agent.job_title}</button>
      </h2>
      <div className="cc-forge-row">
        <div className="cc-forge-count"><b className="mono">{p.done}</b><span>of {p.total} drawn</span></div>
        <div className="cc-forge-track" role="progressbar" aria-valuemin={0} aria-valuemax={p.total} aria-valuenow={p.done}>
          <i style={{ width: `${share}%` }} />
          <span className="mono">{share}%</span>
        </div>
        <div className="cc-forge-left">
          <b className="mono">{left}</b><span>left · about {minutes} min</span>
        </div>
      </div>
    </section>
  );
}

// Seconds per picture, measured between pictures this page has seen finish. The model takes a couple of minutes
// to load before the first one, so time since the start would overstate it. About 40 s until there's a measurement.
function usePace(p, now) {
  const first = useRef(null);
  if (!p) { first.current = null; return 40; }
  if (!first.current || p.done < first.current.done) first.current = { done: p.done, at: now, anchored: false };
  if (!first.current.anchored && p.done > first.current.done) first.current = { done: p.done, at: now, anchored: true };  // start timing as a picture finishes
  const pictures = p.done - first.current.done;
  return first.current.anchored && pictures >= 1 ? (now - first.current.at) / 1000 / pictures : 40;
}
