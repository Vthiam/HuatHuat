from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import impact_service, schemas
from ..config import REPORTS_DIR
from ..db import get_db
from ..models import Flag

router = APIRouter(prefix="/api/flags", tags=["flags"])


def _enum_value(x):
    return x.value if x is not None else None


def _flagged_copy_url_for(document) -> Optional[str]:
    """Highlighted PDFs / commented DOCXs aren't persisted anywhere in the
    DB (no schema change needed) -- pdf_highlighter.py/docx_commenter.py
    name them deterministically from the source filename, so we just check
    whether that file happens to exist on disk. Returned as a URL path
    served by main.py's /reports static mount."""
    lower = document.file_path.lower()
    if lower.endswith(".pdf"):
        ext = "pdf"
    elif lower.endswith(".docx"):
        ext = "docx"
    else:
        return None
    stem = Path(document.file_path).stem
    filename = f"{stem}_flagged.{ext}"
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
        original_sentence=flag.original_sentence,
        suggested_replacement=flag.suggested_replacement,
        document_edited=flag.document_edited,
        human_edit_text=flag.human_edit_text,
        status=_enum_value(flag.status),
        created_at=flag.created_at,
        highlighted_pdf_url=_flagged_copy_url_for(flag.document),
    )


@router.get("", response_model=list[schemas.FlagOut])
def list_flags(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Flag)
    if status:
        query = query.filter(Flag.status == status)
    flags = query.order_by(Flag.created_at.desc()).all()
    return [_to_out(f) for f in flags]


def _get_flag_or_404(flag_id: int, db: Session) -> Flag:
    flag = db.query(Flag).filter(Flag.id == flag_id).first()
    if flag is None:
        raise HTTPException(status_code=404, detail="Flag not found")
    return flag


@router.post("/{flag_id}/accept", response_model=schemas.FlagOut)
def accept_flag(flag_id: int, db: Session = Depends(get_db)):
    """Accepting DOES apply the AI's suggested_replacement into the real
    .docx/.txt document (impact_service.resolve_flag_accept) -- the one
    deliberate exception to "never auto-edit a document" in this project.
    PDFs and flags without a verified original_sentence are a review
    decision only; nothing to apply."""
    flag = _get_flag_or_404(flag_id, db)
    impact_service.resolve_flag_accept(db, flag)
    db.refresh(flag)
    return _to_out(flag)


@router.post("/{flag_id}/reject", response_model=schemas.FlagOut)
def reject_flag(flag_id: int, db: Session = Depends(get_db)):
    flag = _get_flag_or_404(flag_id, db)
    impact_service.resolve_flag_reject(db, flag)
    db.refresh(flag)
    return _to_out(flag)


@router.post("/{flag_id}/self-edit", response_model=schemas.FlagOut)
def self_edit_flag(flag_id: int, request: schemas.SelfEditRequest, db: Session = Depends(get_db)):
    """Reject the AI's specific wording, but apply the human's own
    replacement instead -- "reject button pressed, allow user to self
    edit". Requires the flag to have a verified original_sentence (a
    concrete quote to replace); otherwise there's nothing to swap in for
    (still marks the flag rejected, just doesn't touch the file)."""
    flag = _get_flag_or_404(flag_id, db)
    impact_service.resolve_flag_reject(db, flag, human_edit_text=request.human_edit_text)
    db.refresh(flag)
    return _to_out(flag)
