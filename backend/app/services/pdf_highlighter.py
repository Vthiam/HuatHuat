"""Turns a Flag into something you can actually see: opens the flagged
document's real PDF, highlights the exact excerpt that ties it to the
changed clause, and attaches the AI's recommendation as a sticky-note
annotation right there. Saves to a NEW file -- the original is never
touched, consistent with the rest of this project's rule that nothing
downstream of the statute mirror is ever auto-edited.

.docx highlighting is out of scope for this branch (PDF was the format
decided to matter most for the demo) -- a .docx Flag still gets its
recommendation surfaced in the report/CLI, just without an in-file
annotation. Documented limitation, not a silent gap.
"""
import logging
from pathlib import Path
from typing import Optional

from ..config import LAW_LIBRARY_DIR, REPORTS_DIR
from ..models import Document, Flag

logger = logging.getLogger(__name__)

FLAGGED_DIR_NAME = "flagged"


def _search_with_fallback(page, excerpt: str):
    rects = page.search_for(excerpt)
    if rects:
        return rects

    words = excerpt.split()
    if len(words) > 6:
        shorter = " ".join(words[:6])
        rects = page.search_for(shorter)
        if rects:
            return rects

    return []


def highlight_flag_in_pdf(document: Document, flag: Flag, excerpt: str) -> Optional[Path]:
    if not document.file_path.lower().endswith(".pdf"):
        return None

    source_path = LAW_LIBRARY_DIR / document.file_path
    if not source_path.exists():
        logger.warning("PDF not found for highlighting: %s", source_path)
        return None

    import fitz

    with fitz.open(str(source_path)) as pdf:
        found_any = False
        first_rect = None

        for page in pdf:
            rects = _search_with_fallback(page, excerpt) if excerpt.strip() else []
            for rect in rects:
                page.add_highlight_annot(rect)
                found_any = True
                if first_rect is None:
                    first_rect = (page, rect)

        if not found_any:
            logger.warning(
                "Could not locate excerpt %r in %s -- no highlight added", excerpt[:60], source_path
            )
            return None

        if first_rect is not None and flag.recommendation_text:
            note_page, rect = first_rect
            note_point = fitz.Point(rect.x1 + 10, rect.y0)
            annot = note_page.add_text_annot(note_point, flag.recommendation_text)
            annot.set_info(title="AI-suggested review note")

        flagged_dir = REPORTS_DIR / FLAGGED_DIR_NAME
        flagged_dir.mkdir(parents=True, exist_ok=True)
        output_path = flagged_dir / f"{source_path.stem}_flagged.pdf"
        pdf.save(str(output_path))

    return output_path
