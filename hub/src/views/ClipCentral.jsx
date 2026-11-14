import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { get, post } from "../api.js";
import { money, useNow } from "../util.js";
import { Ring } from "./CommandCenter.jsx";

const MOMENT_LABELS = { glitch_chaos: "Glitch & chaos", chase_shootout: "Chase & shootout", reaction: "Reaction", story_reveal: "Story & reveal", other: "Other" };
const PLATFORM = { twitch: "Twitch", youtube: "YouTube", kick: "Kick" };

// GTA 6 Clip Central: the Jarvis look, cut down to what the clipper needs. One screen, five panels, no sidebar.
export default function ClipCentral() {
  const [state, setState] = useState(null);
  const [offline, setOffline] = useState(false);
  const refresh = useCallback(() => get("/api/state").then((s) => { setState(s); setOffline(false); }).catch(() => setOffline(true)), []);
  useEffect(() => {
    document.body.classList.add("theme-cc");
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);
  if (!state) return <div className="boot"><p>Connecting to GTA 6 Clip Central…</p></div>;

  return (
    <div className="app gc-app">
      <header className="top">
        <div className="brand">
          <div className="brand-mark ws-clips">G6</div>
          <div>
            <div className="brand-name">{state.channel}</div>
            <div className="brand-sub">Clip command</div>
          </div>
        </div>
        <Clock />
        <nav className="seg workspaces" aria-label="Studio">
          {state.workspaces.map((w) => (w.current
            ? <span key={w.id} className="active" aria-current="page">{w.label}</span>
            : <a key={w.id} href={w.url}>{w.label}</a>))}
        </nav>
        <div className="top-stats">
          {state.recordings.length > 0 && <span className="gc-rec-pill" title="Streams being recorded right now">● REC {state.recordings.length}</span>}
          <span className={`live ${offline ? "" : "on"}`}><i /> {offline ? "Reconnecting" : "Live"}</span>
          <span className="top-stat"><b className="mono">{money(state.spend.month)}</b> of {money(state.spend.cap)} this month</span>
        </div>
      </header>

      <main className="gc">
        <PipelinePanel state={state} />
        <LivePanel state={state} onChange={setState} />
        <MomentsPanel state={state} onChange={setState} />
        <SystemPanel state={state} />
        <SchedulePanel state={state} />
      </main>
    </div>
  );
}

function Clock() {
  const now = new Date(useNow());
  return (
    <div className="cc-clock" aria-label="Current time">
      <span>{now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</span>
      <b className="mono">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</b>
    </div>
  );
}

function Panel({ area, title, extra, children }) {
  return (
    <section className={`cc-panel gc-${area}`} aria-label={title}>
      <h2 className="cc-title"><span>{title}</span>{extra}</h2>
      {children}
    </section>
  );
}

function PipelinePanel({ state }) {
  return (
    <Panel area="pipeline" title="Pipeline" extra={<span className="gc-task">{state.task}</span>}>
      <ol className="gc-stages">
        {state.stages.map((s) => (
          <li key={s.id} className={s.milestone ? "later" : s.count ? "on" : ""}>
            <b className="mono">{s.milestone ? "—" : s.count}</b>
            <span>{s.label}</span>
            {s.milestone && <small>milestone {s.milestone}</small>}
          </li>
        ))}
      </ol>
    </Panel>
  );
}

function LivePanel({ state, onChange }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const act = async (path, body) => {
    setBusy(true);
    setError(null);
    try { onChange(await post(path, body)); return true; } catch (e) { setError(e.message); return false; } finally { setBusy(false); }
  };
  const toggle = () => {
    if (!state.automation && !window.confirm("Turn automation on? Watched creators get recorded whenever they go live with GTA (about 1.5 GB an hour), and Claude judges the moments it finds, within the monthly cap.")) return;
    act("/api/clips/automation", { on: !state.automation });
  };
  const record = async (e) => {
    e.preventDefault();
    if (url.trim() && (await act("/api/clips/record", { url: url.trim() }))) setUrl("");
  };
  return (
    <Panel area="live" title="Live" extra={state.recordings.length > 0 && <span className="cc-live">REC {state.recordings.length}</span>}>
      <Recordings state={state} busy={busy} act={act} />
      <div className="gc-auto">
        <span title="Records watched creators when they go live with GTA">Watch list <b className={state.automation ? "on" : ""}>{state.automation ? "on" : "off"}</b></span>
        <button className={`btn ${state.automation ? "stop" : "go"}`} onClick={toggle} disabled={busy}>{state.automation ? "Turn off" : "Turn on"}</button>
      </div>
      <ul className="gc-creators">
        {state.creators.map((c) => {
          const status = c.recording ? ["rec", "Recording"] : c.live ? [c.gta ? "live" : "idle", c.gta ? "Live with GTA" : "Live, not GTA"]
            : c.live === false ? ["idle", "Offline"] : [c.watch ? "idle" : "off", c.watch ? (state.automation ? "Checking…" : "Watched") : "Not watched"];
          return (
            <li key={c.id}>
              <i className={`gc-dot ${status[0]}`} aria-hidden="true" />
              <div>
                <a href={c.url} target="_blank" rel="noreferrer">{c.name}</a>
                <small>{PLATFORM[c.platform] || c.platform} · {status[1]}</small>
              </div>
              <div className="gc-creator-set">
                <select value={c.permission} disabled={busy} aria-label={`Permission to clip ${c.name}`}
                  className={c.permission === "permitted" ? "ok" : "warn"} onChange={(e) => act(`/api/creators/${c.id}`, { permission: e.target.value })}>
                  <option value="permitted">Permitted</option>
                  <option value="unknown">No permission</option>
                  <option value="refused">Refused</option>
                </select>
                <button className={`gc-watch ${c.watch ? "on" : ""}`} disabled={busy} aria-pressed={c.watch}
                  title={c.watch ? "Watched: recorded when live with GTA" : "Not watched"} onClick={() => act(`/api/creators/${c.id}`, { watch: !c.watch })}>
                  {c.watch ? "Watched" : "Watch"}
                </button>
                {!c.recording && (
                  <button className="gc-watch rec" disabled={busy} title={`Record ${c.name} now, if live, and clip it as it goes`}
                    onClick={() => act("/api/clips/record", { url: c.url })}>● Record</button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <form className="gc-record" onSubmit={record}>
        <label htmlFor="gc-url">Record any live stream</label>
        <div>
          <input id="gc-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="twitch.tv/… or a YouTube or Kick link" />
          <button className="btn" disabled={busy || !url.trim()}>Record</button>
        </div>
      </form>
      {error && <p className="gc-error" role="alert">{error}</p>}
    </Panel>
  );
}

const clockOf = (seconds) => {
  const t = Math.max(Math.round(seconds), 0);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  return `${h ? `${h}:` : ""}${String(m).padStart(h ? 2 : 1, "0")}:${String(sec).padStart(2, "0")}`;
};

// What's being recorded right now, however it was started, each with its Stop button. Clips come out as it goes.
function Recordings({ state, busy, act }) {
  const now = useNow();
  if (!state.recordings.length) return <p className="gc-not-rec"><i className="gc-dot off" aria-hidden="true" /> Not recording</p>;
  return (
    <ul className="gc-recs">
      {state.recordings.map((r) => (
        <li key={r.id}>
          <i className="gc-dot rec" aria-hidden="true" />
          <div>
            <b>{r.creator || r.url}</b>
            <small className="mono">REC {clockOf(now / 1000 - r.started)} · {r.pieces} pieces · {r.chat.toLocaleString()} chat</small>
          </div>
          <button className="btn stop small" disabled={busy || r.stopping}
            onClick={() => window.confirm(`Stop recording ${r.creator || "this stream"}? What's recorded so far still gets clipped.`) && act(`/api/sources/${r.id}/stop`)}>
            {r.stopping ? "Stopping…" : "Stop"}
          </button>
        </li>
      ))}
    </ul>
  );
}

const CLIP_STATUS = { edited: ["Waiting for you", "wait"], approved: ["Approved", "ok"], rejected: ["Rejected", "no"], uploaded: ["Posted", "ok"] };

function MomentsPanel({ state, onChange }) {
  const [all, setAll] = useState(false);
  const [playing, setPlaying] = useState(null);
  const kept = state.moments.filter((m) => m.kept);
  const shown = all ? state.moments : kept;
  const passed = state.moments.length - kept.length;
  const open = playing && state.moments.find((m) => m.id === playing);  // kept fresh as the page refreshes
  return (
    <Panel area="moments" title="Top moments" extra={
      <div className="seg small" role="group" aria-label="Which moments">
        <button className={!all ? "active" : ""} onClick={() => setAll(false)}>Picked {kept.length}</button>
        <button className={all ? "active" : ""} onClick={() => setAll(true)}>All {state.moments.length}</button>
      </div>}>
      {!shown.length ? (
        <div className="gc-empty">
          <p>{passed ? `No clips picked yet. Claude passed on ${passed} moment${passed === 1 ? "" : "s"}.` : "No moments yet. They show up here as streams are processed."}</p>
          {passed > 0 && <button className="btn" onClick={() => setAll(true)}>See why</button>}
        </div>
      ) : (
        <ol className="gc-list">
          {shown.map((m) => (
            <li key={m.id} className={`${m.kept ? "" : "passed"} ${m.clip ? "has-clip" : ""}`}>
              <b className="gc-score mono" title="Claude's judgement and the signals combined, out of 10">{m.score?.toFixed(1)}</b>
              {m.clip && (
                <button className="gc-poster" onClick={() => setPlaying(m.id)} aria-label={`Review the clip: ${m.title}`}>
                  <img src={m.clip.poster} alt="" />
                  <span aria-hidden="true">▶</span>
                </button>
              )}
              <div>
                <p className="gc-title">{m.title}</p>
                <p className="gc-meta">
                  {m.creator} · at {m.at} · {Math.round(m.length)} s · {MOMENT_LABELS[m.moment] || m.moment}
                  {!m.kept && <> · <span className="gc-passed">passed</span></>}
                  {m.clip && <> · <span className={`gc-chip ${CLIP_STATUS[m.clip.status][1]}`}>{CLIP_STATUS[m.clip.status][0]}</span></>}
                  {!m.permitted && <> · <span className="gc-warn">No permission</span></>}
                </p>
                <p className="gc-reason">{m.reason}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
      {/* On the page itself: the panels' blur would otherwise pin a fixed overlay to the panel, not the window */}
      {open?.clip && createPortal(<Review moment={open} onChange={onChange} onClose={() => setPlaying(null)} />, document.body)}
    </Panel>
  );
}

// One clip, to approve, reject, trim or fix. Making it again takes about ten seconds.
function Review({ moment, onChange, onClose }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [fixing, setFixing] = useState(false);
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, busy]);
  const c = moment.clip;
  const act = async (label, path, body) => {
    setBusy(label);
    setError(null);
    try { onChange(await post(path, body)); } catch (e) { setError(e.message); } finally { setBusy(null); }
  };
  const nudge = (start_by, end_by) => act("Making the clip again…", `/api/clips/${c.id}/trim`, { start_by, end_by });
  return (
    <div className="gc-player" role="dialog" aria-modal="true" aria-label={moment.title} onClick={() => !busy && onClose()}>
      <div className="gc-review" onClick={(e) => e.stopPropagation()}>
        {fixing ? (
          <FacecamEditor sourceId={moment.source_id} onCancel={() => setFixing(false)}
            onSave={async (box) => { await act("Making this stream's clips again…", `/api/sources/${moment.source_id}/facecam`, { box }); setFixing(false); }} busy={busy} />
        ) : (
          <video key={c.video} src={c.video} poster={c.poster} controls autoPlay playsInline />
        )}
        <div className="gc-review-side">
          <span className={`gc-chip ${CLIP_STATUS[c.status][1]}`}>{CLIP_STATUS[c.status][0]}</span>
          <h3>{moment.title}</h3>
          <p>{moment.caption}</p>
          <p className="gc-tags">{moment.hashtags.join(" ")}</p>
          <p className="gc-meta">{moment.creator} · {c.duration.toFixed(1)} s · {c.layout === "stack" ? "facecam over gameplay" : "gameplay over blur"} · {c.lufs} LUFS</p>
          {!moment.permitted && <p className="gc-warn-line">{moment.creator} hasn't given permission. Uploading it is your call.</p>}

          <div className="gc-decide">
            {c.status === "approved" || c.status === "rejected" ? (
              <button className="btn" disabled={!!busy} onClick={() => act("Saving…", `/api/clips/${c.id}/review`, { decision: "edited" })}>Undo {c.status === "approved" ? "approval" : "rejection"}</button>
            ) : (
              <>
                <button className="btn go" disabled={!!busy} onClick={() => act("Saving…", `/api/clips/${c.id}/review`, { decision: "approved" })}>Approve</button>
                <button className="btn stop" disabled={!!busy} onClick={() => act("Saving…", `/api/clips/${c.id}/review`, { decision: "rejected" })}>Reject</button>
              </>
            )}
          </div>

          <fieldset className="gc-trim" disabled={!!busy || c.status === "uploaded"}>
            <legend>Trim</legend>
            <div><span>Start</span><button className="btn small" onClick={() => nudge(-1, 0)}>1 s earlier</button><button className="btn small" onClick={() => nudge(1, 0)}>1 s later</button></div>
            <div><span>End</span><button className="btn small" onClick={() => nudge(0, -1)}>1 s earlier</button><button className="btn small" onClick={() => nudge(0, 1)}>1 s later</button></div>
          </fieldset>
          {!fixing && <button className="btn ghost" disabled={!!busy} onClick={() => setFixing(true)}>Fix the facecam box</button>}
          {busy && <p className="gc-busy" role="status">{busy}</p>}
          {error && <p className="gc-error" role="alert">{error}</p>}
          <button className="btn" disabled={!!busy} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

// Drag on the frame to draw where the streamer's camera is. Saving makes the stream's clips again.
function FacecamEditor({ sourceId, onSave, onCancel, busy }) {
  const [box, setBox] = useState(null);
  const [drag, setDrag] = useState(null);
  useEffect(() => { get(`/api/sources/${sourceId}/facecam`).then((f) => setBox(f.box)).catch(() => {}); }, [sourceId]);
  const at = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  };
  const down = (e) => { e.currentTarget.setPointerCapture(e.pointerId); const p = at(e); setDrag(p); setBox([p[0], p[1], p[0], p[1]]); };
  const move = (e) => { if (!drag) return; const p = at(e); setBox([Math.min(drag[0], p[0]), Math.min(drag[1], p[1]), Math.max(drag[0], p[0]), Math.max(drag[1], p[1])]); };
  const big = box && box[2] - box[0] > 0.03 && box[3] - box[1] > 0.03;
  return (
    <div className="gc-cam">
      <p>Drag over the streamer's camera.</p>
      <div className="gc-cam-frame" onPointerDown={down} onPointerMove={move} onPointerUp={() => setDrag(null)}>
        <img src={`/api/sources/${sourceId}/frame`} alt="A frame from this stream" draggable="false" />
        {box && <i style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }} />}
      </div>
      <div className="gc-cam-actions">
        <button className="btn go" disabled={!big || !!busy} onClick={() => onSave(box)}>Save box</button>
        <button className="btn" disabled={!!busy} onClick={() => onSave(null)}>No facecam</button>
        <button className="btn ghost" disabled={!!busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function SystemPanel({ state }) {
  const spentPct = Math.round((state.spend.month / state.spend.cap) * 100);
  return (
    <Panel area="system" title="Budget & disk">
      <div className="cc-rings gc-rings">
        <Ring label="Claude" value={spentPct} note={`${money(state.spend.month)} of ${money(state.spend.cap)}`} />
        <Ring label="Disk" value={state.disk.used_pct} note={`${Math.round(state.disk.available_gb)} GB available · ${Math.round(state.disk.free_gb)} free now`} />
      </div>
    </Panel>
  );
}

function SchedulePanel({ state }) {
  return (
    <Panel area="schedule" title="Today's schedule">
      {state.schedule.length ? null : <p className="gc-empty-line">Nothing scheduled. Uploading arrives with milestone 5, private at first.</p>}
    </Panel>
  );
}
