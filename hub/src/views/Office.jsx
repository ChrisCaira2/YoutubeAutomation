import React, { useMemo } from "react";
import { portrait } from "../cast.js";
import { agentColor, money } from "../util.js";

// The front office: every agent is a staffer at a themed desk. Production runs
// along the back row, the finished video comes forward to you, and results
// loop back to the scout.
const STATIONS = {
  showrunner: { x: 500, y: 228, s: 0.8, role: "GM" },
  research: { x: 130, y: 340, s: 0.9, role: "SCOUT" },
  script: { x: 373, y: 340, s: 0.9, role: "WRITER" },
  qa: { x: 627, y: 340, s: 0.9, role: "REF" },
  studio: { x: 870, y: 340, s: 0.9, role: "FILM ROOM" },
  publisher: { x: 150, y: 484, s: 1, role: "ANALYTICS" },
  you: { x: 520, y: 484, s: 1, role: "OWNER · YOU" },
  packaging: { x: 858, y: 484, s: 1, role: "MARKETING" },
};

const PROPS = {
  showrunner: "gm", research: "scout", script: "writer", qa: "ref",
  studio: "film", packaging: "marketing", publisher: "analytics",
};

// Where a tossed football leaves from and lands at each desk.
const anchor = (name) => {
  const st = STATIONS[name];
  return st ? { x: st.x, y: st.y - 30 * st.s } : null;
};

const ACTIVE_MS = 3000;
const reducedMotion = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export default function Office({ state, handoffs, now, openJob, onSelect, onOwner }) {
  const { agents, health, settings } = state;
  const waiting = Object.values(state.jobs).filter(
    (j) => j.status === "active" && (j.stage === "awaiting_approval" || (j.stage === "scripted" && settings.manual_script_review)),
  ).length;
  const working = Object.values(agents).filter((a) => a.status === "working" && a.name !== "showrunner").length;
  const active = handoffs.filter((h) => now - new Date(h.ts).getTime() < ACTIVE_MS);
  const station = (n) => agents[n] && <Station key={n} name={n} agent={agents[n]} openJob={openJob} onSelect={onSelect} workspace={state.workspace} />;

  return (
    <svg viewBox="0 0 1000 560" className="office" role="img" aria-label="The front office: each agent at their desk">
      <Defs />
      <Room />
      <LedWall spent={health.spent_today} budget={health.daily_budget} working={working} paused={settings.paused} mock={state.mode === "mock"} />
      <GmOffice />
      {station("showrunner")}
      <Pendants />
      {["research", "script", "qa", "studio"].map(station)}
      <Plant x={40} y={540} scale={1.1} />
      <CoffeeBar x={335} y={484} />
      <Shelf x={690} y={484} />
      <Plant x={968} y={548} scale={1.25} flip />
      {["publisher", "packaging"].map(station)}
      <OwnerDesk waiting={waiting} onOwner={onOwner} />
      {active.map((h) => <Football key={h.id} h={h} openJob={openJob} />)}
    </svg>
  );
}

/* ---------------------------------------------------------------- room */

function Defs() {
  return (
    <defs>
      <linearGradient id="o-wall" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#141b26" />
        <stop offset="1" stopColor="#1a2330" />
      </linearGradient>
      <linearGradient id="o-floor" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#262d38" />
        <stop offset="1" stopColor="#1b2029" />
      </linearGradient>
      <linearGradient id="o-sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#1a1f4a" />
        <stop offset="0.6" stopColor="#3b2f6b" />
        <stop offset="1" stopColor="#c0627a" />
      </linearGradient>
      <linearGradient id="o-glass" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#bfe3ff" stopOpacity="0.14" />
        <stop offset="1" stopColor="#bfe3ff" stopOpacity="0.04" />
      </linearGradient>
      <linearGradient id="o-oak" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#e2c9a6" />
        <stop offset="1" stopColor="#c9a87f" />
      </linearGradient>
      <linearGradient id="o-cone" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#ffe9b8" stopOpacity="0.22" />
        <stop offset="1" stopColor="#ffe9b8" stopOpacity="0" />
      </linearGradient>
      <radialGradient id="o-flood">
        <stop offset="0" stopColor="#fffbe8" stopOpacity="0.95" />
        <stop offset="1" stopColor="#fffbe8" stopOpacity="0" />
      </radialGradient>
      <filter id="o-soft" x="-20%" y="-20%" width="140%" height="160%">
        <feDropShadow dx="0" dy="6" stdDeviation="6" floodColor="#000" floodOpacity="0.35" />
      </filter>
    </defs>
  );
}

