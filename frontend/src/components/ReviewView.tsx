import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import ReactFlow, { Background, type Node as FlowNode } from "reactflow";
import "reactflow/dist/style.css";
import { api, BASE_URL } from "../api";
import { HIGHLIGHT_COLOR, layout } from "./graphLayout";
import type { ChangeEvent, Flag, Graph, Redline, ScheduleStatus } from "../types";

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

function FlagReviewPanel({
  flag,
  onAccept,
  onReject,
  onSelfEdit,
}: {
  flag: Flag;
  onAccept: (id: number) => void;
  onReject: (id: number) => void;
  onSelfEdit: (id: number, text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(flag.original_sentence ?? "");
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    setEditing(false);
    setEditText(flag.original_sentence ?? "");
  }, [flag.id, flag.original_sentence]);

  const submitSelfEdit = () => {
    onSelfEdit(flag.id, editText);
    setEditing(false);
  };

  return (
    <div>
      <div className="flag-head">
        <span className="flag-doc-name">{flag.document_name}</span>
        <span className="badge template">{flag.flag_type === "direct_dependency" ? "direct" : "transitive"}</span>
        {flag.recommendation_source && (
          <span className={`badge ${flag.recommendation_source}`}>{flag.recommendation_source}</span>
        )}
        <span className={`badge ${flag.status}`}>{flag.status}</span>
        {flag.document_edited && <span className="badge accepted">document updated</span>}
      </div>
      {flag.via_document_name && (
        <div className="meta">depends on this indirectly, via {flag.via_document_name}</div>
      )}

      {flag.cited_excerpt && (
        <>
          <div className="panel-title" style={{ marginTop: 16 }}>
            Where this document is affected
          </div>
          <div className="cited-excerpt">&ldquo;{flag.cited_excerpt}&rdquo;</div>
        </>
      )}

      <div className="panel-title" style={{ marginTop: 16 }}>
        AI assessment
      </div>
      <div className="recommendation">{flag.recommendation_text}</div>

      {flag.original_sentence && flag.suggested_replacement ? (
        <>
          <div className="panel-title" style={{ marginTop: 4 }}>
            What the AI wants to change
          </div>
          <div className="diff-block">
            <div className="diff-line diff-delete">{flag.original_sentence}</div>
            <div className="diff-line diff-insert">{flag.suggested_replacement}</div>
          </div>
        </>
      ) : (
        <p className="self-edit-hint">
          The AI didn't find one specific sentence to rewrite here -- use the excerpt above and
          the assessment to judge for yourself, then Accept, Reject, or Reject with your own edit.
        </p>
      )}

      {flag.human_edit_text && <div className="meta">Your note: "{flag.human_edit_text}"</div>}

      {flag.highlighted_pdf_url && (
        <a className="link" href={`${BASE_URL}${flag.highlighted_pdf_url}`} target="_blank" rel="noreferrer">
          Open highlighted PDF &rarr;
        </a>
      )}

      {flag.status === "pending" && (
        <>
          <div className="actions" style={{ marginTop: 16 }}>
            <button className="accept" onClick={() => onAccept(flag.id)}>
              Accept
            </button>
            <button className="reject" onClick={() => onReject(flag.id)}>
              Reject
            </button>
            <button onClick={() => setEditing((v) => !v)}>
              {flag.original_sentence ? "Reject with your own edit" : "Reject with a note"}
            </button>
          </div>
          <AnimatePresence>
            {editing && (
              <motion.div
                className="self-edit"
                style={{ transformOrigin: "top" }}
                initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scaleY: 0.95 }}
                animate={{ opacity: 1, scaleY: 1 }}
                exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scaleY: 0.95 }}
                transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1] }}
              >
                {flag.original_sentence ? (
                  <p className="self-edit-hint">Replaces the sentence above in the real document.</p>
                ) : (
                  <p className="self-edit-hint">
                    No specific sentence was flagged here, so this is recorded as a note only -- it
                    won't edit the document.
                  </p>
                )}
                <textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  placeholder={
                    flag.original_sentence
                      ? "Replacement text for the flagged sentence"
                      : "Explain why you're rejecting this, or what you did instead"
                  }
                  rows={3}
                />
                <div className="actions">
                  <button className="primary" onClick={submitSelfEdit} disabled={!editText.trim()}>
                    {flag.original_sentence ? "Submit self-edit" : "Submit note"}
                  </button>
                  <button onClick={() => setEditing(false)}>Cancel</button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}

