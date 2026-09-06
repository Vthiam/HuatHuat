"""Orchestrates the second half of the pipeline: given a ChangeEvent
(created entirely by feature/sso-diff-history), figure out what it means
and who it affects.

  1. Summarize the change in plain English (fills in ChangeEvent's
     legal_effect_summary, left null by the branch that created it)
  2. Walk the dependency graph to find every affected document, direct
     and transitive
  3. Draft a per-document recommendation and write a Flag row

Also owns resolving a Flag once a human reviews it (resolve_flag_accept /
resolve_flag_reject) -- both cli.py's `review` command and the API's
routers/flags.py call these same two functions, so accept/reject behavior
(including the real document edit on accept) lives in exactly one place.

Never touches statute text directly (that's feature/sso-diff-history's
job) and never fires a notification (that's feature/cli-reports-review's
job) -- but, per explicit product decision, resolve_flag_accept DOES
rewrite a document's own content for .docx/.txt, via document_editor.py.
"""
import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from .config import LAW_LIBRARY_DIR
from .models import ChangeEvent, DependencyEdge, Document, Flag, FlagStatus
from .services import document_editor, llm
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
        rec = llm.recommend_impact(
            document_name=item.document.name,
            document_text=document_text,
            document_excerpt=excerpt,
            clause_ref=clause.clause_ref,
            old_clause_text=change_event.old_text,
            new_clause_text=change_event.new_text,
            dependency_path=item.dependency_path,
        )

        # Only trust conflicting_sentence if it's a verbatim match in the
        # real document text -- an LLM can occasionally paraphrase instead
        # of quoting exactly, and document_editor.py needs an exact match
        # to safely apply an edit later. A near-miss is surfaced as a flag
        # with the explanation but no auto-editable suggestion, rather
        # than silently failing to find it at accept time.
        verified_sentence = None
        verified_replacement = None
        if rec.conflicting_sentence and rec.conflicting_sentence in document_text:
            verified_sentence = rec.conflicting_sentence
            verified_replacement = rec.suggested_replacement

        flag = Flag(
            change_event_id=change_event.id,
            document_id=item.document.id,
            flag_type=item.flag_type,
            depth=item.depth,
            via_document_id=item.via_document.id if item.via_document else None,
            recommendation_text=rec.explanation,
            recommendation_source=rec.source,
            original_sentence=verified_sentence,
            suggested_replacement=verified_replacement,
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


def resolve_flag_accept(db: Session, flag: Flag) -> Flag:
    """Accepts the AI's suggestion. For .docx/.txt with a verified
    original_sentence + suggested_replacement, this actually rewrites the
    document (document_editor.py) -- explicit product decision, and the
    one deliberate exception to "never auto-edit a document's content" in
    this project. PDFs, and any flag without both fields (heuristic
    fallback, or the model found nothing to change), are accepted as a
    review decision only -- nothing to apply.

    Safe to call on an already-resolved flag: it will just re-attempt the
    edit (harmless no-op if the sentence is no longer present, e.g. it was
    already applied) rather than erroring.
    """
    flag.status = FlagStatus.ACCEPTED
    flag.resolved_at = datetime.datetime.utcnow()

    if flag.original_sentence and flag.suggested_replacement:
        applied = document_editor.apply_edit(flag.document, flag.original_sentence, flag.suggested_replacement)
        flag.document_edited = flag.document_edited or applied

    db.commit()
    return flag


def resolve_flag_reject(db: Session, flag: Flag, human_edit_text: Optional[str] = None) -> Flag:
    """Rejects the AI's specific suggested wording. If the human supplies
    their own text (self-edit), it's always recorded on the flag as an
    audit trail of why/how they rejected it. When original_sentence also
    exists, that text is additionally applied to the real document in
    place of original_sentence -- the same way an accepted edit would be --
    so this becomes "reject the AI's answer, but still make the
    correction, in my own words" rather than just "do nothing". Without
    original_sentence there's no anchor to edit the document against, so
    the human's text is kept purely as a note. With no self-edit text
    supplied at all, this is just a plain rejection with no note or
    document change."""
    flag.status = FlagStatus.REJECTED
    flag.resolved_at = datetime.datetime.utcnow()

    if human_edit_text:
        flag.human_edit_text = human_edit_text
        if flag.original_sentence:
            applied = document_editor.apply_edit(flag.document, flag.original_sentence, human_edit_text)
            flag.document_edited = flag.document_edited or applied

    db.commit()
    return flag
