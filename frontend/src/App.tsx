import { useState } from "react";
import { motion } from "motion/react";
import "./App.css";
import { LibraryView } from "./components/LibraryView";
import { ReviewView } from "./components/ReviewView";

type Tab = "library" | "review";

const TABS: { id: Tab; label: string }[] = [
  { id: "library", label: "Library" },
  { id: "review", label: "Review" },
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
            {tab === t.id && (
              <motion.span
                layoutId="tab-pill"
                className="tab-pill"
                transition={{ type: "spring", bounce: 0.15, duration: 0.4 }}
              />
            )}
            <span className="tab-label">{t.label}</span>
          </button>
        ))}
      </div>

      {tab === "library" && <LibraryView />}
      {tab === "review" && <ReviewView />}
    </div>
  );
}

export default App;