export function ReviewView() {
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedFlagId, setSelectedFlagId] = useState<number | null>(null);
  const [redline, setRedline] = useState<Redline | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [schedule, setSchedule] = useState<ScheduleStatus | null>(null);
  const [mode, setMode] = useState<"live" | "simulate">("simulate");
  const [clauseRef, setClauseRef] = useState("4");
  const [overrideSchedule, setOverrideSchedule] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [graphExpanded, setGraphExpanded] = useState(false);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!graphExpanded) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setGraphExpanded(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [graphExpanded]);

  const loadChanges = async () => {
    try {
      const cs = await api.listChanges();
      setChanges(cs);
      if (cs.length > 0 && selectedId === null) setSelectedId(cs[0].id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const loadFlags = async () => {
    try {
      setFlags(await api.listFlags());
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
    loadFlags();
    loadSchedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedId === null) return;
    setRedline(null);
    setGraph(null);
    api.getRedline(selectedId).then(setRedline).catch((e) => setError((e as Error).message));
    api.getGraph(selectedId).then(setGraph).catch((e) => setError((e as Error).message));
  }, [selectedId]);

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
        await loadFlags();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (id: number, action: "accept" | "reject") => {
    try {
      if (action === "accept") await api.acceptFlag(id);
      else await api.rejectFlag(id);
      await loadFlags();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const selfEdit = async (id: number, text: string) => {
    try {
      await api.selfEditFlag(id, text);
      await loadFlags();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const { nodes, edges } = useMemo(() => (graph ? layout(graph) : { nodes: [], edges: [] }), [graph]);

  const selectedChange = changes.find((c) => c.id === selectedId) ?? null;

  const documentFlags = useMemo(
    () =>
      flags.filter(
        (f) => f.change_event_id === selectedId && (statusFilter === "all" || f.status === statusFilter)
      ),
    [flags, selectedId, statusFilter]
  );

  useEffect(() => {
    if (documentFlags.length === 0) {
      setSelectedFlagId(null);
      return;
    }
    if (!documentFlags.some((f) => f.id === selectedFlagId)) {
      setSelectedFlagId(documentFlags[0].id);
    }
  }, [documentFlags, selectedFlagId]);

  const selectedFlag = documentFlags.find((f) => f.id === selectedFlagId) ?? null;

  const reviewSectionRef = useRef<HTMLDivElement>(null);

  const handleNodeClick = (_: unknown, node: FlowNode) => {
    const match = node.id.match(/^doc-(\d+)$/);
    if (!match) return; // the clause node, or a node with no id we recognise
    const documentId = Number(match[1]);
    const flag = flags.find((f) => f.change_event_id === selectedId && f.document_id === documentId);
    if (!flag) return; // the root statute-document node -- nothing to review
    setStatusFilter(flag.status);
    setSelectedFlagId(flag.id);
    setGraphExpanded(false); // so the update is actually visible, not hidden behind the fullscreen graph
    reviewSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  return (
    <div>
      {error && <div className="error-box">{error}</div>}
      {message && (
        <div className="error-box" style={{ background: "var(--green-soft)", color: "var(--green)" }}>
          {message}
        </div>
      )}

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

      {changes.length === 0 ? (
        <div className="empty-state">No changes detected yet. Check SSO above to find some.</div>
      ) : (
        <div className="review-columns">
          <div className="panel review-col-list">
            <div className="panel-title">Changes</div>
            {changes.map((c, i) => (
              <motion.div
                className={`change-item ${selectedId === c.id ? "selected" : ""}`}
                key={c.id}
                onClick={() => setSelectedId(c.id)}
                initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: Math.min(i * 0.04, 0.3), ease: [0.23, 1, 0.32, 1] }}
              >
                <strong>s.{c.clause_ref}</strong> of {c.document_name}{" "}
                <span className="badge heuristic">{c.source}</span>
              </motion.div>
            ))}
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={selectedId ?? "none"}
              className="panel review-col-main"
              initial={{ opacity: 0, filter: "blur(2px)" }}
              animate={{ opacity: 1, filter: "blur(0px)" }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
            >
              {selectedChange && (
                <>
                  <div className="panel-title">Reviewing</div>
                  <div style={{ marginBottom: 4 }}>
                    <strong>s.{selectedChange.clause_ref}</strong> of {selectedChange.document_name}{" "}
                    <span className="badge heuristic">{selectedChange.source}</span>
                  </div>
                  {selectedChange.legal_effect_summary && (
                    <p className="recommendation" style={{ marginTop: 8 }}>
                      {selectedChange.legal_effect_summary}
                    </p>
                  )}

                  <div className="panel-title" style={{ marginTop: 16 }}>
                    What changed in the law
                  </div>
                  {!redline ? <div className="empty-state">Loading...</div> : <Redlined redline={redline} />}
                </>
              )}

              <div
                ref={reviewSectionRef}
                className="controls-row"
                style={{ marginTop: 20, marginBottom: 12, paddingBottom: 12 }}
              >
                <div className="panel-title" style={{ marginBottom: 0 }}>
                  Review a document
                </div>
                <label>
                  Show:
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    style={{ marginLeft: 6 }}
                  >
                    <option value="pending">pending</option>
                    <option value="accepted">accepted</option>
                    <option value="rejected">rejected</option>
                    <option value="all">all</option>
                  </select>
                </label>
                {documentFlags.length > 0 && (
                  <label>
                    Document:
                    <select
                      value={selectedFlagId ?? ""}
                      onChange={(e) => setSelectedFlagId(Number(e.target.value))}
                      style={{ marginLeft: 6 }}
                    >
                      {documentFlags.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.document_name}
                          {statusFilter === "all" ? ` — ${f.status}` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>

              {!selectedFlag ? (
                <div className="empty-state">
                  No {statusFilter === "all" ? "" : statusFilter} flags for this change.
                </div>
              ) : (
                <AnimatePresence mode="wait">
                  <motion.div
                    key={selectedFlag.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15, ease: [0.23, 1, 0.32, 1] }}
                  >
                    <FlagReviewPanel
                      flag={selectedFlag}
                      onAccept={(id) => act(id, "accept")}
                      onReject={(id) => act(id, "reject")}
                      onSelfEdit={selfEdit}
                    />
                  </motion.div>
                </AnimatePresence>
              )}
            </motion.div>
          </AnimatePresence>

          {graphExpanded && <div className="graph-backdrop" onClick={() => setGraphExpanded(false)} />}

          <AnimatePresence mode="wait">
            <motion.div
              key={selectedId ?? "none"}
              className={`panel review-col-graph ${graphExpanded ? "expanded" : ""}`}
              initial={{ opacity: 0, filter: "blur(2px)" }}
              animate={{ opacity: 1, filter: "blur(0px)" }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
            >
              <div className="panel-title" style={{ marginBottom: 12 }}>
                Effects down the line
              </div>
              <div className="legend">
                <span>
                  <span className="dot" style={{ background: HIGHLIGHT_COLOR.changed }} />
                  Changed clause
                </span>
                <span>
                  <span className="dot" style={{ background: HIGHLIGHT_COLOR.direct }} />
                  Direct
                </span>
                <span>
                  <span className="dot" style={{ background: HIGHLIGHT_COLOR.transitive }} />
                  Transitive
                </span>
              </div>
              <p className="meta" style={{ marginTop: -8, marginBottom: 10 }}>
                Click a direct or transitive document to review it below.
              </p>
              <div className="graph-wrap">
                <ReactFlow
                  key={graphExpanded ? "expanded" : "normal"}
                  nodes={nodes}
                  edges={edges}
                  onNodeClick={handleNodeClick}
                  fitView
                >
                  <Background />
                </ReactFlow>
                <button
                  className="expand-toggle"
                  onClick={() => setGraphExpanded((v) => !v)}
                  aria-label={graphExpanded ? "Collapse graph" : "Expand graph"}
                  title={graphExpanded ? "Collapse" : "Expand"}
                >
                  {graphExpanded ? (
                    <svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M8 3v3a2 2 0 0 1-2 2H3" />
                      <path d="M21 8h-3a2 2 0 0 1-2-2V3" />
                      <path d="M3 16h3a2 2 0 0 1 2 2v3" />
                      <path d="M16 21v-3a2 2 0 0 1 2-2h3" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
                      <path d="M16 3h3a2 2 0 0 1 2 2v3" />
                      <path d="M8 21H5a2 2 0 0 1-2-2v-3" />
                      <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
                    </svg>
                  )}
                </button>
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
