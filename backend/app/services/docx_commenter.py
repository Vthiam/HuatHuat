"""Turns a Flag into a real Microsoft Word comment -- opens the flagged
.docx, finds the run(s) containing the exact conflicting sentence, and
attaches the AI's recommendation as a genuine Word comment anchored to it
(python-docx's Document.add_comment, which writes real OOXML
word/comments.xml -- this opens as an actual comment balloon in Word,
not a lookalike). Saves to a NEW file; the original is never touched.

This is the .docx equivalent of pdf_highlighter.py's highlight+sticky-note
-- same idea (flag the exact passage, attach the note), different file
format's native annotation mechanism.
"""
import logging
from pathlib import Path
from typing import Optional

from ..config import LAW_LIBRARY_DIR, REPORTS_DIR
from ..models import Document, Flag

logger = logging.getLogger(__name__)

FLAGGED_DIR_NAME = "flagged"


def add_comment_to_docx(document: Document, flag: Flag, conflicting_sentence: str) -> Optional[Path]:
    if not document.file_path.lower().endswith(".docx"):
        return None

    source_path = LAW_LIBRARY_DIR / document.file_path
    if not source_path.exists():
        logger.warning("DOCX not found for commenting: %s", source_path)
        return None
    if not conflicting_sentence or not conflicting_sentence.strip():
        return None

    import docx

    doc = docx.Document(str(source_path))

    target_runs = None
    for paragraph in doc.paragraphs:
        if conflicting_sentence not in paragraph.text:
            continue
        # If one run happens to contain the whole sentence, anchor tightly
        # to it. Otherwise the sentence is split across runs (common when
        # a document has mixed formatting) -- anchor to the whole
        # paragraph's runs instead, a disclosed simplification rather than
        # attempting to split individual runs at the exact character
        # boundary.
        single = next((r for r in paragraph.runs if conflicting_sentence in r.text), None)
        target_runs = [single] if single is not None else list(paragraph.runs)
        break

    if not target_runs:
        logger.warning("Could not locate sentence %r in %s -- no comment added", conflicting_sentence[:60], source_path)
        return None

    comment_text = flag.recommendation_text or "Flagged for review -- see the dashboard for details."
    doc.add_comment(runs=target_runs, text=comment_text, author="HuatHuat AI", initials="AI")

    flagged_dir = REPORTS_DIR / FLAGGED_DIR_NAME
    flagged_dir.mkdir(parents=True, exist_ok=True)
    output_path = flagged_dir / f"{source_path.stem}_flagged.docx"
    doc.save(str(output_path))

    return output_path
