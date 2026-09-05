"""Scan/check-sso/upload as HTTP actions -- scan and check-sso call the
exact same cli.py functions the CLI uses, so the API and CLI share one
orchestration path rather than duplicating the pipeline logic."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import schemas
from ..cli import cmd_check_sso, cmd_scan
from ..config import INBOX_DIR
from ..db import get_db
from ..services.sso_client import SSO_SCRAPE_WINDOW_END_HOUR_SGT, SSO_SCRAPE_WINDOW_START_HOUR_SGT, should_run_now
from .changes import _to_out as change_event_to_out
from .flags import _to_out as flag_to_out

router = APIRouter(prefix="/api", tags=["actions"])

ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".docx", ".pdf"}


@router.get("/schedule-status", response_model=schemas.ScheduleStatusOut)
def schedule_status():
    return schemas.ScheduleStatusOut(
        within_window=should_run_now(),
        window_description=f"{SSO_SCRAPE_WINDOW_START_HOUR_SGT}am-{SSO_SCRAPE_WINDOW_END_HOUR_SGT}am Singapore time",
    )


def _scan_result_to_out(result) -> schemas.ScanResultOut:
    return schemas.ScanResultOut(
        classified_from_inbox=[
            schemas.ScanClassifiedOut(
                document_id=c.document.id,
                document_name=c.document.name,
                genre=c.document.genre.value,
                confidence=c.confidence,
                source=c.document.classification_source.value if c.document.classification_source else "heuristic",
                needs_confirmation=c.needs_confirmation,
            )
            for c in result.inbox_result.classified
        ],
        new_documents=[d.name for d in result.template_result.new_documents],
        edges_created=len(result.template_result.edges_created),
        report_path=str(result.report_path),
    )


@router.post("/scan", response_model=schemas.ScanResultOut)
def run_scan(db: Session = Depends(get_db)):
    return _scan_result_to_out(cmd_scan(db))


@router.post("/upload", response_model=schemas.ScanResultOut)
async def upload_document(db: Session = Depends(get_db), file: UploadFile = File(...)):
    """Saves the uploaded file into law_library/inbox/, then immediately
    runs the same scan cmd_scan does -- so the response tells you exactly
    how the AI classified it, not just that the upload succeeded."""
    safe_name = Path(file.filename or "upload").name  # strips any directory components
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
        )

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    dest = INBOX_DIR / safe_name
    counter = 1
    while dest.exists():
        dest = INBOX_DIR / f"{Path(safe_name).stem}_{counter}{suffix}"
        counter += 1

    contents = await file.read()
    dest.write_bytes(contents)

    return _scan_result_to_out(cmd_scan(db))


@router.post("/check-sso", response_model=schemas.CheckSsoResultOut)
def run_check_sso(request: schemas.CheckSsoRequest, db: Session = Depends(get_db)):
    result = cmd_check_sso(db, request.live, request.simulate, request.clause_ref, request.override_schedule)

    if not result.ok:
        return schemas.CheckSsoResultOut(ok=False, message=result.message)

    return schemas.CheckSsoResultOut(
        ok=True,
        change_events=[change_event_to_out(e) for e in result.change_events],
        flags=[flag_to_out(f) for f in result.flags],
        report_path=str(result.report_path) if result.report_path else None,
    )