function Room() {
  return (
    <g>
      <rect width="1000" height="268" fill="url(#o-wall)" />
      {/* wood slat accent walls */}
      {[0, 968].map((x0) => (
        <g key={x0}>
          {Array.from({ length: 4 }, (_, i) => (
            <rect key={i} x={x0 + i * 8} y="0" width="5" height="268" fill="#5a4330" opacity="0.55" />
          ))}
        </g>
      ))}
      <Window x={44} />
      <Window x={646} />
      <rect y="262" width="1000" height="6" fill="#0d1118" />
      <rect y="268" width="1000" height="292" fill="url(#o-floor)" />
      <path d="M0 268 H1000" stroke="#ffffff" strokeOpacity="0.05" />
      {/* soft reflections of the windows on the polished floor */}
      <rect x="60" y="272" width="280" height="40" fill="#c0627a" opacity="0.05" />
      <rect x="662" y="272" width="280" height="40" fill="#c0627a" opacity="0.05" />
    </g>
  );
}

function Window({ x }) {
  return (
    <g transform={`translate(${x} 22)`}>
      <rect width="310" height="240" fill="url(#o-sky)" />
      {/* city skyline */}
      <path d="M0 190 V150 h22 v-24 h18 v34 h16 v-50 h24 v50 h14 v-20 h20 v40 h18 v-62 h26 v62 h16 v-30 h22 v30 h20 v-44 h18 v44 h16 v-16 h22 v16 h18 v-36 h20 v66 Z" fill="#141633" opacity="0.9" />
      {/* stadium bowl and field */}
      <path d="M40 240 Q155 150 270 240 Z" fill="#232a52" />
      <path d="M70 240 Q155 178 240 240 Z" fill="#2fa25a" />
      <path d="M155 196 V240" stroke="#e8f5e9" strokeOpacity="0.35" />
      {[52, 258].map((tx) => (
        <g key={tx}>
          <line x1={tx} y1="240" x2={tx} y2="132" stroke="#2b3157" strokeWidth="3" />
          <rect x={tx - 12} y="124" width="24" height="9" rx="2" fill="#fffbe8" />
          <circle cx={tx} cy="128" r="34" fill="url(#o-flood)" className="stadium-light" />
        </g>
      ))}
      {/* mullions */}
      <g stroke="#0d1118" strokeWidth="4">
        <rect width="310" height="240" fill="none" />
        <line x1="103" y1="0" x2="103" y2="240" />
        <line x1="207" y1="0" x2="207" y2="240" />
      </g>
      <rect width="310" height="240" fill="url(#o-glass)" />
    </g>
  );
}

function LedWall({ spent, budget, working, paused, mock }) {
  return (
    <g transform="translate(380 6)" filter="url(#o-soft)">
      <rect width="240" height="58" rx="8" fill="#06080c" stroke="#232c3a" strokeWidth="2" />
      <rect x="6" y="6" width="228" height="46" rx="4" fill="#0b0f16" />
      <text x="18" y="22" className="sb-label">{mock ? "FORECAST" : "SPENT TODAY"}</text>
      <text x="18" y="45" className="sb-digits">{money(spent)}</text>
      <text x="108" y="22" className="sb-label">BUDGET</text>
      <text x="108" y="45" className="sb-digits dim">{money(budget)}</text>
      <line x1="190" y1="14" x2="190" y2="46" stroke="#232c3a" strokeWidth="2" />
      <text x="212" y="22" className="sb-label" textAnchor="middle">AT WORK</text>
      <text x="212" y="45" className="sb-digits teal" textAnchor="middle">{paused ? "–" : working}</text>
    </g>
  );
}

