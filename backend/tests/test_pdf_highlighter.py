import hashlib
from types import SimpleNamespace

import pytest

from app.services import pdf_highlighter


def _make_pdf(path, text):
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    pdf.save(str(path))
    pdf.close()


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def fake_library(tmp_path, monkeypatch):
    law_library = tmp_path / "law_library"
    statutes_dir = law_library / "statutes"
    reports_dir = law_library / "reports"
    statutes_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    monkeypatch.setattr(pdf_highlighter, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(pdf_highlighter, "REPORTS_DIR", reports_dir)
    return {"root": law_library, "statutes": statutes_dir, "reports": reports_dir}


def test_highlights_found_excerpt_and_leaves_original_untouched(fake_library):
    pdf_path = fake_library["statutes"] / "checklist.pdf"
    _make_pdf(pdf_path, "These exemptions are set out in section 4 of the Act.")
    original_hash = _sha256(pdf_path)

    document = SimpleNamespace(file_path="statutes/checklist.pdf")
    flag = SimpleNamespace(recommendation_text="Consider reviewing this against the new section 4 wording.")

    output_path = pdf_highlighter.highlight_flag_in_pdf(
        document, flag, excerpt="These exemptions are set out in section 4 of the Act."
    )

    assert output_path is not None
    assert output_path.exists()
    assert output_path.parent.name == "flagged"

    assert _sha256(pdf_path) == original_hash  # original never modified

    import fitz

    with fitz.open(str(output_path)) as out_pdf:
        page = out_pdf[0]
        annots = list(page.annots())
        kinds = [a.type[1] for a in annots]  # (type_id, type_name)
        assert "Highlight" in kinds
        assert "Text" in kinds


def test_returns_none_for_non_pdf_document(fake_library):
    document = SimpleNamespace(file_path="templates/workflow.docx")
    flag = SimpleNamespace(recommendation_text="note")
    assert pdf_highlighter.highlight_flag_in_pdf(document, flag, excerpt="anything") is None


def test_returns_none_when_excerpt_not_found(fake_library):
    pdf_path = fake_library["statutes"] / "checklist.pdf"
    _make_pdf(pdf_path, "Completely unrelated content with no overlap at all.")

    document = SimpleNamespace(file_path="statutes/checklist.pdf")
    flag = SimpleNamespace(recommendation_text="note")

    result = pdf_highlighter.highlight_flag_in_pdf(
        document, flag, excerpt="This phrase does not appear anywhere in the document text."
    )
    assert result is None


def test_returns_none_when_source_file_missing(fake_library):
    document = SimpleNamespace(file_path="statutes/does_not_exist.pdf")
    flag = SimpleNamespace(recommendation_text="note")
    assert pdf_highlighter.highlight_flag_in_pdf(document, flag, excerpt="anything") is None
