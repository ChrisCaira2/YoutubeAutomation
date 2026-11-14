import React, { useEffect, useState } from "react";
import { post } from "../api.js";

const TARGET_LABELS = { script: "Script (rewrite)", visuals: "Visuals (re-storyboard and re-render)", package: "Package (titles and thumbnails)" };

// Your script review (in place of QA-1): approve, send back to Script with notes, or reject.
export function ScriptReviewActions({ job, onDone }) {
  const [mode, setMode] = useState(null);
  const [text, setText] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    if (!confirming) return;
    const t = setTimeout(() => setConfirming(false), 4000);
    return () => clearTimeout(t);
  }, [confirming]);

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setMode(null);
      setText("");
      onDone && onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review">
      <div className="review-buttons">
        {confirming ? (
          <button className="btn go active" disabled={busy} onClick={() => act(() => post(`/api/jobs/${job.id}/approve_script`, {}))}>Confirm script approval</button>
        ) : (
          <button className="btn go" onClick={() => { setMode(null); setConfirming(true); }}>Approve script</button>
        )}
        <button className={`btn ${mode === "revise" ? "active" : ""}`} onClick={() => { setConfirming(false); setMode(mode === "revise" ? null : "revise"); }}>Request rewrite</button>
        <button className={`btn stop ${mode === "reject" ? "active" : ""}`} onClick={() => { setConfirming(false); setMode(mode === "reject" ? null : "reject"); }}>Reject</button>
      </div>
      {mode === "revise" && (
        <form className="review-form" onSubmit={(e) => { e.preventDefault(); act(() => post(`/api/jobs/${job.id}/revise_script`, { reason: text })); }}>
          <label>
            What should the Script agent change? (A rewrite costs money; research is reused.)
            <textarea required value={text} onChange={(e) => setText(e.target.value)} placeholder="Open with the 100 on the scoreboard; cut beat b6." />
          </label>
          <button className="btn" disabled={busy || !text.trim()}>Send to Script agent</button>
        </form>
      )}
      {mode === "reject" && (
        <form className="review-form" onSubmit={(e) => { e.preventDefault(); act(() => post(`/api/jobs/${job.id}/reject`, { reason: text })); }}>
          <label>
            Why
            <textarea required value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <button className="btn stop" disabled={busy || !text.trim()}>Reject video</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// Approve, request changes (routed to the right agent), or reject.
export default function ReviewActions({ job, onDone }) {
  const [mode, setMode] = useState(null);
  const [target, setTarget] = useState("script");
  const [text, setText] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // Approving is a two-step click: the queue shifts as items leave, so one stray click must not release a video.
  const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    if (!confirming) return;
    const t = setTimeout(() => setConfirming(false), 4000);
    return () => clearTimeout(t);
  }, [confirming]);

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setMode(null);
      setText("");
      onDone && onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review">
      <div className="review-buttons">
        {confirming ? (
          <button className="btn go active" disabled={busy} onClick={() => act(() => post(`/api/jobs/${job.id}/approve`, {}))}>Confirm approve</button>
        ) : (
          <button className="btn go" onClick={() => { setMode(null); setConfirming(true); }}>Approve</button>
        )}
        <button className={`btn ${mode === "changes" ? "active" : ""}`} onClick={() => { setConfirming(false); setMode(mode === "changes" ? null : "changes"); }}>Request changes</button>
        <button className={`btn stop ${mode === "reject" ? "active" : ""}`} onClick={() => { setConfirming(false); setMode(mode === "reject" ? null : "reject"); }}>Reject</button>
      </div>
      {mode === "changes" && (
        <form className="review-form" onSubmit={(e) => { e.preventDefault(); act(() => post(`/api/jobs/${job.id}/request_changes`, { target, comment: text })); }}>
          <label>
            Send back to
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {Object.entries(TARGET_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>
            What should change
            <textarea required value={text} onChange={(e) => setText(e.target.value)} placeholder="Open on the record number instead of the arena." />
          </label>
          <button className="btn" disabled={busy || !text.trim()}>Send to agent</button>
        </form>
      )}
      {mode === "reject" && (
        <form className="review-form" onSubmit={(e) => { e.preventDefault(); act(() => post(`/api/jobs/${job.id}/reject`, { reason: text })); }}>
          <label>
            Why
            <textarea required value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <button className="btn stop" disabled={busy || !text.trim()}>Reject video</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
