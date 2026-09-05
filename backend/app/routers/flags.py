import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..config import REPORTS_DIR
from ..db import get_db
from ..models import Flag

router = APIRouter(prefix="/api/flags", tags=["flags"])


def _enum_value(x):
    return x.value if x is not None else None


def _highlighted_pdf_url_for(document) -> Optional[str]:
    """Highlighted PDFs aren't persisted anywhere in the DB (no schema
    change needed for this) -- pdf_highlighter names them deterministically
    from the source document's filename, so we just check whether that
    file happens to exist on disk. Returned as a URL path served by
    main.py's /reports static mount, so the frontend can link straight to
    it rather than being handed an unusable local filesystem path."""
    if not document.file_path.lower().endswith(".pdf"):
        return None
    stem = Path(document.file_path).stem
    filename = f"{stem}_flagged.pdf"
    candidate = REPORTS_DIR / "flagged" / filename
    return f"/reports/flagged/{filename}" if candidate.exists() else None


def _to_out(flag: Flag) -> schemas.FlagOut:
    return schemas.FlagOut(
        id=flag.id,
        change_event_id=flag.change_event_id,
        document_id=flag.document_id,
        document_name=flag.document.name,
        flag_type=_enum_value(flag.flag_type),
        depth=flag.depth,
        via_document_id=flag.via_document_id,
        via_document_name=flag.via_document.name if flag.via_document else None,
        recommendation_text=flag.recommendation_text,
        recommendation_source=_enum_value(flag.recommendation_source),
        status=_enum_value(flag.status),
        created_at=flag.created_at,
        highlighted_pdf_url=_highlighted_pdf_url_for(flag.document),
    )


@router.get("", response_model=list[schemas.FlagOut])
def list_flags(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Flag)
    if status:
        query = query.filter(Flag.status == status)
    flags = query.order_by(Flag.created_at.desc()).all()
    return [_to_out(f) for f in flags]


def _resolve(flag_id: int, new_status: str, db: Session) -> schemas.FlagOut:
    flag = db.query(Flag).filter(Flag.id == flag_id).first()
    if flag is None:
        raise HTTPException(status_code=404, detail="Flag not found")
    # Accepting/rejecting only records a review decision -- it never
    # rewrites the flagged document's actual content.
    flag.status = new_status
    flag.resolved_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(flag)
    return _to_out(flag)


@router.post("/{flag_id}/accept", response_model=schemas.FlagOut)
def accept_flag(flag_id: int, db: Session = Depends(get_db)):
    return _resolve(flag_id, "accepted", db)


@router.post("/{flag_id}/reject", response_model=schemas.FlagOut)
def reject_flag(flag_id: int, db: Session = Depends(get_db)):
    return _resolve(flag_id, "rejected", db)
