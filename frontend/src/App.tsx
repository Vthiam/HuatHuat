import { useState } from "react";
import "./App.css";
import { ChangeFeedView } from "./components/ChangeFeedView";
import { GraphView } from "./components/GraphView";
import { LibraryView } from "./components/LibraryView";
import { ReviewView } from "./components/ReviewView";

type Tab = "library" | "changes" | "review" | "graph";

const TABS: { id: Tab; label: string }[] = [
  { id: "library", label: "Library" },
  { id: "changes", label: "Change Feed" },
  { id: "review", label: "Review" },
  { id: "graph", label: "Graph" },
];

function App() {
  const [tab, setTab] = useState<Tab>("library");

  return (
    <div className="app">
      <div className="app-header">
        <div>
          <h1>HuatHuat</h1>
          <div className="subtitle">Statute-change resilience for a firm's document library</div>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "library" && <LibraryView />}
      {tab === "changes" && <ChangeFeedView />}
      {tab === "review" && <ReviewView />}
      {tab === "graph" && <GraphView />}
    </div>
  );
}

export default App;
