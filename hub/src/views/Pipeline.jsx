import React, { useState } from "react";
import { post } from "../api.js";
import { agentColor, fmtLabel, money } from "../util.js";

// Stages grouped into the five questions you actually ask, stacked so nothing scrolls sideways.
const PHASES = [
  { id: "writing", label: "Research & script", stages: ["idea", "researched", "scripted", "qa_script"] },
  { id: "production", label: "Slides & video", stages: ["storyboarded", "rendered", "qa_video"] },
  { id: "release", label: "Package & release", stages: ["packaged", "awaiting_approval", "scheduled", "published"] },
  { id: "learning", label: "Learning", stages: ["analyzing", "learned"] },
];

export default function Pipeline({ state, openJob }) {
  const [format, setFormat] = useState("all");
  const [phase, setPhase] = useState("all");
  const jobs = Object.values(state.jobs).filter((j) => format === "all" || j.format === format);
  const order = state.stages.map((s) => s.id);
  const labels = Object.fromEntries(state.stages.map((s) => [s.id, s.label]));
  const sorted = (list) => list.slice().sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage) || b.priority - a.priority || a.id - b.id);
  const moving = jobs.filter((j) => j.status === "active" || j.status === "done");
  const groups = [
    { id: "blocked", label: "Needs attention", tone: "alert", jobs: jobs.filter((j) => j.status === "blocked") },
    ...PHASES.map((p) => ({ ...p, jobs: moving.filter((j) => p.stages.includes(j.stage)) })),
  ];
  const rejected = jobs.filter((j) => j.status === "failed");
  // Everything shows only groups with videos in them; the buttons above already show the zeros.
  const shown = groups.filter((g) => (phase === "all" ? g.jobs.length > 0 : g.id === phase));

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Pipeline</h2>
        <div className="head-actions">
          {state.mode === "live" && <NewVideo />}
          <div className="seg" role="group" aria-label="Format">
            {[["all", "All"], ["long", "Long-form"], ["short", "Shorts"]].map(([id, label]) => (
              <button key={id} className={format === id ? "active" : ""} onClick={() => setFormat(id)}>{label}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="phase-nav" role="group" aria-label="Pipeline phase">
        <button className={phase === "all" ? "active" : ""} onClick={() => setPhase("all")}>Everything <span className="mono">{moving.length + groups[0].jobs.length}</span></button>
        {groups.filter((g) => g.id !== "blocked" || g.jobs.length > 0).map((g) => (
          <button key={g.id} className={`${phase === g.id ? "active" : ""} ${g.tone || ""}`} onClick={() => setPhase(g.id)}>
            {g.label} <span className="mono">{g.jobs.length}</span>
          </button>
        ))}
      </div>
      <div className="phases">
        {shown.map((g) => (
          <section key={g.id} className={`phase ${g.tone || ""}`}>
            <h3>{g.label} <span className="muted mono">{g.jobs.length}</span></h3>
            {g.jobs.length === 0 ? (
              <p className="phase-empty">Nothing here right now.</p>
            ) : (
              <div className="job-grid">
                {sorted(g.jobs).map((j) => <JobCard key={j.id} j={j} stageLabel={labels[j.stage]} step={order.indexOf(j.stage)} steps={order.length} onClick={() => openJob(j.id)} />)}
              </div>
            )}
          </section>
        ))}
        {rejected.length > 0 && phase === "all" && (
          <details className="phase rejected">
            <summary>Rejected or failed <span className="muted mono">{rejected.length}</span></summary>
            <div className="job-grid">
              {sorted(rejected).map((j) => <JobCard key={j.id} j={j} stageLabel={labels[j.stage]} onClick={() => openJob(j.id)} />)}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

function NewVideo() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [format, setFormat] = useState("long");
  const [state, setState] = useState(null);
  if (!open) return <button className="btn go" onClick={() => setOpen(true)}>New video</button>;
  const start = (e) => {
    e.preventDefault();
    setState("saving");
    post("/api/ideas", { title, notes, format })
      .then(() => { setOpen(false); setTitle(""); setNotes(""); setState(null); })
      .catch((err) => setState(err.message));
  };
  return (
    <form className="new-video" onSubmit={start}>
      <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What's the video about?" required maxLength={120} /></label>
      <label>What you have in mind (optional)<textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder="The angle, the mood, anything research should know" /></label>
      <div className="seg" role="group" aria-label="New video format">
        {[["long", "Long-form"], ["short", "Short"]].map(([id, label]) => (
          <button type="button" key={id} className={format === id ? "active" : ""} onClick={() => setFormat(id)}>{label}</button>
        ))}
      </div>
      <div className="form-actions">
        <button className="btn go" disabled={!title.trim() || state === "saving"}>{state === "saving" ? "Starting…" : `Start research (about ${format === "long" ? "40" : "15"}¢)`}</button>
        <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {state && state !== "saving" && <p className="error">{state}</p>}
    </form>
  );
}

export function JobCard({ j, onClick, stageLabel, step, steps }) {
  return (
    <button className={`job-card ${j.status}`} onClick={onClick} style={{ "--agent": agentColor(j.working) }}>
      <div className="job-top">
        <span className={`fmt ${j.format}`}>{fmtLabel(j.format)}</span>
        <span className="muted mono">#{j.id}</span>
      </div>
      <div className="job-title">{j.title}</div>
      {stageLabel && <div className="job-stage">{stageLabel}</div>}
      {steps > 0 && (
        <div className="job-progress" role="img" aria-label={`Step ${step + 1} of ${steps}`}>
          <i style={{ width: `${((step + 1) / steps) * 100}%` }} />
        </div>
      )}
      <div className="job-meta">
        <span>{j.series}</span>
        <span className="mono">{money(j.cost)}</span>
      </div>
      {j.working && <div className="job-working"><i /> {j.working} working</div>}
      {j.status === "blocked" && j.note && <div className="job-note">{j.note}</div>}
      {j.attempts > 0 && <div className="job-warn">Retry {j.attempts}</div>}
      {j.priority > 0 && <div className="job-prio">Priority +{j.priority}</div>}
    </button>
  );
}
