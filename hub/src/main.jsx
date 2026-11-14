import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { get } from "./api.js";
import App from "./App.jsx";
import ClipCentral from "./views/ClipCentral.jsx";
import "./styles.css";

// The same build serves every wing: the studios get the full hub, the clipper (port 8002) its own command screen.
function Root() {
  const [wing, setWing] = useState(null);
  useEffect(() => {
    get("/api/state").then((s) => setWing(s.clipper ? "clips" : "studio")).catch(() => setWing("studio"));
  }, []);
  if (!wing) return <div className="boot"><p>Connecting…</p></div>;
  return wing === "clips" ? <ClipCentral /> : <App />;
}

createRoot(document.getElementById("root")).render(<Root />);
