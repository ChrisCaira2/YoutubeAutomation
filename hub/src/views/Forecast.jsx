import React, { useEffect, useState } from "react";
import { get } from "../api.js";
import { agentColor, money } from "../util.js";

export function useForecast(format) {
  const [forecast, setForecast] = useState(null);
  useEffect(() => {
    let alive = true;
    get(`/api/forecast?format=${format}`).then((f) => alive && setForecast(f)).catch(() => alive && setForecast(null));
    return () => {
      alive = false;
    };
  }, [format]);
  return forecast;
}

export const rangeText = (r) => (r.high === 0 ? "Free" : `${money(r.low)}–${money(r.high)}`);

export function ForecastSummary({ forecast }) {
  if (!forecast) return null;
  const t = forecast.through_review;
  return <p className="muted">Expected cost through your script review: about <b className="mono amber">{money(t.expected)}</b> ({rangeText(t)})</p>;
}

export default function ForecastPanel({ mode }) {
  const [format, setFormat] = useState("long");
  const forecast = useForecast(format);
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Cost forecast per video</h2>
        <div className="seg" role="group" aria-label="Format">
          {[["long", "Long-form"], ["short", "Short"]].map(([id, label]) => (
            <button key={id} className={format === id ? "active" : ""} onClick={() => setFormat(id)}>{label}</button>
          ))}
        </div>
      </div>
      {!forecast && <p className="muted">The forecast isn't available from this server. Restart it to load the latest code.</p>}
      {forecast && (
        <>
          <div className="forecast-totals">
            <div>
              <span className="tile-label">Through your script review</span>
              <b className="tile-value mono">{money(forecast.through_review.expected)}</b>
              <span className="tile-sub">{rangeText(forecast.through_review)}</span>
            </div>
            <div>
              <span className="tile-label">Whole video, with rough guesses</span>
              <b className="tile-value mono dim">{money(forecast.full_video.expected)}</b>
              <span className="tile-sub">{rangeText(forecast.full_video)}</span>
            </div>
          </div>
          <div className="table-wrap">
            <table className="pb forecast-table">
              <thead><tr><th>Step</th><th>Expected</th><th>Range</th><th>Based on</th><th>Why</th></tr></thead>
              <tbody>
                {forecast.steps.map((r) => (
                  <tr key={r.key} className={r.built ? "" : "unbuilt"}>
                    <td style={{ color: agentColor(r.agent) }}>{r.label}</td>
                    <td className="mono">{r.high === 0 ? "$0" : money(r.expected)}</td>
                    <td className="mono">{rangeText(r)}</td>
                    <td><span className={`basis b-${r.basis.split(",")[0].split(" ")[0].toLowerCase()}`}>{r.basis}</span></td>
                    <td className="muted">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            {mode === "mock" ? "Mock runs report these numbers and charge nothing. " : ""}
            {forecast.excludes} Forecast as of {forecast.as_of}.
          </p>
        </>
      )}
    </section>
  );
}

// One job's forecast next to what its events actually recorded.
export function JobCost({ job, events, mode }) {
  const forecast = useForecast(job.format);
  if (!forecast) return <p className="empty">No forecast available.</p>;
  const agents = [...new Set(forecast.steps.filter((s) => s.high > 0).map((s) => s.agent))];
  const actual = (name) => events.filter((e) => e.type === "cost" && e.agent === name).reduce((sum, e) => sum + e.cost_usd, 0);
  const planned = (name) => {
    const rows = forecast.steps.filter((s) => s.agent === name);
    return { low: rows.reduce((n, s) => n + s.low, 0), high: rows.reduce((n, s) => n + s.high, 0) };
  };
  const total = agents.reduce((sum, name) => sum + actual(name), 0);
  return (
    <div className="stack">
      <p className="muted">
        {mode === "mock" ? "Simulated: mock agents report the forecast, and nothing is charged." : "Actual is what Claude's usage reports came to."}
        {" "}Whole-video ranges include rough guesses for steps not built yet.
      </p>
      <div className="table-wrap">
        <table className="pb">
          <thead><tr><th>Agent</th><th>Forecast</th><th>{mode === "mock" ? "Simulated" : "Actual"}</th></tr></thead>
          <tbody>
            {agents.map((name) => (
              <tr key={name}>
                <td style={{ color: agentColor(name) }}>{name}</td>
                <td className="mono">{rangeText(planned(name))}</td>
                <td className="mono">{money(actual(name))}</td>
              </tr>
            ))}
            <tr>
              <td><b>Whole video</b></td>
              <td className="mono"><b>{rangeText(forecast.full_video)}</b></td>
              <td className="mono"><b>{money(total)}</b></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
