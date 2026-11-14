import React, { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { money } from "../util.js";
import ForecastPanel, { ForecastSummary, useForecast } from "./Forecast.jsx";

export default function Health({ state }) {
  const h = state.health;
  const s = state.settings;
  const pct = Math.min(100, (h.spent_today / (h.daily_budget || 1)) * 100);

  return (
    <div className="health">
      <section className="tiles">
        <Tile label={state.mode === "mock" ? "Forecast today (nothing charged)" : "Spent today"} value={money(h.spent_today)} sub={`of ${money(h.daily_budget)} daily budget`}>
          <div className="bar"><div style={{ width: `${pct}%` }} /></div>
        </Tile>
        <Tile label="In the pipeline" value={h.queue_depth} sub="active jobs" />
        <Tile label="Waiting on you" value={h.awaiting_you} sub="approvals" warn={h.awaiting_you > 0} />
        <Tile label="Blocked" value={h.blocked} sub="jobs needing a retry" warn={h.blocked > 0} />
        <Tile label="Errors today" value={h.errors_today} sub="agent errors" warn={h.errors_today > 0} />
        <Tile label="YouTube quota" value="—" sub="Not used yet: you upload manually" />
      </section>
      <ForecastPanel mode={state.mode} />
      <div className="health-grid">
        <Settings settings={s} />
        <NewJob />
      </div>
      <Blocked state={state} />
    </div>
  );
}

function Tile({ label, value, sub, warn, children }) {
  return (
    <div className={`tile ${warn ? "warn" : ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value mono">{value}</div>
      <div className="tile-sub">{sub}</div>
      {children}
    </div>
  );
}

function Settings({ settings }) {
  const [form, setForm] = useState(settings);
  const [msg, setMsg] = useState(null);
  useEffect(() => setForm(settings), [settings]);

  const save = async (e) => {
    e.preventDefault();
    try {
      await post("/api/settings", {
        daily_budget_usd: Number(form.daily_budget_usd),
        per_video_budget_usd: Number(form.per_video_budget_usd),
        approve_first_n: Number(form.approve_first_n),
        mock_feed: Boolean(form.mock_feed),
        manual_script_review: Boolean(form.manual_script_review),
        tts_voice: form.tts_voice,
      });
      setMsg("Saved.");
    } catch (err) {
      setMsg(err.message);
    }
  };

  return (
    <form className="panel form" onSubmit={save}>
      <h2>Settings</h2>
      <label>Daily budget (USD)<input type="number" step="0.5" min="0" value={form.daily_budget_usd} onChange={(e) => setForm({ ...form, daily_budget_usd: e.target.value })} /></label>
      <label>Per-video budget (USD)<input type="number" step="0.25" min="0" value={form.per_video_budget_usd} onChange={(e) => setForm({ ...form, per_video_budget_usd: e.target.value })} /></label>
      <label>Manual approvals before auto-approve<input type="number" min="0" value={form.approve_first_n} onChange={(e) => setForm({ ...form, approve_first_n: e.target.value })} /></label>
      <label>Narrator voice (free, runs on your Mac)
        <select value={form.tts_voice || "am_michael"} onChange={(e) => setForm({ ...form, tts_voice: e.target.value })}>
          {["am_michael", "am_adam", "am_eric", "am_onyx"].map((v) => <option key={v} value={v}>{v.replace("am_", "").replace(/^./, (c) => c.toUpperCase())}</option>)}
        </select>
      </label>
      <label className="check"><input type="checkbox" checked={!!form.manual_script_review} onChange={(e) => setForm({ ...form, manual_script_review: e.target.checked })} /> I review scripts myself (QA-1 agent paused)</label>
      <label className="check"><input type="checkbox" checked={!!form.mock_feed} onChange={(e) => setForm({ ...form, mock_feed: e.target.checked })} /> Mock mode: keep feeding demo jobs from the backlog</label>
      <button className="btn">Save settings</button>
      {msg && <p className="muted">{msg}</p>}
    </form>
  );
}

function NewJob() {
  const [topics, setTopics] = useState([]);
  const [topic, setTopic] = useState("");
  const [format, setFormat] = useState("long");
  const [priority, setPriority] = useState(1);
  const [msg, setMsg] = useState(null);
  const forecast = useForecast(format);
  useEffect(() => {
    get("/api/topics").then((t) => {
      setTopics(t);
      const first = t.find((x) => x.status === "backlog") || t[0];
      if (first) setTopic(String(first.id));
    });
  }, []);

  const create = async (e) => {
    e.preventDefault();
    try {
      const job = await post("/api/jobs", { topic_id: Number(topic), format, priority: Number(priority) });
      setMsg(`Created job #${job.id}.`);
    } catch (err) {
      setMsg(err.message);
    }
  };

  return (
    <form className="panel form" onSubmit={create}>
      <h2>Start a video</h2>
      <label>Topic
        <select value={topic} onChange={(e) => setTopic(e.target.value)}>
          {topics.map((t) => <option key={t.id} value={t.id}>{t.id}. {t.title} ({t.status})</option>)}
        </select>
      </label>
      <label>Format
        <select value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="long">Long-form (16:9, 8–12 min)</option>
          <option value="short">Short (9:16, 20–45 s)</option>
        </select>
      </label>
      <label>Priority<input type="number" min="0" max="9" value={priority} onChange={(e) => setPriority(e.target.value)} /></label>
      <ForecastSummary forecast={forecast} />
      <button className="btn go">Create job</button>
      {msg && <p className="muted">{msg}</p>}
    </form>
  );
}

function Blocked({ state }) {
  const stuck = Object.values(state.jobs).filter((j) => j.status === "blocked" || j.status === "failed");
  if (!stuck.length) return null;
  return (
    <div className="panel">
      <h2>Blocked and failed jobs</h2>
      <ul className="stuck">
        {stuck.map((j) => (
          <li key={j.id}>
            <span><b>#{j.id} {j.title}</b> <span className="muted">— {j.note}</span></span>
            <button className="btn small" onClick={() => post(`/api/jobs/${j.id}/retry`, {})}>Retry from {j.stage}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
