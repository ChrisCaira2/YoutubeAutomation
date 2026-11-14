import React, { useEffect, useState } from "react";
import { post } from "./api.js";
import { useStudio } from "./store.js";
import { money, useNow } from "./util.js";
import CommandCenter from "./views/CommandCenter.jsx";
import MissionControl from "./views/MissionControl.jsx";
import Pipeline from "./views/Pipeline.jsx";
import Approvals from "./views/Approvals.jsx";
import Playbook from "./views/Playbook.jsx";
import Health from "./views/Health.jsx";
import JobDrawer from "./views/JobDrawer.jsx";

const COMMAND = ["command", "Command Center"];  // Game Day Brain's futuristic home screen
const TABS = [
  ["control", "Mission Control"],
  ["pipeline", "Pipeline"],
  ["approvals", "Approvals"],
  ["playbook", "Playbook"],
  ["health", "Health & Controls"],
];

const initials = (name) => name.split(/\s+/).filter((w) => !/^(the|of|and)$/i.test(w)).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

export default function App() {
  const studio = useStudio();
  const [tab, setTab] = useState(null);
  const [openJob, setOpenJob] = useState(null);
  const { state, connected } = studio;
  const futuristic = state?.workspace === "slop";
  useEffect(() => {
    document.body.classList.toggle("theme-cc", futuristic);
  }, [futuristic]);

  if (!state) {
    return (
      <div className="boot">
        <div className="boot-mark">AA</div>
        <p>Connecting to the studio…</p>
      </div>
    );
  }

  const waiting = Object.values(state.jobs).filter(
    (j) => j.status === "active" && (j.stage === "awaiting_approval" || (j.stage === "scripted" && state.settings.manual_script_review)),
  ).length;
  const paused = state.settings.paused;
  const h = state.health;
  const tabs = futuristic ? [COMMAND, ...TABS] : TABS;
  const shown = tab || tabs[0][0];

  return (
    <div className={`app ${futuristic ? "cc-app" : ""}`}>
      <header className="top">
        <div className="brand">
          <div className={`brand-mark ws-${state.workspace}`}>{initials(state.channel)}</div>
          <div>
            <div className="brand-name">{state.channel}</div>
            <div className="brand-sub">{futuristic ? "Command center" : `Agent Hub · ${state.workspace === "archive" ? `hosted by ${state.host}` : "AI-generated videos"}`}</div>
          </div>
        </div>
        {futuristic && <HeaderClock />}
        {state.workspaces?.length > 1 && (
          <nav className="seg workspaces" aria-label="Studio">
            {state.workspaces.map((w) => (
              w.current
                ? <span key={w.id} className="active" aria-current="page">{w.label}</span>
                : <a key={w.id} href={w.url}>{w.label}</a>
            ))}
          </nav>
        )}
        <div className="top-stats">
          <span className={`live ${connected ? "on" : ""}`}>
            <i /> {connected ? "Live" : "Reconnecting"}
          </span>
          {state.mode === "mock" && <span className="badge mock" title="Fake providers, no spending">Mock mode</span>}
          {state.mode === "live" && <span className="badge live-mode" title="Agents call Claude and spend real money">Live · real spending</span>}
          <span className="top-stat">
            <b className="mono">{money(h.spent_today)}</b> {state.mode === "mock" ? "forecast, " : ""}of {money(h.daily_budget)} today
          </span>
          <button className={`btn ${paused ? "go" : "stop"}`} onClick={() => post(`/api/control/${paused ? "resume" : "pause"}`)}>
            {paused ? "Resume studio" : "Pause studio"}
          </button>
        </div>
      </header>

      <nav className="tabs" aria-label="Views">
        {tabs.map(([id, label]) => (
          <button key={id} className={shown === id ? "active" : ""} onClick={() => setTab(id)}>
            {label}
            {id === "approvals" && waiting > 0 && <span className="count">{waiting}</span>}
          </button>
        ))}
      </nav>

      <div className="stage">
        {paused && <div className="banner">The studio is paused. Agents finish their current step and then wait.</div>}

        <main>
          {shown === "command" && <CommandCenter studio={studio} openJob={setOpenJob} goTo={setTab} />}
          {shown === "control" && <MissionControl studio={studio} openJob={setOpenJob} goTo={setTab} />}
          {shown === "pipeline" && <Pipeline state={state} openJob={setOpenJob} />}
          {shown === "approvals" && <Approvals state={state} openJob={setOpenJob} />}
          {shown === "playbook" && <Playbook />}
          {shown === "health" && <Health state={state} />}
        </main>
      </div>

      {openJob && <JobDrawer jobId={openJob} studio={studio} onClose={() => setOpenJob(null)} />}
    </div>
  );
}

function HeaderClock() {
  const now = new Date(useNow());
  return (
    <div className="cc-clock" aria-label="Current time">
      <span>{now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</span>
      <b className="mono">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</b>
    </div>
  );
}
