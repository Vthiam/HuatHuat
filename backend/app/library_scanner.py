"""Syncs law_library/ (real files on disk) with the database (structured
records describing those files). Two entry points:

  scan_inbox(db)     -- classify + file whatever's dropped in inbox/
  scan_templates(db) -- register new template files, detect what every
                         template (new or existing) depends on

Statute files/clauses are entirely feature/sso-diff-history's territory --
this module never parses statute text itself, it only ever reads existing
Clause rows (created by that branch) to resolve what a template cites.

Both functions are safe to call repeatedly: they check for an existing
Document (by file_path) or DependencyEdge (by from/to/clause) before
creating a new one.
"""
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from .config import (
    CLASSIFICATION_CONFIDENCE_THRESHOLD,
    INBOX_DIR,
    LAW_LIBRARY_DIR,
    STATUTES_DIR,
    TEMPLATES_DIR,
    TRACKED_ACTS,
)
from .models import Clause, DependencyEdge, Document, DocumentGenre, DocumentSource
from .services.classifier import CitationMatch, classify_document, detect_citations


@dataclass
class ClassifiedDocument:
    document: Document
    confidence: float
    needs_confirmation: bool


@dataclass
class InboxScanResult:
    classified: List[ClassifiedDocument] = field(default_factory=list)


@dataclass
class TemplateScanResult:
    new_documents: List[Document] = field(default_factory=list)
    edges_created: List[DependencyEdge] = field(default_factory=list)
    needs_confirmation: List[Document] = field(default_factory=list)


def _relative_path(path: Path) -> str:
    return str(path.relative_to(LAW_LIBRARY_DIR))


def _ensure_library_dirs() -> None:
    for d in (INBOX_DIR, STATUTES_DIR, TEMPLATES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _display_name(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def scan_inbox(db: Session) -> InboxScanResult:
    _ensure_library_dirs()
    result = InboxScanResult()

    for path in sorted(INBOX_DIR.glob("*")):
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8", errors="ignore")
        classification = classify_document(text, filename=path.name)

        target_dir = STATUTES_DIR if classification.genre == DocumentGenre.STATUTE else TEMPLATES_DIR
        dest = target_dir / path.name
        counter = 1
        while dest.exists():
            dest = target_dir / f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(dest))

        needs_confirmation = classification.confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD

        document = Document(
            name=_display_name(dest),
            genre=classification.genre,
            # Filed via the inbox means a human dropped it in without saying
            # which folder it belongs in -- it's still firm-provenance, even
            # if the AI decided its genre is STATUTE (e.g. someone pasted in
            # regulation text by hand instead of waiting for the SSO sync).
            source=DocumentSource.FIRM,
            file_path=_relative_path(dest),
            classification_source=classification.source,
            classification_confidence=classification.confidence,
        )
        db.add(document)
        db.flush()

        result.classified.append(ClassifiedDocument(document, classification.confidence, needs_confirmation))

    db.commit()
    return result


def _find_clause(statute_documents: List[Document], tracked_acts: list, act_id: Optional[str], clause_ref: Optional[str]) -> Optional[Clause]:
    if act_id is None or clause_ref is None:
        return None
    act_cfg = next((a for a in tracked_acts if a["act_id"] == act_id), None)
    if act_cfg is None:
        return None
    for sd in statute_documents:
        if sd.name != act_cfg["name"]:
            continue
        for clause in sd.clauses:
            if clause.clause_ref == clause_ref:
                return clause
    return None


def _upsert_edge_for_match(
    db: Session, from_doc: Document, match: CitationMatch, statute_documents: List[Document], tracked_acts: list
) -> Optional[DependencyEdge]:
    if match.target_type == "clause":
        clause = _find_clause(statute_documents, tracked_acts, match.act_id, match.clause_ref)
        if clause is None:
            return None
        existing = (
            db.query(DependencyEdge)
            .filter_by(from_document_id=from_doc.id, to_document_id=clause.document_id, to_clause_id=clause.id)
            .first()
        )
        if existing is not None:
            return None
        edge = DependencyEdge(
            from_document_id=from_doc.id,
            to_document_id=clause.document_id,
            to_clause_id=clause.id,
            excerpt=match.excerpt,
        )
    elif match.target_type == "document" and match.document_id is not None:
        if match.document_id == from_doc.id:
            return None
        existing = (
            db.query(DependencyEdge)
            .filter_by(from_document_id=from_doc.id, to_document_id=match.document_id, to_clause_id=None)
            .first()
        )
        if existing is not None:
            return None
        edge = DependencyEdge(
            from_document_id=from_doc.id,
            to_document_id=match.document_id,
            to_clause_id=None,
            excerpt=match.excerpt,
        )
    else:
        return None

    db.add(edge)
    db.flush()
    return edge


def scan_templates(db: Session, tracked_acts: Optional[list] = None) -> TemplateScanResult:
    """tracked_acts defaults to config.TRACKED_ACTS; overridable for tests
    so they don't need a real seeded Act to exercise citation matching."""
    _ensure_library_dirs()
    tracked_acts = tracked_acts if tracked_acts is not None else TRACKED_ACTS
    result = TemplateScanResult()

    existing_by_path = {
        d.file_path: d for d in db.query(Document).filter(Document.genre == DocumentGenre.TEMPLATE).all()
    }

    for path in sorted(TEMPLATES_DIR.glob("*")):
        if not path.is_file():
            continue
        rel_path = _relative_path(path)
        if rel_path in existing_by_path:
            continue
        doc = Document(
            name=_display_name(path),
            genre=DocumentGenre.TEMPLATE,
            source=DocumentSource.FIRM,
            file_path=rel_path,
        )
        db.add(doc)
        db.flush()
        existing_by_path[rel_path] = doc
        result.new_documents.append(doc)

    db.commit()

    all_templates = list(existing_by_path.values())
    statute_documents = db.query(Document).filter(Document.genre == DocumentGenre.STATUTE).all()

    for doc in all_templates:
        full_path = LAW_LIBRARY_DIR / doc.file_path
        if not full_path.exists():
            continue
        text = full_path.read_text(encoding="utf-8", errors="ignore")
        other_documents = [d for d in all_templates if d.id != doc.id]

        matches = detect_citations(text, tracked_acts, other_documents)
        for match in matches:
            edge = _upsert_edge_for_match(db, doc, match, statute_documents, tracked_acts)
            if edge is not None:
                result.edges_created.append(edge)

    db.commit()

    for doc in all_templates:
        if doc.classification_confidence is not None and doc.classification_confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD:
            result.needs_confirmation.append(doc)

    return result
