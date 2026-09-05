export interface Clause {
  id: number;
  clause_ref: string;
  heading: string | null;
  text: string;
  version: number;
  updated_at: string;
}

export interface DependencyEdge {
  id: number;
  from_document_id: number;
  to_document_id: number;
  to_document_name: string;
  to_clause_id: number | null;
  to_clause_ref: string | null;
  excerpt: string;
}

export interface Document {
  id: number;
  name: string;
  genre: string;
  source: string;
  file_path: string;
  last_synced_at: string | null;
  classification_source: string | null;
  classification_confidence: number | null;
}

export interface DocumentDetail extends Document {
  clauses: Clause[];
  dependencies: DependencyEdge[];
}

export interface DocumentText {
  text: string;
  is_pdf: boolean;
  pdf_url: string | null;
}

export interface ChangeEvent {
  id: number;
  clause_id: number;
  clause_ref: string;
  document_name: string;
  old_text: string;
  new_text: string;
  source: string;
  legal_effect_summary: string | null;
  summary_source: string | null;
  detected_at: string;
}

export interface DiffOp {
  op: "equal" | "insert" | "delete";
  text: string;
}

export interface Redline {
  change_event: ChangeEvent;
  ops: DiffOp[];
}

export interface Flag {
  id: number;
  change_event_id: number;
  document_id: number;
  document_name: string;
  flag_type: "direct_dependency" | "transitive_dependency";
  depth: number;
  via_document_id: number | null;
  via_document_name: string | null;
  recommendation_text: string | null;
  recommendation_source: string | null;
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  highlighted_pdf_url: string | null;
}

export interface ScanClassified {
  document_id: number;
  document_name: string;
  genre: string;
  confidence: number;
  source: string;
  needs_confirmation: boolean;
}

export interface ScanResult {
  classified_from_inbox: ScanClassified[];
  new_documents: string[];
  edges_created: number;
  report_path: string;
}

export interface CheckSsoResult {
  ok: boolean;
  message: string | null;
  change_events: ChangeEvent[];
  flags: Flag[];
  report_path: string | null;
}

export interface ScheduleStatus {
  within_window: boolean;
  window_description: string;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "clause" | "document";
  highlight: "changed" | "direct" | "transitive" | "none";
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