function GmOffice() {
  return (
    <g>
      <rect x="392" y="74" width="216" height="194" rx="4" fill="#111823" />
      <rect x="392" y="74" width="216" height="194" rx="4" fill="url(#o-glass)" stroke="#6f8aa8" strokeOpacity="0.45" strokeWidth="2" />
      <rect x="392" y="150" width="216" height="12" fill="#ffffff" opacity="0.06" />
      <g transform="translate(500 104)">
        <rect x="-52" y="-12" width="104" height="22" rx="11" fill="#0b0f16" style={{ stroke: "var(--c-showrunner)" }} strokeWidth="1.5" />
        <text y="4" textAnchor="middle" className="door-plate">GENERAL MANAGER</text>
      </g>
    </g>
  );
}

function Pendants() {
  return (
    <g>
      {[130, 373, 627, 870].map((x) => (
        <g key={x}>
          <line x1={x} y1="0" x2={x} y2="196" stroke="#0a0d12" strokeWidth="1.5" />
          <path d={`M${x - 14} 206 Q${x} 186 ${x + 14} 206 Z`} fill="#20262f" />
          <rect x={x - 14} y="205" width="28" height="3" rx="1.5" fill="#ffe9b8" />
          <path d={`M${x - 14} 208 L${x - 70} 330 H${x + 70} L${x + 14} 208 Z`} fill="url(#o-cone)" />
        </g>
      ))}
    </g>
  );
}

/* ------------------------------------------------------------- stations */

function Station({ name, agent, openJob, onSelect, workspace }) {
  const st = STATIONS[name];
  const color = agentColor(name);
  const status = agent.paused && agent.status !== "working" ? "paused" : agent.status;
  const working = status === "working";
  const label = `${st.role}: ${agent.label}, ${status}${agent.task ? `, ${agent.task}` : ""}`;
  const click = () => (working && agent.job_id ? openJob(agent.job_id) : onSelect(name));

  return (
    <g transform={`translate(${st.x} ${st.y}) scale(${st.s})`} className={`station ${status}`} style={{ "--agent": color }}
      onClick={click} role="button" tabIndex={0} aria-label={label}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && click()}>
      <title>{label}</title>
      <ellipse cx="0" cy="66" rx="92" ry="9" fill="#000" opacity="0.3" />
      {working && <ellipse cx="0" cy="66" rx="98" ry="13" className="floor-glow" />}
      {PROPS[name] === "marketing" && <Moodboard working={working} />}
      <Chair />
      <g className={`avatar ${working ? "bob" : status === "paused" ? "doze" : "breathe"}`}>
        <image href={portrait(name, status, workspace)} x="-50" y="-98" width="100" height="100" />
        {name === "qa" && <Whistle />}
        {name === "studio" && <Headset />}
      </g>
      <Desk />
      <Prop kind={PROPS[name]} working={working} />
      {working && <Hands />}
      <Badge role={st.role} status={status} progress={agent.progress} />
      {working && agent.task && <Bubble text={agent.task} />}
      {status === "paused" && <Tag text="ON BREAK" />}
      {status === "waiting" && name === "showrunner" && <Tag text="TIMEOUT" />}
      {(status === "blocked" || status === "error") && <Alarm />}
      {status === "idle" && name !== "showrunner" && <Mug />}
    </g>
  );
}

function Chair() {
  return (
    <g>
      <rect x="-34" y="-74" width="68" height="78" rx="18" fill="#232a35" />
      <rect x="-34" y="-74" width="68" height="10" rx="5" style={{ fill: "var(--agent)" }} opacity="0.7" />
    </g>
  );
}

function Desk() {
  return (
    <g filter="url(#o-soft)">
      <rect x="-80" y="0" width="160" height="9" rx="4" fill="url(#o-oak)" />
      <rect x="-74" y="9" width="148" height="48" rx="3" fill="#2a313c" />
      <rect x="-74" y="9" width="148" height="3" fill="#000" opacity="0.25" />
      <rect x="-70" y="57" width="5" height="8" fill="#151a21" />
      <rect x="65" y="57" width="5" height="8" fill="#151a21" />
    </g>
  );
}

