import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ClauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clause_ref: str
    heading: Optional[str]
    text: str
    version: int
    updated_at: datetime.datetime


class DependencyEdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_document_id: int
    to_document_id: int
    to_document_name: str
    to_clause_id: Optional[int]
    to_clause_ref: Optional[str]
    excerpt: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    genre: str
    source: str
    file_path: str
    last_synced_at: Optional[datetime.datetime]
    classification_source: Optional[str]
    classification_confidence: Optional[float]


class DocumentDetailOut(DocumentOut):
    clauses: List[ClauseOut] = []
    dependencies: List[DependencyEdgeOut] = []  # edges FROM this document


class DocumentTextOut(BaseModel):
    text: str
    is_pdf: bool
    pdf_url: Optional[str] = None  # served by the /library static mount, for an <iframe> preview


class ChangeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clause_id: int
    clause_ref: str
    document_name: str
    old_text: str
    new_text: str
    source: str
    legal_effect_summary: Optional[str]
    summary_source: Optional[str]
    detected_at: datetime.datetime


class DiffOpOut(BaseModel):
    op: str
    text: str


class RedlineOut(BaseModel):
    change_event: ChangeEventOut
    ops: List[DiffOpOut]


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_event_id: int
    document_id: int
    document_name: str
    flag_type: str
    depth: int
    via_document_id: Optional[int]
    via_document_name: Optional[str]
    recommendation_text: Optional[str]
    recommendation_source: Optional[str]
    cited_excerpt: Optional[str]
    original_sentence: Optional[str]
    suggested_replacement: Optional[str]
    document_edited: bool
    human_edit_text: Optional[str]
    status: str
    created_at: datetime.datetime
    highlighted_pdf_url: Optional[str]


class SelfEditRequest(BaseModel):
    human_edit_text: str


class ScanClassifiedOut(BaseModel):
    document_id: int
    document_name: str
    genre: str
    confidence: float
    source: str
    needs_confirmation: bool


class ScanResultOut(BaseModel):
    classified_from_inbox: List[ScanClassifiedOut]
    new_documents: List[str]
    edges_created: int
    report_path: str
    new_flags: List[FlagOut] = []  # flags raised immediately against pre-existing law changes


class CheckSsoRequest(BaseModel):
    live: bool = False
    simulate: bool = False
    clause_ref: Optional[str] = None
    override_schedule: bool = False


class CheckSsoResultOut(BaseModel):
    ok: bool
    message: Optional[str] = None
    change_events: List[ChangeEventOut] = []
    flags: List[FlagOut] = []
    report_path: Optional[str] = None


class ScheduleStatusOut(BaseModel):
    within_window: bool
    window_description: str


class GraphNodeOut(BaseModel):
    id: str
    label: str
    kind: str  # 'clause' | 'document'
    highlight: str  # 'changed' | 'direct' | 'transitive' | 'none'


class GraphEdgeOut(BaseModel):
    source: str
    target: str


class GraphOut(BaseModel):
    nodes: List[GraphNodeOut]
    edges: List[GraphEdgeOut]
