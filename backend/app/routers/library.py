from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..config import LAW_LIBRARY_DIR
from ..db import get_db
from ..models import DependencyEdge, Document
from ..services.document_extract import extract_text

router = APIRouter(prefix="/api/documents", tags=["library"])


def _enum_value(x):
    return x.value if x is not None else None


@router.get("", response_model=list[schemas.DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.genre, Document.name).all()
    return [
        schemas.DocumentOut(
            id=d.id,
            name=d.name,
            genre=_enum_value(d.genre),
            source=_enum_value(d.source),
            file_path=d.file_path,
            last_synced_at=d.last_synced_at,
            classification_source=_enum_value(d.classification_source),
            classification_confidence=d.classification_confidence,
        )
        for d in docs
    ]


@router.get("/{document_id}", response_model=schemas.DocumentDetailOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    edges = db.query(DependencyEdge).filter(DependencyEdge.from_document_id == doc.id).all()

    return schemas.DocumentDetailOut(
        id=doc.id,
        name=doc.name,
        genre=_enum_value(doc.genre),
        source=_enum_value(doc.source),
        file_path=doc.file_path,
        last_synced_at=doc.last_synced_at,
        classification_source=_enum_value(doc.classification_source),
        classification_confidence=doc.classification_confidence,
        clauses=[schemas.ClauseOut.model_validate(c) for c in doc.clauses],
        dependencies=[
            schemas.DependencyEdgeOut(
                id=e.id,
                from_document_id=e.from_document_id,
                to_document_id=e.to_document_id,
                to_document_name=e.to_document.name,
                to_clause_id=e.to_clause_id,
                to_clause_ref=e.to_clause.clause_ref if e.to_clause_id else None,
                excerpt=e.excerpt,
            )
            for e in edges
        ],
    )


@router.get("/{document_id}/text", response_model=schemas.DocumentTextOut)
def get_document_text(document_id: int, db: Session = Depends(get_db)):
    """Extracted text for preview, using the exact same extractor
    ingestion uses -- so what you see here is what the classifier and
    citation detector actually saw, not a separate rendering path."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    full_path = LAW_LIBRARY_DIR / doc.file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    is_pdf = doc.file_path.lower().endswith(".pdf")
    return schemas.DocumentTextOut(
        text=extract_text(full_path),
        is_pdf=is_pdf,
        pdf_url=f"/library/{doc.file_path}" if is_pdf else None,
    )
