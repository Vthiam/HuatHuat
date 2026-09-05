import type {
  ChangeEvent,
  CheckSsoResult,
  DocumentDetail,
  Document,
  DocumentText,
  Flag,
  Graph,
  Redline,
  ScanResult,
  ScheduleStatus,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${options?.method ?? "GET"} ${path} failed (${resp.status}): ${body}`);
  }
  return resp.json();
}

async function upload<T>(path: string, file: File): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch(`${BASE_URL}${path}`, { method: "POST", body: formData });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`upload ${path} failed (${resp.status}): ${body}`);
  }
  return resp.json();
}

export const api = {
  listDocuments: () => request<Document[]>("/api/documents"),
  getDocument: (id: number) => request<DocumentDetail>(`/api/documents/${id}`),
  getDocumentText: (id: number) => request<DocumentText>(`/api/documents/${id}/text`),
  uploadDocument: (file: File) => upload<ScanResult>("/api/upload", file),

  listChanges: () => request<ChangeEvent[]>("/api/changes"),
  getRedline: (changeEventId: number) => request<Redline>(`/api/changes/${changeEventId}/redline`),

  listFlags: (status?: string) =>
    request<Flag[]>(`/api/flags${status ? `?status=${status}` : ""}`),
  acceptFlag: (id: number) => request<Flag>(`/api/flags/${id}/accept`, { method: "POST" }),
  rejectFlag: (id: number) => request<Flag>(`/api/flags/${id}/reject`, { method: "POST" }),

  getGraph: (changeEventId: number) => request<Graph>(`/api/graph/${changeEventId}`),

  getScheduleStatus: () => request<ScheduleStatus>("/api/schedule-status"),
  runScan: () => request<ScanResult>("/api/scan", { method: "POST" }),
  runCheckSso: (body: {
    live?: boolean;
    simulate?: boolean;
    clause_ref?: string;
    override_schedule?: boolean;
  }) => request<CheckSsoResult>("/api/check-sso", { method: "POST", body: JSON.stringify(body) }),
};
