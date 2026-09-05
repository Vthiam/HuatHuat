from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import ChangeEvent
from ..services.diff_engine import word_diff

router = APIRouter(prefix="/api/changes", tags=["changes"])


def _enum_value(x):
    return x.value if x is not None else None


def _to_out(event: ChangeEvent) -> schemas.ChangeEventOut:
    clause = event.clause
    return schemas.ChangeEventOut(
        id=event.id,
        clause_id=event.clause_id,
        clause_ref=clause.clause_ref,
        document_name=clause.document.name,
        old_text=event.old_text,
        new_text=event.new_text,
        source=_enum_value(event.source),
        legal_effect_summary=event.legal_effect_summary,
        summary_source=_enum_value(event.summary_source),
        detected_at=event.detected_at,
    )


@router.get("", response_model=list[schemas.ChangeEventOut])
def list_changes(db: Session = Depends(get_db)):
    events = db.query(ChangeEvent).order_by(ChangeEvent.detected_at.desc()).all()
    return [_to_out(e) for e in events]


@router.get("/{change_event_id}/redline", response_model=schemas.RedlineOut)
def get_redline(change_event_id: int, db: Session = Depends(get_db)):
    event = db.query(ChangeEvent).filter(ChangeEvent.id == change_event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Change event not found")

    ops = word_diff(event.old_text, event.new_text)
    return schemas.RedlineOut(
        change_event=_to_out(event),
        ops=[schemas.DiffOpOut(op=o.op, text=o.text) for o in ops],
    )
