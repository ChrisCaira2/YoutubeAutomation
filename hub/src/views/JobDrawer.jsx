import React, { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { agentColor, clock, fmtLabel, money } from "../util.js";
import { JobCost } from "./Forecast.jsx";
import ReviewActions, { ScriptReviewActions } from "./ReviewActions.jsx";
import PackageView from "./PackageView.jsx";

const SECTIONS = [
  ["brief", "Brief"],
  ["script", "Script"],
  ["media", "Photos & film"],
  ["storyboard", "Storyboard"],
  ["render", "Render"],
  ["qa", "QA reports"],
  ["package", "Packages"],
  ["cost", "Cost"],
  ["versions", "Versions"],
  ["timeline", "Timeline"],
];

export default function JobDrawer({ jobId, studio, onClose }) {
  const [detail, setDetail] = useState(null);
  const [section, setSection] = useState("script");
  const live = studio.state.jobs[jobId];

  useEffect(() => {
    let alive = true;
    const load = () => get(`/api/jobs/${jobId}`).then((d) => alive && setDetail(d)).catch(() => {});
    load();
    const off = studio.onEvent((e) => e.job_id === jobId && (e.type === "output" || e.type === "stage") && load());
    return () => {
      alive = false;
      off();
    };
  }, [jobId, studio]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const job = live || detail?.job;
  if (!job) return null;
  const latest = (kind) => detail?.artifacts.filter((a) => a.kind === kind).at(-1)?.data;
  const stageLabel = studio.state.stages.find((s) => s.id === job.stage)?.label || job.stage;
  const timeline = detail ? detail.events.concat(studio.events.filter((e) => e.job_id === jobId && e.id > (detail.events.at(-1)?.id || 0))) : [];

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={job.title}>
        <header className="drawer-head">
          <div>
            <span className={`fmt ${job.format}`}>{fmtLabel(job.format)}</span>
            <h2>{job.title}</h2>
            <p className="muted">
              #{job.id} · {job.series} · <b>{stageLabel}</b> · {job.status} · {money(job.cost)}
              {job.working && <> · <span style={{ color: agentColor(job.working) }}>{job.working} working</span></>}
            </p>
            {job.note && <p className="note">Note: {job.note}</p>}
          </div>
          <button className="btn ghost small" onClick={onClose} aria-label="Close">Close</button>
        </header>

        <div className="drawer-actions">
          {job.stage === "awaiting_approval" && job.status === "active" && <ReviewActions job={job} />}
          {job.stage === "scripted" && job.status === "active" && studio.state.settings.manual_script_review && <ScriptReviewActions job={job} />}
          {job.stage === "qa_video" && job.status === "active" && studio.state.mode === "live" && <MakePackage job={job} busy={studio.state.agents.packaging?.status === "working"} />}
          {job.stage === "qa_video" && job.status === "active" && studio.state.mode === "live" && latest("package") && (
            <button className="btn" onClick={() => post(`/api/jobs/${job.id}/reuse_package`, {})}>Keep the existing title and thumbnails (free)</button>
          )}
          {["qa_video", "awaiting_approval", "scheduled"].includes(job.stage) && job.status === "active" && job.format === "long" && studio.state.mode === "live" && <MakeShorts job={job} busy={studio.state.agents.script?.status === "working"} />}
          {["qa_video", "awaiting_approval", "scheduled"].includes(job.stage) && job.status === "active" && studio.state.mode === "live" && <FinalRender job={job} busy={studio.state.agents.studio?.status === "working"} />}
          {(job.status === "blocked" || job.status === "failed") && (
            <button className="btn" onClick={() => post(`/api/jobs/${job.id}/retry`, {})}>Retry from {stageLabel}</button>
          )}
          {job.status === "active" && (
            <div className="prio">
              Priority <b className="mono">{job.priority}</b>
              <button className="btn small ghost" onClick={() => post(`/api/jobs/${job.id}/priority`, { priority: job.priority + 1 })}>Raise</button>
              <button className="btn small ghost" disabled={job.priority <= 0} onClick={() => post(`/api/jobs/${job.id}/priority`, { priority: job.priority - 1 })}>Lower</button>
            </div>
          )}
        </div>

        <nav className="seg wrap drawer-tabs">
          {SECTIONS.map(([id, label]) => (
            <button key={id} className={section === id ? "active" : ""} onClick={() => setSection(id)}>{label}</button>
          ))}
        </nav>

        <div className="drawer-body">
          {!detail && <p className="muted">Loading…</p>}
          {detail && section === "brief" && <Brief b={latest("brief")} />}
          {detail && section === "script" && <Script s={latest("script")} />}
          {detail && section === "media" && <MediaPicker job={job} live={studio.state.mode === "live"} busy={studio.state.agents.studio?.status === "working"} />}
          {detail && section === "storyboard" && <Storyboard sb={latest("storyboard")} job={job} mode={studio.state.mode} />}
          {detail && section === "render" && <Render r={latest("render")} m={latest("asset_manifest")} job={job} mode={studio.state.mode} />}
          {detail && section === "qa" && <QA reports={detail.artifacts.filter((a) => a.kind === "qa_report")} />}
          {detail && section === "package" && <PackageView p={latest("package")} job={job} mode={studio.state.mode} />}
          {detail && section === "cost" && <JobCost job={job} events={timeline} mode={studio.state.mode} />}
          {detail && section === "versions" && <Versions artifacts={detail.artifacts} />}
          {detail && section === "timeline" && <Timeline events={timeline} />}
        </div>
      </aside>
    </div>
  );
}

const Empty = ({ what }) => <p className="empty">No {what} yet.</p>;

function Brief({ b }) {
  if (!b) return <Empty what="brief" />;
  return (
    <div className="stack">
      <p><b>Audience:</b> {b.audience}</p>
      <p><b>Promise:</b> {b.promise}</p>
      <p><b>Angle:</b> {b.angle}</p>
      <h4>Sourced facts</h4>
      <ol>{b.facts.map((f, i) => <li key={i}>{f.claim} — <a href={f.source_url} target="_blank" rel="noreferrer">{f.source_title}</a></li>)}</ol>
      <h4>Candidate hooks</h4>
      <ul>{b.hooks.map((h, i) => <li key={i}>{h}</li>)}</ul>
    </div>
  );
}

function Script({ s }) {
  if (!s) return <Empty what="script" />;
  return (
    <div className="stack">
      <p className="muted">{s.beats.length} beats · about {Math.round(s.target_seconds)} s · {s.originality_statement}</p>
      <div className="table-wrap">
        <table className="beats">
          <thead><tr><th>Beat</th><th>Narration</th><th>On screen</th><th>Visual</th><th>Purpose</th><th>Src</th></tr></thead>
          <tbody>
            {s.beats.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.id}</td>
                <td>{b.narration}</td>
                <td>{b.on_screen_text}</td>
                <td>{b.visual_intent}</td>
                <td><span className={`purpose p-${b.retention_purpose}`}>{b.retention_purpose.replace("_", " ")}</span></td>
                <td className="mono">{b.source_ref ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MakePackage({ job, busy }) {
  const [error, setError] = useState(null);
  return (
    <div>
      <button className="btn go" disabled={busy} onClick={() => post(`/api/jobs/${job.id}/make_package`, {}).catch((e) => setError(e.message))}>
        {busy ? "Packaging is working…" : "Make title and thumbnails (about 4¢)"}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function MakeShorts({ job, busy }) {
  const [error, setError] = useState(null);
  return (
    <div>
      <button className="btn" disabled={busy} onClick={() => post(`/api/jobs/${job.id}/make_shorts`, {}).catch((e) => setError(e.message))}>
        {busy ? "Script is writing…" : "Write 3 Shorts (about 11¢)"}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function FinalRender({ job, busy }) {
  const [error, setError] = useState(null);
  return (
    <div>
      <button className="btn go" disabled={busy} onClick={() => post(`/api/jobs/${job.id}/render_final`, {}).catch((e) => setError(e.message))}>
        {busy ? "Studio is rendering…" : "Render final video (free)"}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function MediaPicker({ job, live, busy }) {
  const [data, setData] = useState(null);
  const [ticked, setTicked] = useState([]);
  const [state, setState] = useState("loading");
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!live) return;
    let alive = true;
    get(`/api/jobs/${job.id}/media`)
      .then((d) => { if (alive) { setData(d); setState("ready"); } })
      .catch((e) => { if (alive) { setError(e.message); setState("ready"); } });
    return () => { alive = false; };
  }, [job.id, live]);

  if (!live) return <p className="empty">Photos and film are found in live mode only.</p>;
  if (state === "loading") return <p className="muted">Searching Wikimedia Commons for the people and places in this video…</p>;
  if (!data) return <p className="error">{error}</p>;

  const toggle = (id) => setTicked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  const add = () => {
    setState("saving");
    setError(null);
    post(`/api/jobs/${job.id}/media`, { ids: ticked })
      .then(() => get(`/api/jobs/${job.id}/media`))
      .then((d) => { setData(d); setTicked([]); setState("ready"); })
      .catch((e) => { setError(e.message); setState("ready"); });
  };
  const list = (kind) => data.candidates.filter((c) => c.kind === kind);
  const size = ticked.reduce((sum, id) => sum + (data.candidates.find((c) => c.id === id)?.size_mb || 0), 0);

  return (
    <div className="stack">
      <p className="muted">Only freely licensed files are shown. Nothing downloads until you add it. The year is on each one, so check it fits the moment. Searched: {data.terms.join(", ")}.</p>
      <p className="media-bar">
        <button className="btn go" disabled={!ticked.length || state === "saving" || busy} onClick={add}>
          {state === "saving" ? "Downloading…" : `Add ${ticked.length} to the video (free${ticked.length ? `, up to ${size.toFixed(1)} MB` : ""})`}
        </button>
      </p>
      {error && <p className="error">{error}</p>}
      {[["photo", "Photos"], ["film", "Film"]].map(([kind, label]) => (
        <section key={kind}>
          <h4>{label} <span className="muted mono">{list(kind).length}</span></h4>
          {!list(kind).length && <p className="muted">None with a free license. Moving diagrams and charts carry these moments instead.</p>}
          <div className="media-grid">
            {list(kind).map((c) => (
              <label key={c.id} className={`media-card ${ticked.includes(c.id) ? "on" : ""}`}>
                <div className="media-thumb">{c.thumb ? <img src={c.thumb} alt={c.caption} loading="lazy" /> : <span>{c.title}</span>}</div>
                <div className="media-text">
                  <input type="checkbox" disabled={c.in_library} checked={c.in_library || ticked.includes(c.id)} onChange={() => toggle(c.id)} />
                  <b>{c.caption}</b>
                  <small>{c.in_library ? "In the library · " : ""}{c.year || "Year unknown"} · {c.license} · {c.size_mb} MB{c.duration ? ` · ${Math.round(c.duration)} s` : ""}</small>
                  <small><a href={c.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{c.author}</a></small>
                </div>
              </label>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function Storyboard({ sb, job, mode }) {
  if (!sb) return <Empty what="storyboard" />;
  return (
    <div className="stack">
      <p className="muted">Style Bible: {sb.style_bible} · {sb.frames.length} frames</p>
      {mode === "live" && <img className="sheet" src={`/api/media/${job.id}/contact-sheet.png?v=${job.updated_at}`} alt="Contact sheet of every storyboard frame" />}
      <div className="contact-sheet">
        {sb.frames.map((f, i) => (
          <figure key={i} className={`frame m-${f.mode}`}>
            <div className="frame-art">{f.mode.replace("_", " ")}</div>
            <figcaption>
              <span className="mono">{f.beat_id} · {Math.round(f.start)}s</span>
              <span>{f.motion}</span>
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

function Render({ r, m, job, mode }) {
  if (!r) return <Empty what="render" />;
  const file = r.preview ? "preview.mp4" : "final.mp4";
  const url = `/api/media/${job.id}/${file}`;
  return (
    <div className="stack">
      {mode === "live" ? (
        <video key={`${file}-${job.updated_at}`} className={`player ${r.height > r.width ? "vertical" : ""}`} src={url} controls preload="metadata" />
      ) : (
        <div className={`player-ph ${r.height > r.width ? "vertical" : ""}`}>
          <span>Preview player</span>
          <small>Mock mode has no real video.</small>
        </div>
      )}
      {mode === "live" && (
        <p>
          <a href={url} download={`job-${job.id}-${file}`}>Download {r.preview ? "preview" : "final video"}</a>
          {" · "}
          <a href={`/api/media/${job.id}/captions.srt`} download={`job-${job.id}-captions.srt`}>Download captions</a>
          {" · "}
          <a href={`/api/media/${job.id}/credits.txt`} download={`job-${job.id}-credits.txt`}>Photo credits for the description</a>
        </p>
      )}
      <p className="mono muted">{r.width}×{r.height} · {r.fps} fps · {Math.round(r.duration_seconds)} s · {r.preview ? "preview" : "final"}</p>
      <p className="mono muted small">{r.path}</p>
      {m && (
        <>
          <h4>Asset manifest</h4>
          <ul>{m.assets.map((a, i) => <li key={i}><b>{a.kind}</b>: {a.source} — {a.license}</li>)}</ul>
        </>
      )}
    </div>
  );
}

function QA({ reports }) {
  if (!reports.length) return <Empty what="QA reports" />;
  return (
    <div className="stack">
      {reports.map((r) => (
        <div key={r.id} className={`qa ${r.data.passed ? "pass" : "fail"}`}>
          <h4>{r.data.gate === "script" ? "QA-1 script" : "QA-2 video"} · v{r.version} · {r.data.passed ? "Passed" : "Sent back"}</h4>
          <ul>{r.data.checks.map((c, i) => <li key={i} className={c.passed ? "" : "bad"}>{c.passed ? "✓" : "✗"} {c.name}{c.note && ` — ${c.note}`}</li>)}</ul>
        </div>
      ))}
    </div>
  );
}

function Versions({ artifacts }) {
  if (!artifacts.length) return <Empty what="artifacts" />;
  return (
    <div className="table-wrap">
      <table className="pb">
        <thead><tr><th>Artifact</th><th>Version</th><th>By</th><th>Saved</th></tr></thead>
        <tbody>
          {artifacts.slice().reverse().map((a) => (
            <tr key={a.id}><td>{a.kind.replace("_", " ")}</td><td className="mono">v{a.version}</td><td style={{ color: agentColor(a.created_by) }}>{a.created_by}</td><td className="mono">{clock(a.created_at)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ events }) {
  return (
    <ol className="feed timeline">
      {events.slice().reverse().map((e) => (
        <li key={e.id} className={`sev-${e.severity}`} style={{ "--agent": agentColor(e.agent) }}>
          <span className="feed-time mono">{clock(e.ts)}</span>
          <span className="feed-dot" />
          <span className="feed-msg">{e.message}</span>
        </li>
      ))}
    </ol>
  );
}
