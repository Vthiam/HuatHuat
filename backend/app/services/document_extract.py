"""Extracts plain text from a real firm document, whatever format it's
actually in. Ingestion, classification, and citation detection all
operate on the returned string -- none of them need to know or care
whether the source was a .txt, .docx, or .pdf file.
"""
from pathlib import Path


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".docx":
        return _extract_docx(path)

    if suffix == ".pdf":
        return _extract_pdf(path)

    return ""


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


def _extract_pdf(path: Path) -> str:
    import fitz

    text_parts = []
    with fitz.open(str(path)) as pdf:
        for page in pdf:
            text_parts.append(page.get_text())
    return "\n".join(text_parts)
