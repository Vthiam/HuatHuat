import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Document, DocumentDetail, DocumentText, ScheduleStatus } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function LibraryView() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selected, setSelected] = useState<DocumentDetail | null>(null);
  const [preview, setPreview] = useState<DocumentText | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [schedule, setSchedule] = useState<ScheduleStatus | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setDocuments(await api.listDocuments());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    api.getScheduleStatus().then(setSchedule).catch(() => undefined);
  }, []);

  const selectDocument = async (id: number) => {
    setPreview(null);
    setError(null);
    try {
      const detail = await api.getDocument(id);
      setSelected(detail);
      setPreview(await api.getDocumentText(id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const handleUploadClick = () => fileInputRef.current?.click();

  const handleFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;

    setUploading(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.uploadDocument(file);
      const classified = result.classified_from_inbox[0];
      setMessage(
        classified
          ? `Uploaded "${file.name}" -- classified as ${classified.genre} (${Math.round(classified.confidence * 100)}% confidence, ${classified.source}).`
          : `Uploaded "${file.name}".`
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const checkForUpdates = async () => {
    setChecking(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.runCheckSso({ live: true });
      if (!result.ok) {
        setMessage(result.message);
      } else if (result.change_events.length === 0) {
        setMessage("Checked SSO -- no changes to the tracked statute since last check.");
      } else {
        setMessage(
          `Checked SSO -- ${result.change_events.length} change(s) found, ${result.flags.length} document(s) flagged. See the Change Feed / Review tabs.`
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  return (
    <div>
      {error && <div className="error-box">{error}</div>}
      {message && (
        <div className="error-box" style={{ background: "#e3f1e8", color: "#2f7d4f" }}>
          {message}
        </div>
      )}

      <div className="controls-row">
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.docx,.pdf"
          style={{ display: "none" }}
          onChange={handleFileChosen}
        />
        <button className="primary" onClick={handleUploadClick} disabled={uploading}>
          {uploading ? "Uploading..." : "Upload document"}
        </button>
        <button onClick={checkForUpdates} disabled={checking}>
          {checking ? "Checking..." : "Check for law updates"}
        </button>
        <button onClick={load}>Refresh</button>
        <span className="schedule-note">{documents.length} document(s) in the library</span>
        {schedule && (
          <span className={`schedule-note ${schedule.within_window ? "" : "outside"}`}>
            {schedule.within_window ? "within" : "outside"} SSO's automated window
          </span>
        )}
      </div>

      <div className="two-col">
        <div className="panel">
          {loading ? (
            <div className="empty-state">Loading...</div>
          ) : documents.length === 0 ? (
            <div className="empty-state">No documents yet. Upload one, or check for law updates above.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Genre</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr
                    key={d.id}
                    className={`clickable ${selected?.id === d.id ? "selected" : ""}`}
                    onClick={() => selectDocument(d.id)}
                  >
                    <td>{d.name}</td>
                    <td>
                      <span className={`badge ${d.genre}`}>{d.genre}</span>
                    </td>
                    <td>{d.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel detail-panel">
          {!selected ? (
            <div className="empty-state">Click a document to open it -- see its real content, clauses, and dependencies.</div>
          ) : (
            <>
              <h3>{selected.name}</h3>
              <div className="meta" style={{ marginBottom: 12 }}>
                {selected.file_path}
                {selected.classification_source && (
                  <>
                    {" "}
                    &middot; classified via{" "}
                    <span className={`badge ${selected.classification_source}`}>
                      {selected.classification_source}
                    </span>{" "}
                    ({Math.round((selected.classification_confidence ?? 0) * 100)}%)
                  </>
                )}
              </div>

              <strong style={{ fontSize: 13 }}>Document content</strong>
              {!preview ? (
                <div className="empty-state">Loading preview...</div>
              ) : preview.is_pdf && preview.pdf_url ? (
                <iframe
                  src={`${API_BASE}${preview.pdf_url}`}
                  title={selected.name}
                  style={{ width: "100%", height: 380, border: "1px solid var(--border)", borderRadius: 8, marginTop: 6 }}
                />
              ) : (
                <div className="clause-block" style={{ maxHeight: 380, overflowY: "auto", whiteSpace: "pre-wrap" }}>
                  {preview.text || <em>No extractable text in this file.</em>}
                </div>
              )}

              {selected.clauses.length > 0 && (
                <>
                  <strong style={{ fontSize: 13, display: "block", marginTop: 14 }}>Clauses</strong>
                  {selected.clauses.map((c) => (
                    <div className="clause-block" key={c.id}>
                      <strong>
                        s.{c.clause_ref} {c.heading}
                      </strong>{" "}
                      <span className="meta">(v{c.version})</span>
                    </div>
                  ))}
                </>
              )}

              {selected.dependencies.length > 0 && (
                <>
                  <strong style={{ fontSize: 13, display: "block", marginTop: 14 }}>Depends on</strong>
                  {selected.dependencies.map((e) => (
                    <div className="clause-block" key={e.id}>
                      <strong>
                        {e.to_clause_ref ? `s.${e.to_clause_ref} of ${e.to_document_name}` : e.to_document_name}
                      </strong>
                      <div className="clause-text">"{e.excerpt}"</div>
                    </div>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
