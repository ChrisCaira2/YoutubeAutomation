import React, { useState } from "react";

function CopyButton({ text }) {
  const [done, setDone] = useState(false);
  const copy = () => navigator.clipboard.writeText(text).then(() => {
    setDone(true);
    setTimeout(() => setDone(false), 1500);
  });
  return <button className="btn ghost small" onClick={copy}>{done ? "Copied" : "Copy"}</button>;
}

function Copyable({ label, text }) {
  return (
    <div className="pkg-block">
      <div className="pkg-head"><b>{label}</b><CopyButton text={text} /></div>
      <p className="pkg-text">{text}</p>
    </div>
  );
}

// Everything you paste into YouTube Studio when you upload: thumbnails to download, text to copy.
export default function PackageView({ p, job, mode }) {
  if (!p) return <p className="empty">No packages yet.</p>;
  const media = (name) => `/api/media/${job.id}/${name}`;
  return (
    <div className="stack">
      <div className="pkg-grid">
        {p.options.map((o, i) => (
          <div key={i} className="pkg">
            {mode === "live" && o.thumbnail_path ? (
              <a href={media(o.thumbnail_path)} download={`job-${job.id}-${o.thumbnail_path}`} title="Download this thumbnail">
                <img className="thumb" src={`${media(o.thumbnail_path)}?v=${job.updated_at}`} alt={o.thumbnail_concept} />
              </a>
            ) : (
              <div className="thumb-ph">{o.thumbnail_concept}</div>
            )}
            <div className="pkg-head"><span className="pkg-title">{o.title}</span><CopyButton text={o.title} /></div>
            <span className="muted small">{o.title.length} characters · {o.thumbnail_concept}</span>
          </div>
        ))}
      </div>
      {mode === "live" && p.options.some((o) => o.thumbnail_path) && (
        <details>
          <summary>How they look at phone size</summary>
          <img className="sheet" src={`${media("thumbnails-phone.png")}?v=${job.updated_at}`} alt="Each thumbnail at full size and at phone size" />
        </details>
      )}
      <Copyable label="Description, with chapters, sources and photo credits" text={p.description} />
      <Copyable label="Tags" text={p.tags.join(", ")} />
      <Copyable label="Pinned comment" text={p.pinned_comment} />
      <p><b>AI disclosure:</b> {p.ai_disclosure.required ? "Required" : "Not required"}. {p.ai_disclosure.reason}</p>
    </div>
  );
}
