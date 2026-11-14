import React, { useEffect, useState } from "react";
import { get } from "../api.js";

export default function Playbook() {
  const [pb, setPb] = useState(null);
  const [area, setArea] = useState("all");
  useEffect(() => {
    get("/api/playbook").then(setPb).catch(() => {});
  }, []);
  if (!pb) return <div className="panel"><p className="muted">Loading the Playbook…</p></div>;

  const areas = ["all", ...new Set(pb.entries.map((e) => e.area))];
  const entries = pb.entries.filter((e) => area === "all" || e.area === area);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Playbook</h2>
        <span className="muted">Version {pb.version} · as of {pb.as_of} · {pb.entries.length} rules</span>
      </div>
      <p className="muted pb-note">{pb.notes}</p>
      <div className="seg wrap" role="group" aria-label="Area">
        {areas.map((a) => (
          <button key={a} className={area === a ? "active" : ""} onClick={() => setArea(a)}>{a}</button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="pb">
          <thead>
            <tr><th>Area</th><th>Rule</th><th>Confidence</th><th>Source</th><th>Our data</th></tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.area}</td>
                <td>{e.rule}</td>
                <td><span className={`conf ${e.confidence}`}>{e.confidence}</span></td>
                <td>{e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.source}</a> : e.source}</td>
                <td className="muted">{e.our_data ?? "No data yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