function Badge({ role, status, progress }) {
  return (
    <g transform="translate(0 20)">
      <rect x="-56" y="0" width="112" height="30" rx="15" fill="#0b0f16" style={{ stroke: "var(--agent)" }} strokeOpacity="0.9" strokeWidth="1.5" />
      <circle cx="-42" cy="15" r="4" style={{ fill: "var(--agent)" }} className={status === "working" ? "dot-live" : ""} />
      <text x="-32" y="13" className="plate-role">{role}</text>
      <text x="-32" y="24" className={`plate-status ${status}`}>{status}</text>
      {status === "working" && (
        <g>
          <rect x="-48" y="35" width="96" height="3" rx="1.5" fill="#000" opacity="0.5" />
          <rect x="-48" y="35" width={96 * Math.max(0.04, progress || 0)} height="3" rx="1.5" style={{ fill: "var(--agent)" }} />
        </g>
      )}
    </g>
  );
}

function Hands() {
  return (
    <g className="typing">
      <rect className="arm-l" x="-24" y="-7" width="13" height="7" rx="3.5" style={{ fill: "var(--agent)" }} opacity="0.9" />
      <rect className="arm-r" x="11" y="-7" width="13" height="7" rx="3.5" style={{ fill: "var(--agent)" }} opacity="0.9" />
    </g>
  );
}

function Whistle() {
  return (
    <g transform="translate(0 -10)">
      <path d="M-10 -14 Q0 2 10 -14" fill="none" stroke="#e5484d" strokeWidth="1.6" />
      <rect x="-5" y="-6" width="10" height="6" rx="2.5" fill="#c9cfd6" />
    </g>
  );
}

function Headset() {
  return (
    <g fill="none" stroke="#11151b" strokeWidth="3.5" strokeLinecap="round">
      <path d="M-25 -55 Q-25 -82 0 -84 Q25 -82 25 -55" />
      <rect x="-30" y="-60" width="8" height="14" rx="3" fill="#11151b" />
      <path d="M-26 -48 Q-22 -36 -10 -37" strokeWidth="2" />
    </g>
  );
}

/* --------------------------------------------------------------- props */

function Screen({ x, y, w, h, children, working }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect width={w} height={h} rx="3" fill="#0d1118" stroke="#3a4352" strokeWidth="2" />
      <g className={working ? "screen-on" : "screen-off"}>{children}</g>
      <rect x={w / 2 - 3} y={h} width="6" height={-y - h} fill="#3a4352" />
      <rect x={w / 2 - 10} y={-y - 2} width="20" height="3" rx="1.5" fill="#3a4352" />
    </g>
  );
}

function Laptop({ x, working, children }) {
  return (
    <g transform={`translate(${x} 0)`}>
      <path d="M-20 0 L-16 -26 H16 L20 0 Z" fill="#c9cfd6" />
      <rect x="-14" y="-24" width="28" height="20" rx="1" fill="#0d1118" />
      <g transform="translate(-12 -22)" className={working ? "screen-on" : "screen-off"}>{children}</g>
      <rect x="-24" y="-2" width="48" height="3" rx="1.5" fill="#aeb5bd" />
    </g>
  );
}

