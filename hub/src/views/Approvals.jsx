import React, { useEffect, useState } from "react";
import { get } from "../api.js";
import { fmtLabel, money } from "../util.js";
import PackageView from "./PackageView.jsx";
import ReviewActions, { ScriptReviewActions } from "./ReviewActions.jsx";

export default function Approvals({ state, openJob }) {
  const jobs = Object.values(state.jobs).filter((j) => j.status === "active").sort((a, b) => a.id - b.id);
  const scripts = state.settings.manual_script_review ? jobs.filter((j) => j.stage === "scripted") : [];
  const videos = jobs.filter((j) => j.stage === "awaiting_approval");
  const done = state.health.manual_approvals;
  const n = state.settings.approve_first_n;

  return (
    <div className="approvals-wrap">
      {state.settings.manual_script_review && (
        <div className="panel">
          <div className="panel-head">
            <h2>Script review</h2>
            <span className="muted">QA-1 is paused: you review scripts. Turn this off in Health & Controls to hand it back to the QA agent.</span>
          </div>
          {scripts.length === 0 && <p className="empty">No scripts waiting on you.</p>}
          <div className="approval-list">
            {scripts.map((j) => <ScriptItem key={j.id} job={j} openJob={openJob} />)}
          </div>
        </div>
      )}
      <div className="panel">
        <div className="panel-head">
          <h2>Video approval</h2>
          <span className="muted">
            {done < n
              ? `You approve the first ${n} videos; ${n - done} manual approval${n - done === 1 ? "" : "s"} left before auto-approve.`
              : `Auto-approve is on (${done} manual approvals done). Change it in Health & Controls.`}
          </span>
        </div>
        {videos.length === 0 && <p className="empty">No finished videos waiting on you.</p>}
        <div className="approval-list">
          {videos.map((j) => <ApprovalItem key={j.id} job={j} openJob={openJob} mode={state.mode} />)}
        </div>
      </div>
    </div>
  );
}

function useDetail(job) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    get(`/api/jobs/${job.id}`).then(setDetail).catch(() => {});
  }, [job.id, job.updated_at]);
  return detail;
}

const latestOf = (detail, kind) => detail?.artifacts.filter((a) => a.kind === kind).at(-1)?.data;

function ScriptItem({ job, openJob }) {
  const detail = useDetail(job);
  const script = latestOf(detail, "script");
  const brief = latestOf(detail, "brief");
  const versions = detail?.artifacts.filter((a) => a.kind === "script").length || 0;

  return (
    <article className="approval">
      <header>
        <div>
          <span className={`fmt ${job.format}`}>{fmtLabel(job.format)}</span>
          <h3>{job.title}</h3>
          <p className="muted">
            {job.series} · spent {money(job.cost)}
            {script && ` · ${script.beats.length} beats · about ${(script.target_seconds / 60).toFixed(1)} min`}
            {versions > 1 && ` · version ${versions}`}
          </p>
        </div>
        <button className="btn ghost small" onClick={() => openJob(job.id)}>Open full detail</button>
      </header>
      {job.note && <p><b>Latest change:</b> {job.note}</p>}
      {script && <p><b>What this video adds:</b> {script.originality_statement}</p>}
      {script && (
        <ol className="script-read">
          {script.beats.map((b) => (
            <li key={b.id}>
              <div className="beat-meta mono">
                {b.id} · {Math.round(b.est_seconds)}s · <span className={`purpose p-${b.retention_purpose}`}>{b.retention_purpose.replace("_", " ")}</span>
                {b.source_ref != null && <> · fact {b.source_ref}</>}
              </div>
              <p className="narration">{b.narration}</p>
              <p className="muted small">On screen: “{b.on_screen_text}” · Visual: {b.visual_intent}</p>
            </li>
          ))}
        </ol>
      )}
      {brief && (
        <details className="facts">
          <summary>Sourced facts the script cites ({brief.facts.length})</summary>
          <ol>
            {brief.facts.map((f, i) => (
              <li key={i}>{f.claim} — <a href={f.source_url} target="_blank" rel="noreferrer">{f.source_title}</a></li>
            ))}
          </ol>
        </details>
      )}
      <ScriptReviewActions job={job} />
    </article>
  );
}

function ApprovalItem({ job, openJob, mode }) {
  const detail = useDetail(job);
  const pkg = latestOf(detail, "package");
  const render = latestOf(detail, "render");
  const qa = detail?.artifacts.filter((a) => a.kind === "qa_report").map((a) => a.data);

  return (
    <article className="approval">
      <header>
        <div>
          <span className={`fmt ${job.format}`}>{fmtLabel(job.format)}</span>
          <h3>{job.title}</h3>
          <p className="muted">{job.series} · cost {money(job.cost)} · {render ? `${Math.round(render.duration_seconds / 6) / 10} min render` : "render pending"}</p>
        </div>
        <button className="btn ghost small" onClick={() => openJob(job.id)}>Open full detail</button>
      </header>
      {job.note && <p><b>Latest change:</b> {job.note}</p>}
      {pkg && <PackageView p={pkg} job={job} mode={mode} />}
      {qa && (
        <p className="muted">
          QA: {qa.filter((r) => r.passed).map((r) => (r.gate === "script" ? "script" : "video")).join(" and ") || "none"} passed
          {qa.some((r) => !r.passed) && ` after ${qa.filter((r) => !r.passed).length} send-back(s)`}.
          AI disclosure: {pkg ? (pkg.ai_disclosure.required ? "required" : "not required") : "—"}.
        </p>
      )}
      <ReviewActions job={job} />
    </article>
  );
}
