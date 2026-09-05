from app.models import DocumentGenre
from app.services.classifier import CitationMatch, detect_citations, classify_document

STATUTE_TEXT = """
PERSONAL DATA PROTECTION ACT 2012
2020 REVISED EDITION
An Act to govern the collection, use and disclosure of personal data.

PART 1
PRELIMINARY

Short title
1. This Act is the Personal Data Protection Act 2012.

Interpretation
2. In this Act, unless the context otherwise requires --
"advisory committee" means an advisory committee appointed under section 7;

Purpose
3. The purpose of this Act is to govern the collection, use and disclosure
of personal data by organisations.

Application of Act
4. Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation on an
individual acting in a personal or domestic capacity.
"""

TEMPLATE_TEXT = """
PDPA Applicability Checklist (Firm Template)

Before advising a client on a data-handling engagement, confirm whether
the Personal Data Protection Act 2012 applies. These exemptions are set
out in section 4 of the Act.
"""


def test_classifies_statute_shaped_text_as_statute():
    result = classify_document(STATUTE_TEXT, filename="PDPA2012.txt")
    assert result.genre == DocumentGenre.STATUTE
    assert 0.0 < result.confidence <= 1.0


def test_classifies_template_shaped_text_as_template():
    result = classify_document(TEMPLATE_TEXT, filename="checklist.txt")
    assert result.genre == DocumentGenre.TEMPLATE
    assert 0.0 < result.confidence <= 1.0


TRACKED = [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"]}]


def test_detects_direct_section_citation():
    text = "These exemptions are set out in section 4 of the Sample Act 2024."
    matches = detect_citations(text, TRACKED, other_documents=[])
    assert any(m.target_type == "clause" and m.clause_ref == "4" and m.act_id == "SAMPLEACT2024" for m in matches)


def test_no_false_positive_without_act_mention():
    text = "Refer to section 4 of some unrelated statute."
    matches = detect_citations(text, TRACKED, other_documents=[])
    assert not any(m.target_type == "clause" for m in matches)


class _FakeDoc:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def test_detects_document_to_document_reference():
    other = [_FakeDoc(1, "Sample Applicability Checklist")]
    text = "Before proceeding, run the Sample Applicability Checklist."
    matches = detect_citations(text, [], other_documents=other)
    assert any(m.target_type == "document" and m.document_id == 1 for m in matches)


def test_dedupe_keeps_single_match_per_target():
    text = "See section 4 and again section 4 of the Sample Act 2024."
    matches = detect_citations(text, TRACKED, other_documents=[])
    clause_matches = [m for m in matches if m.target_type == "clause"]
    assert len(clause_matches) == 1