function Prop({ kind, working }) {
  switch (kind) {
    case "scout":
      return (
        <g>
          <Laptop x={-50} working={working}>
            <rect width="24" height="16" fill="#4cc9f0" opacity="0.35" />
            <path d="M3 12 L9 7 L14 10 L21 4" stroke="#4cc9f0" strokeWidth="1.5" fill="none" />
          </Laptop>
          <g transform="translate(46 -8)">
            <rect x="-8" y="-4" width="7" height="10" rx="3" fill="#2b313b" />
            <rect x="2" y="-4" width="7" height="10" rx="3" fill="#2b313b" />
            <rect x="-2" y="-2" width="5" height="4" fill="#3b4250" />
          </g>
        </g>
      );
    case "writer":
      return (
        <g>
          <Laptop x={-48} working={working}>
            <g stroke="#e6e0ff" strokeWidth="1.2" className={working ? "doc-lines" : ""}>
              <path d="M3 4 h18 M3 8 h14 M3 12 h17" />
            </g>
          </Laptop>
          <g transform="translate(42 -6) rotate(-6)">
            <rect x="-10" y="-4" width="22" height="8" rx="1.5" fill="#f4f1ea" />
            <path d="M-6 -1 h14 M-6 2 h10" stroke="#b794ff" strokeWidth="1" />
            <rect x="14" y="-3" width="2" height="9" rx="1" fill="#b794ff" transform="rotate(30 15 1)" />
          </g>
        </g>
      );
    case "ref":
      return (
        <g>
          <g transform="translate(-60 -24)">
            <rect width="26" height="22" rx="3" fill="#0d1118" stroke="#3a4352" strokeWidth="2" />
            {[0, 1, 2].map((i) => (
              <g key={i} transform={`translate(5 ${5 + i * 5.5})`}>
                <path d="M0 1.5 l1.5 1.5 l3 -3" stroke="#3ddc84" strokeWidth="1.3" fill="none" className={working ? `check check-${i}` : ""} />
                <path d="M7 1.5 h10" stroke="#8a95a5" strokeWidth="1.2" />
              </g>
            ))}
          </g>
          <g transform="translate(44 -2)">
            <rect x="0" y="-8" width="16" height="10" rx="1.5" fill="#f5c542" />
            <circle cx="3" cy="-3" r="1.4" fill="#c99a12" />
          </g>
        </g>
      );
    case "film":
      return (
        <g>
          <Screen x={-90} y={-44} w={52} h={30} working={working}>
            <rect x="3" y="3" width="46" height="24" fill="#1f6b3a" />
            <g stroke="#e8f5e9" strokeWidth="1.4" fill="none">
              <path d="M10 9 l4 4 m0 -4 l-4 4" /><circle cx="38" cy="18" r="3" />
              <path d="M14 13 Q24 24 34 18" strokeDasharray="2 2" className={working ? "play-draw" : ""} />
            </g>
          </Screen>
          <g transform="translate(46 -6)">
            <path d="M-8 0 Q-8 -12 0 -12 Q8 -12 8 0" fill="none" stroke="#2b313b" strokeWidth="2.5" />
            <rect x="-10" y="-3" width="5" height="7" rx="2" fill="#2b313b" />
            <rect x="5" y="-3" width="5" height="7" rx="2" fill="#2b313b" />
          </g>
        </g>
      );
    case "analytics":
      return (
        <g>
          {[-88, 44].map((x, k) => (
            <Screen key={x} x={x} y={-42} w={44} h={28} working={working}>
              {[0, 1, 2, 3].map((i) => (
                <rect key={i} x={6 + i * 9} y={8 + ((i + k) % 3) * 4} width="5" height={16 - ((i + k) % 3) * 4} rx="1"
                  style={{ fill: "var(--c-publisher)" }} className={working ? `chart-bar chart-bar-${i}` : ""} />
              ))}
            </Screen>
          ))}
        </g>
      );
    case "gm":
      return (
        <g>
          <Laptop x={-48} working={working}>
            <rect x="2" y="3" width="8" height="10" rx="1" fill="#ffb020" opacity="0.7" />
            <rect x="13" y="3" width="8" height="10" rx="1" fill="#4cc9f0" opacity="0.7" />
          </Laptop>
          <g transform="translate(44 -4)">
            <rect x="-8" y="-2" width="16" height="6" rx="2" fill="#2b313b" />
            <rect x="-6" y="-8" width="12" height="6" rx="3" fill="#3b4250" />
          </g>
        </g>
      );
    case "marketing":
      return (
        <g transform="translate(-58 -8)">
          <rect x="-18" y="-3" width="36" height="10" rx="2" fill="#2b313b" />
          <rect x="-15" y="-1" width="30" height="6" rx="1" fill="#ff8a3d" opacity={working ? 0.6 : 0.25} />
          <rect x="12" y="-14" width="2.5" height="14" rx="1" fill="#e5e7eb" transform="rotate(25 13 -7)" className={working ? "stylus" : ""} />
        </g>
      );
    default:
      return null;
  }
}

function Moodboard({ working }) {
  const cards = [["#ff8a3d", "100"], ["#4cc9f0", "28/32"], ["#ffb020", "1962"]];
  return (
    <g transform="translate(64 -108)">
      <path d="M8 40 L0 118 M50 40 L58 118" stroke="#3a4352" strokeWidth="3" />
      <rect x="-6" y="0" width="70" height="52" rx="4" fill="#e9e4dc" />
      {cards.map(([c, t], i) => (
        <g key={i} transform={`translate(${-1 + (i % 2) * 33} ${4 + Math.floor(i / 2) * 25}) rotate(${i % 2 ? 3 : -3})`}>
          <rect width="28" height="20" rx="2" fill={c} />
          <text x="14" y="13" textAnchor="middle" className={`card-num ${working && i === 0 ? "pop" : ""}`}>{t}</text>
        </g>
      ))}
    </g>
  );
}

