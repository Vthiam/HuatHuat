"""Orchestrates the second half of the pipeline: given a ChangeEvent
(created entirely by feature/sso-diff-history), figure out what it means
and who it affects.

  1. Summarize the change in plain English (fills in ChangeEvent's
     legal_effect_summary, left null by the branch that created it)
  2. Walk the dependency graph to find every affected document, direct
     and transitive
  3. Draft a per-document recommendation and write a Flag row

Never touches statute text, never edits a document's own content, never
fires a notification -- those are feature/sso-diff-history's and
feature/cli-reports-review's jobs respectively. This module's only output
is Flag rows (plus filling in the one ChangeEvent field left for it).
"""
from typing import List

from sqlalchemy.orm import Session

from .config import LAW_LIBRARY_DIR
from .models import ChangeEvent, DependencyEdge, Document, Flag
from .services import llm
from .services.graph_service import AffectedDocument, find_affected_documents


def _excerpt_for(db: Session, item: AffectedDocument, changed_clause_id: int) -> str:
    if item.via_document is None:
        edge = (
            db.query(DependencyEdge)
            .filter_by(from_document_id=item.document.id, to_clause_id=changed_clause_id)
            .first()
        )
    else:
        edge = (
            db.query(DependencyEdge)
            .filter_by(from_document_id=item.document.id, to_document_id=item.via_document.id, to_clause_id=None)
            .first()
        )
    return edge.excerpt if edge is not None else ""


def _read_document_text(document: Document) -> str:
    """Reads the document's actual file content so the LLM can scan the
    whole thing for conflicting passages, not just the short citation
    excerpt. Returns "" if the file isn't on disk (e.g. in unit tests that
    only build DB rows) -- recommend_impact degrades gracefully to
    excerpt-only analysis in that case."""
    if not document.file_path:
        return ""
    full_path = LAW_LIBRARY_DIR / document.file_path
    if not full_path.exists():
        return ""
    try:
        return full_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def process_change_event(db: Session, change_event: ChangeEvent) -> List[Flag]:
    """Safe to call more than once for the same ChangeEvent: the summary
    is only generated once (skipped if already set), and a Flag is only
    created if one doesn't already exist for that (change_event, document)
    pair."""
    clause = change_event.clause

    if change_event.legal_effect_summary is None:
        # Kept as a plain-English summary for reports/UI even though it's
        # no longer fed into recommend_impact below -- that call now
        # grounds itself directly in the raw old/new clause text instead
        # of a (possibly lossy) intermediate summary.
        summary_text, summary_source = llm.summarize_change(
            clause.clause_ref, clause.heading or "", change_event.old_text, change_event.new_text
        )
        change_event.legal_effect_summary = summary_text
        change_event.summary_source = summary_source
        db.flush()

    affected = find_affected_documents(db, clause.id)
    created_flags: List[Flag] = []

    for item in affected:
        existing = (
            db.query(Flag)
            .filter_by(change_event_id=change_event.id, document_id=item.document.id)
            .first()
        )
        if existing is not None:
            continue

        excerpt = _excerpt_for(db, item, clause.id)
        document_text = _read_document_text(item.document)
        rec_text, rec_source = llm.recommend_impact(
            document_name=item.document.name,
            document_text=document_text,
            document_excerpt=excerpt,
            clause_ref=clause.clause_ref,
            old_clause_text=change_event.old_text,
            new_clause_text=change_event.new_text,
            dependency_path=item.dependency_path,
        )

        flag = Flag(
            change_event_id=change_event.id,
            document_id=item.document.id,
            flag_type=item.flag_type,
            depth=item.depth,
            via_document_id=item.via_document.id if item.via_document else None,
            recommendation_text=rec_text,
            recommendation_source=rec_source,
        )
        db.add(flag)
        db.flush()
        created_flags.append(flag)

    db.commit()
    return created_flags


def process_all(db: Session, change_events: List[ChangeEvent]) -> List[Flag]:
    all_flags: List[Flag] = []
    for event in change_events:
        all_flags.extend(process_change_event(db, event))
    return all_flags
