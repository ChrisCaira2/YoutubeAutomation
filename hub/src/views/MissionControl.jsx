import React, { useMemo, useState } from "react";
import { post } from "../api.js";
import { agentColor, ago, clock, duration, money, useNow } from "../util.js";
import { creditFor } from "../cast.js";
import Office from "./Office.jsx";

const ORDER = ["showrunner", "research", "script", "qa", "studio", "packaging", "publisher"];
const SHORT = { showrunner: "GM", research: "Scout", script: "Writer", qa: "Ref", studio: "Film room", packaging: "Marketing", publisher: "Analytics", you: "You" };

export default function MissionControl({ studio, openJob, goTo }) {
  const { state, events, handoffs } = studio;
  const now = useNow();
  const [spotlight, setSpotlight] = useState(null);

  const select = (name) => {
    setSpotlight(name);
    document.getElementById(`agent-card-${name}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => setSpotlight((s) => (s === name ? null : s)), 2500);
  };

  return (
    <div className="mission">
      <section className="mission-main">
        <div className="panel office-wrap">
          <div className="panel-head">
            <h2>The front office</h2>
            <span className="muted">Click a staffer for their card or current job, or your desk for approvals. Footballs are handoffs.</span>
          </div>
          <div className="office-scroll">
            <Office state={state} handoffs={handoffs} now={now} openJob={openJob} onSelect={select} onOwner={() => goTo("approvals")} />
          </div>
          {creditFor(state.workspace) && (
            <p className="credit">
              <a href={creditFor(state.workspace).url} target="_blank" rel="noreferrer">{creditFor(state.workspace).text}</a>
            </p>
          )}
          <ul className="handoff-list">
            {handoffs.slice(-5).reverse().map((h) => (
              <li key={h.id}>
                <button className="handoff" onClick={() => openJob(h.job_id)}>
                  <span style={{ color: agentColor(h.details.from) }}>{SHORT[h.details.from] || h.details.from}</span>
                  <span className="muted"> → </span>
                  <span style={{ color: agentColor(h.details.to) }}>{SHORT[h.details.to] || h.details.to}</span>
                  <span className="handoff-what">{h.details.artifact?.replace("_", " ")} · {state.jobs[h.job_id]?.title || `#${h.job_id}`}</span>
                  <span className="muted mono">{ago(h.ts, now)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="agent-grid">
          {ORDER.map((n) => state.agents[n] && <AgentCard key={n} a={state.agents[n]} now={now} openJob={openJob} spotlight={spotlight === n} />)}
        </div>
      </section>
      <aside className="panel feed-panel">
        <LiveFeed events={events} jobs={state.jobs} openJob={openJob} />
      </aside>
    </div>
  );
}

function AgentCard({ a, now, openJob, spotlight }) {
  const working = a.status === "working";
  const canPause = a.name !== "showrunner";
  return (
    <article id={`agent-card-${a.name}`} className={`agent-card ${a.status} ${spotlight ? "spotlight" : ""}`} style={{ "--agent": agentColor(a.name) }}>
      <header>
        <span className={`pulse ${working ? "on" : ""}`} />
        <div className="agent-titles">
          <h3>{a.label}</h3>
          <p>{a.role}</p>
        </div>
        <span className={`status-pill ${a.status}`}>{a.status}</span>
      </header>
      <div className="agent-task">
        {a.task ? (
          <>
            <div className="task-text">{a.task}</div>
            {a.job_id && (
              <button className="link" onClick={() => openJob(a.job_id)}>
                “{a.job_title}”
              </button>
            )}
          </>
        ) : (
          <div className="task-text muted">{a.paused ? "Paused by you" : "Idle"}</div>
        )}
      </div>
      <div className="bar">
        <div style={{ width: `${Math.round((a.progress || 0) * 100)}%` }} />
      </div>
      <dl className="agent-stats">
        <div>
          <dt>On task</dt>
          <dd className="mono">{working && a.started_at ? duration(a.started_at, now) : "—"}</dd>
        </div>
        <div>
          <dt>Heartbeat</dt>
          <dd className="mono">{ago(a.heartbeat, now)}</dd>
        </div>
        <div>
          <dt>Today</dt>
          <dd className="mono">{money(a.cost_today)}</dd>
        </div>
      </dl>
      {canPause && (
        <button className="btn ghost small" onClick={() => post(`/api/agents/${a.name}/${a.paused ? "resume" : "pause"}`)}>
          {a.paused ? "Resume agent" : "Pause agent"}
        </button>
      )}
    </article>
  );
}

const SEVERITIES = ["all", "info", "warn", "error"];
const HIDDEN_BY_DEFAULT = new Set(["progress", "cost", "tool_call"]);

function LiveFeed({ events, jobs, openJob }) {
  const [agent, setAgent] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [job, setJob] = useState("all");
  const [verbose, setVerbose] = useState(false);

  const shown = useMemo(() => {
    return events
      .filter(
        (e) =>
          (verbose || !HIDDEN_BY_DEFAULT.has(e.type)) &&
          (agent === "all" || e.agent === agent) &&
          (severity === "all" || e.severity === severity) &&
          (job === "all" || String(e.job_id) === job),
      )
      .slice(-250)
      .reverse();
  }, [events, agent, severity, job, verbose]);

  const agentsSeen = [...new Set(events.map((e) => e.agent))];
  const jobList = Object.values(jobs).sort((a, b) => b.id - a.id);

  return (
    <>
      <div className="panel-head">
        <h2>Live activity</h2>
      </div>
      <div className="filters">
        <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Filter by agent">
          <option value="all">All agents</option>
          {agentsSeen.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <select value={job} onChange={(e) => setJob(e.target.value)} aria-label="Filter by job">
          <option value="all">All jobs</option>
          {jobList.map((j) => (
            <option key={j.id} value={String(j.id)}>#{j.id} {j.title.slice(0, 32)}</option>
          ))}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Filter by severity">
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s === "all" ? "All severities" : s}</option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={verbose} onChange={(e) => setVerbose(e.target.checked)} /> Tool calls and costs
        </label>
      </div>
      <ol className="feed">
        {shown.map((e) => (
          <li key={e.id} className={`sev-${e.severity}`} style={{ "--agent": agentColor(e.agent) }}>
            <span className="feed-time mono">{clock(e.ts)}</span>
            <span className="feed-dot" />
            <span className="feed-msg">
              {e.message}
              {e.job_id && (
                <button className="link small" onClick={() => openJob(e.job_id)}>#{e.job_id}</button>
              )}
            </span>
          </li>
        ))}
        {shown.length === 0 && <li className="muted">Nothing yet.</li>}
      </ol>
    </>
  );
}