function Bubble({ text }) {
  const t = text.length > 34 ? `${text.slice(0, 33)}…` : text;
  const w = Math.max(80, t.length * 6.2 + 30);
  return (
    <g transform="translate(0 -134)" className="bubble">
      <rect x={-w / 2} y="0" width={w} height="24" rx="12" fill="#ffffff" filter="url(#o-soft)" />
      <path d="M-5 23 L0 31 L5 23 Z" fill="#ffffff" />
      <circle cx={-w / 2 + 13} cy="12" r="4" style={{ fill: "var(--agent)" }} className="dot-live" />
      <text x={-w / 2 + 23} y="16" className="bubble-text">{t}</text>
    </g>
  );
}

function Tag({ text }) {
  return (
    <g transform="translate(14 -24)">
      <rect width="56" height="18" rx="9" fill="#ffb020" />
      <text x="28" y="12.5" textAnchor="middle" className="sign-text">{text}</text>
    </g>
  );
}

function Alarm() {
  return (
    <g transform="translate(34 -96)" className="alarm">
      <circle r="11" fill="#ff5470" />
      <text y="5" textAnchor="middle" className="alarm-text">!</text>
    </g>
  );
}

function Mug() {
  return (
    <g transform="translate(52 -13)">
      <rect width="11" height="13" rx="3" fill="#e9e4dc" />
      <path d="M11 3 q5 0 5 4 q0 4 -5 4" fill="none" stroke="#e9e4dc" strokeWidth="2" />
      <path d="M3 -3 q-3 -5 0 -10 M8 -3 q-3 -5 0 -10" stroke="#e9e4dc" strokeOpacity="0.45" strokeWidth="1.5" fill="none" className="steam" />
    </g>
  );
}

/* ------------------------------------------------------- owner and decor */

function OwnerDesk({ waiting, onOwner }) {
  const st = STATIONS.you;
  const label = waiting ? `Your desk: ${waiting} waiting for your review` : "Your desk: nothing waiting";
  return (
    <g transform={`translate(${st.x} ${st.y})`} className={`station owner ${waiting ? "has-mail" : ""}`} style={{ "--agent": "var(--c-you)" }}
      onClick={onOwner} role="button" tabIndex={0} aria-label={label} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOwner()}>
      <title>{label}</title>
      <ellipse cx="0" cy="66" rx="100" ry="10" fill="#000" opacity="0.3" />
      <rect x="-36" y="-84" width="72" height="88" rx="22" fill="#3a2a22" />
      <rect x="-28" y="-76" width="56" height="70" rx="16" fill="#4a352a" />
      <Desk />
      <g transform="translate(-58 -12)">
        <rect x="-16" y="0" width="34" height="12" rx="2" fill="#3a4352" />
        {Array.from({ length: Math.min(waiting, 4) }, (_, i) => (
          <rect key={i} x="-13" y={-3 - i * 3} width="28" height="4" rx="1" fill="#f4f1ea" />
        ))}
      </g>
      <Laptop x={0} working={false}>
        <rect width="24" height="16" fill="#1b2533" />
      </Laptop>
      <g transform="translate(52 -34)">
        <path d="M0 34 V8 L12 0" stroke="#9aa3ad" strokeWidth="2.5" fill="none" />
        <path d="M6 -6 L26 -6 L22 6 L10 6 Z" fill={waiting ? "#ff5470" : "#ffe9b8"} className={waiting ? "lamp-blink" : ""} />
      </g>
      <Badge role="OWNER · YOU" status={waiting ? `${waiting} to review` : "all clear"} />
      {waiting > 0 && (
        <g transform="translate(-24 -96)" className="mail-badge">
          <circle r="12" fill="#ff5470" />
          <text y="5" textAnchor="middle" className="alarm-text">{waiting}</text>
        </g>
      )}
    </g>
  );
}

