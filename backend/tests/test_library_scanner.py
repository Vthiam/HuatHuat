import pytest

from app import library_scanner
from app.models import DependencyEdge, Document, DocumentGenre
from app.testing.fixtures import build_sample_library


@pytest.fixture()
def fake_library(tmp_path, monkeypatch):
    law_library = tmp_path / "law_library"
    inbox = law_library / "inbox"
    statutes = law_library / "statutes"
    templates = law_library / "templates"
    for d in (inbox, statutes, templates):
        d.mkdir(parents=True)

    monkeypatch.setattr(library_scanner, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(library_scanner, "INBOX_DIR", inbox)
    monkeypatch.setattr(library_scanner, "STATUTES_DIR", statutes)
    monkeypatch.setattr(library_scanner, "TEMPLATES_DIR", templates)
    return {"root": law_library, "inbox": inbox, "statutes": statutes, "templates": templates}


PDPA_TRACKED = [{"act_id": "PDPA2012", "name": "Personal Data Protection Act 2012", "clause_refs": ["4"]}]
SAMPLE_TRACKED = [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"]}]


def test_scan_templates_registers_new_documents(db_session, fake_library):
    (fake_library["templates"] / "checklist.txt").write_text(
        "These exemptions are set out in section 4 of the PDPA."
    )

    result = library_scanner.scan_templates(db_session, tracked_acts=PDPA_TRACKED)

    assert len(result.new_documents) == 1
    assert result.new_documents[0].genre == DocumentGenre.TEMPLATE
    assert db_session.query(Document).count() == 1


def test_scan_templates_creates_direct_dependency_edge(db_session, fake_library):
    lib = build_sample_library(db_session)
    db_session.commit()

    (fake_library["templates"] / "checklist.txt").write_text(
        "These exemptions are set out in section 4 of the Sample Act 2024."
    )

    result = library_scanner.scan_templates(db_session, tracked_acts=SAMPLE_TRACKED)
    new_doc = result.new_documents[0]

    edges = db_session.query(DependencyEdge).filter_by(to_clause_id=lib["clause"].id).all()
    assert any(e.from_document_id == new_doc.id for e in edges)


def test_scan_templates_creates_document_to_document_edge(db_session, fake_library):
    (fake_library["templates"] / "checklist.txt").write_text("A standalone checklist with no citations.")
    (fake_library["templates"] / "workflow.txt").write_text(
        "Step 1: run the Checklist first."
    )

    library_scanner.scan_templates(db_session, tracked_acts=[])

    checklist = db_session.query(Document).filter_by(name="Checklist").first()
    workflow = db_session.query(Document).filter_by(name="Workflow").first()
    assert checklist is not None and workflow is not None

    edge = (
        db_session.query(DependencyEdge)
        .filter_by(from_document_id=workflow.id, to_document_id=checklist.id, to_clause_id=None)
        .first()
    )
    assert edge is not None


def test_scan_templates_is_idempotent(db_session, fake_library):
    (fake_library["templates"] / "checklist.txt").write_text(
        "These exemptions are set out in section 4 of the PDPA."
    )

    library_scanner.scan_templates(db_session, tracked_acts=PDPA_TRACKED)
    library_scanner.scan_templates(db_session, tracked_acts=PDPA_TRACKED)

    assert db_session.query(Document).count() == 1
    # no duplicate edges either, even though citation detection re-ran
    edges = db_session.query(DependencyEdge).all()
    assert len(edges) == len(set((e.from_document_id, e.to_document_id, e.to_clause_id) for e in edges))


def test_scan_inbox_classifies_and_moves_template_shaped_file(db_session, fake_library):
    (fake_library["inbox"] / "memo.txt").write_text(
        "Client Intake Memo (Firm Template)\n\nUse this memo when a new engagement is opened."
    )

    result = library_scanner.scan_inbox(db_session)

    assert len(result.classified) == 1
    classified = result.classified[0]
    assert classified.document.genre == DocumentGenre.TEMPLATE
    assert not (fake_library["inbox"] / "memo.txt").exists()
    assert (fake_library["templates"] / "memo.txt").exists()


def test_scan_inbox_classifies_and_moves_statute_shaped_file(db_session, fake_library):
    from tests.test_classifier import STATUTE_TEXT

    (fake_library["inbox"] / "some_act.txt").write_text(STATUTE_TEXT)

    result = library_scanner.scan_inbox(db_session)

    classified = result.classified[0]
    assert classified.document.genre == DocumentGenre.STATUTE
    assert (fake_library["statutes"] / "some_act.txt").exists()


def test_scan_inbox_is_idempotent_on_repeated_calls(db_session, fake_library):
    (fake_library["inbox"] / "memo.txt").write_text("A short firm memo template.")

    library_scanner.scan_inbox(db_session)
    library_scanner.scan_inbox(db_session)  # inbox is now empty, nothing to reclassify

    assert db_session.query(Document).count() == 1
