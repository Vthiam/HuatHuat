import { useEffect, useState } from "react";
import { api } from "../api";
import type { ChangeEvent, Redline, ScheduleStatus } from "../types";

function Redlined({ redline }: { redline: Redline }) {
  return (
    <div className="redline">
      {redline.ops.map((op, i) => {
        if (op.op === "equal") return <span key={i}>{op.text} </span>;
        if (op.op === "insert")
          return (
            <span className="insert" key={i}>
              {op.text}{" "}
            </span>
          );
        return (
          <span className="delete" key={i}>
            {op.text}{" "}
          </span>
        );
      })}
    </div>
  );
}

export function ChangeFeedView() {
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [schedule, setSchedule] = useState<ScheduleStatus | null>(null);
  const [mode, setMode] = useState<"live" | "simulate">("simulate");
  const [clauseRef, setClauseRef] = useState("4");
  const [overrideSchedule, setOverrideSchedule] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRedline, setSelectedRedline] = useState<Redline | null>(null);

  const loadChanges = async () => {
    try {
      setChanges(await api.listChanges());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const loadSchedule = async () => {
    try {
      setSchedule(await api.getScheduleStatus());
    } catch {
      // schedule status is a nicety, not critical -- ignore failure
    }
  };

  useEffect(() => {
    loadChanges();
    loadSchedule();
  }, []);

  const runScan = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.runScan();
      setMessage(
        `Scan: ${result.classified_from_inbox.length} classified from inbox, ` +
          `${result.new_documents.length} new template(s), ${result.edges_created} dependency edge(s) detected.`
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const runCheckSso = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.runCheckSso({
        live: mode === "live",
        simulate: mode === "simulate",
        clause_ref: mode === "simulate" ? clauseRef : undefined,
        override_schedule: overrideSchedule,
      });
      if (!result.ok) {
        setError(result.message ?? "check-sso refused to run.");
      } else {
        setMessage(
          `Detected ${result.change_events.length} change(s), raised ${result.flags.length} flag(s).`
        );
        await loadChanges();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const viewRedline = async (id: number) => {
    try {
      setSelectedRedline(await api.getRedline(id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      {error && <div className="error-box">{error}</div>}

      <div className="controls-row">
        <button onClick={runScan} disabled={busy}>
          Run scan (ingest library)
        </button>
      </div>

      <div className="controls-row">
        <label>
          <input type="radio" checked={mode === "simulate"} onChange={() => setMode("simulate")} />
          Simulate
        </label>
        {mode === "simulate" && (
          <input
            type="text"
            value={clauseRef}
            onChange={(e) => setClauseRef(e.target.value)}
            placeholder="clause ref"
            style={{ width: 60 }}
          />
        )}
        <label>
          <input type="radio" checked={mode === "live"} onChange={() => setMode("live")} />
          Live (real SSO fetch)
        </label>
        {mode === "live" && (
          <label>
            <input
              type="checkbox"
              checked={overrideSchedule}
              onChange={(e) => setOverrideSchedule(e.target.checked)}
            />
            Override schedule
          </label>
        )}
        <button className="primary" onClick={runCheckSso} disabled={busy}>
          Check SSO now
        </button>
        {schedule && (
          <span className={`schedule-note ${schedule.within_window ? "" : "outside"}`}>
            {schedule.within_window ? "Within" : "Outside"} SSO's automated window (
            {schedule.window_description})
          </span>
        )}
      </div>

      {message && (
        <div className="error-box" style={{ background: "#e3f1e8", color: "#2f7d4f" }}>
          {message}
        </div>
      )}

      <div className="two-col">
        <div className="panel">
          <strong style={{ fontSize: 13 }}>Change history</strong>
          {changes.length === 0 ? (
            <div className="empty-state">No changes detected yet.</div>
          ) : (
            changes.map((c) => (
              <div className="change-item" key={c.id} onClick={() => viewRedline(c.id)}>
                <div>
                  <strong>s.{c.clause_ref}</strong> of {c.document_name}{" "}
                  <span className="badge heuristic">{c.source}</span>
                </div>
                {c.legal_effect_summary && <div className="summary">{c.legal_effect_summary}</div>}
              </div>
            ))
          )}
        </div>

        <div className="panel">
          <strong style={{ fontSize: 13 }}>Redline</strong>
          {!selectedRedline ? (
            <div className="empty-state">Click a change on the left to see what changed.</div>
          ) : (
            <Redlined redline={selectedRedline} />
          )}
        </div>
      </div>
    </div>
  );
}
