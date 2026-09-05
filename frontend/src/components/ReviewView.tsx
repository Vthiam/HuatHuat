import { useEffect, useState } from "react";
import { api } from "../api";
import type { Flag } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function ReviewView() {
  const [status, setStatus] = useState("pending");
  const [flags, setFlags] = useState<Flag[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try {
      setFlags(await api.listFlags(status));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const act = async (id: number, action: "accept" | "reject") => {
    try {
      if (action === "accept") await api.acceptFlag(id);
      else await api.rejectFlag(id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      {error && <div className="error-box">{error}</div>}

      <div className="controls-row">
        <label>
          Status:
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ marginLeft: 6 }}>
            <option value="pending">pending</option>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <button onClick={load}>Refresh</button>
      </div>

      {flags.length === 0 ? (
        <div className="empty-state">No {status} flags.</div>
      ) : (
        flags.map((f) => (
          <div className="flag-card" key={f.id}>
            <div className="flag-head">
              <span className="flag-doc-name">{f.document_name}</span>
              <span className="badge template">{f.flag_type === "direct_dependency" ? "direct" : "transitive"}</span>
              {f.recommendation_source && <span className={`badge ${f.recommendation_source}`}>{f.recommendation_source}</span>}
              <span className={`badge ${f.status}`}>{f.status}</span>
            </div>
            {f.via_document_name && (
              <div className="meta">depends on this indirectly, via {f.via_document_name}</div>
            )}
            <div className="recommendation">{f.recommendation_text}</div>
            {f.highlighted_pdf_url && (
              <a className="link" href={`${API_BASE}${f.highlighted_pdf_url}`} target="_blank" rel="noreferrer">
                Open highlighted PDF &rarr;
              </a>
            )}
            {f.status === "pending" && (
              <div className="actions">
                <button className="accept" onClick={() => act(f.id, "accept")}>
                  Accept
                </button>
                <button className="reject" onClick={() => act(f.id, "reject")}>
                  Reject
                </button>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