function Plant({ x, y, scale = 1, flip = false }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${flip ? -scale : scale} ${scale})`}>
      <path d="M-16 0 L-12 -30 H12 L16 0 Z" fill="#e9e4dc" />
      <path d="M0 -30 Q-30 -60 -26 -96 Q-6 -70 0 -30 Z" fill="#2e8b57" />
      <path d="M0 -30 Q24 -64 34 -88 Q14 -52 0 -30 Z" fill="#37a067" />
      <path d="M0 -30 Q-4 -80 6 -116 Q14 -76 0 -30 Z" fill="#256f46" />
      <path d="M0 -30 Q-38 -40 -44 -62 Q-18 -54 0 -30 Z" fill="#37a067" />
    </g>
  );
}

function CoffeeBar({ x, y }) {
  return (
    <g transform={`translate(${x} ${y})`} filter="url(#o-soft)">
      <rect x="-30" y="0" width="60" height="58" rx="4" fill="#2a313c" />
      <rect x="-34" y="-4" width="68" height="6" rx="3" fill="url(#o-oak)" />
      <rect x="-20" y="-40" width="28" height="36" rx="4" fill="#3a4352" />
      <rect x="-15" y="-34" width="18" height="8" rx="2" fill="#0d1118" />
      <circle cx="-6" cy="-14" r="3" fill="#ffb020" />
      <rect x="14" y="-14" width="10" height="10" rx="2" fill="#e9e4dc" />
    </g>
  );
}

function Shelf({ x, y }) {
  return (
    <g transform={`translate(${x} ${y})`} filter="url(#o-soft)">
      <rect x="-36" y="-70" width="72" height="128" rx="4" fill="#2a313c" />
      <rect x="-30" y="-64" width="60" height="116" rx="2" fill="#1b2029" />
      <rect x="-30" y="-16" width="60" height="4" fill="url(#o-oak)" />
      <rect x="-30" y="28" width="60" height="4" fill="url(#o-oak)" />
      <g fill="#ffb020">
        <path d="M-16 -50 h18 v5 q0 10 -9 12 q-9 -2 -9 -12 z" /><rect x="-9" y="-33" width="4" height="10" /><rect x="-14" y="-23" width="14" height="5" rx="1" />
      </g>
      <circle cx="16" cy="-26" r="8" fill="#c9cfd6" /><rect x="12" y="-18" width="8" height="4" fill="#c9cfd6" />
      <g transform="translate(-26 -8)">
        <rect width="28" height="34" rx="2" fill="#e9e4dc" />
        <path d="M6 8 l4 -4 h8 l4 4 l-3 3 v15 h-10 v-15 z" fill="#4cc9f0" />
        <text x="14" y="23" textAnchor="middle" className="jersey-num">23</text>
      </g>
      <rect x="8" y="2" width="16" height="22" rx="2" fill="#b794ff" opacity="0.7" />
    </g>
  );
}

/* ------------------------------------------------------------ handoffs */

function Football({ h, openJob }) {
  const a = anchor(h.details.from);
  const b = anchor(h.details.to);
  const d = useMemo(() => {
    if (!a || !b) return null;
    const top = Math.min(a.y, b.y) - 90 - Math.abs(a.x - b.x) * 0.12;
    return `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${top} ${b.x} ${b.y}`;
  }, [a?.x, a?.y, b?.x, b?.y]);
  if (!d) return null;
  const color = agentColor(h.details.from);
  return (
    <g className="toss" onClick={() => openJob(h.job_id)} role="button" aria-label={`Handoff: ${h.message}`}>
      <title>{h.message}</title>
      <path d={d} fill="none" style={{ stroke: color }} strokeWidth="6" opacity="0.12" strokeLinecap="round" />
      <path d={d} fill="none" style={{ stroke: color }} strokeWidth="1.5" strokeDasharray="3 7" opacity="0.8" strokeLinecap="round" />
      <g transform={reducedMotion ? `translate(${b.x} ${b.y})` : undefined}>
        <ellipse rx="11" ry="7" fill="#8b4a22" stroke="#5a2e12" strokeWidth="1" />
        <path d="M-9 0 Q0 -3 9 0" stroke="#f4f1ea" strokeWidth="1" fill="none" opacity="0.5" />
        <path d="M-4 0 h8 M-2 -2 v4 M0 -2 v4 M2 -2 v4" stroke="#f4f1ea" strokeWidth="1" />
        {!reducedMotion && <animateMotion dur="1.3s" repeatCount="indefinite" path={d} rotate="auto" />}
      </g>
    </g>
  );
}
