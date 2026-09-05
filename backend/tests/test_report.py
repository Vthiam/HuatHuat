import pytest

from app import impact_service, library_scanner, report
from app.models import ChangeEvent, ChangeSource
from app.testing.fixtures import build_sample_library


@pytest.fixture()
def fake_reports_dir(tmp_path, monkeypatch):
    reports_dir = tmp_path / "law_library" / "reports"
    monkeypatch.setattr(report, "REPORTS_DIR", reports_dir)
    return reports_dir


def test_write_scan_report_covers_new_docs_and_edges(db_session, fake_reports_dir, tmp_path, monkeypatch):
    templates_dir = tmp_path / "law_library" / "templates"
    inbox_dir = tmp_path / "law_library" / "inbox"
    templates_dir.mkdir(parents=True)
    inbox_dir.mkdir(parents=True)
    monkeypatch.setattr(library_scanner, "TEMPLATES_DIR", templates_dir)
    monkeypatch.setattr(library_scanner, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(library_scanner, "LAW_LIBRARY_DIR", tmp_path / "law_library")
    monkeypatch.setattr(library_scanner, "STATUTES_DIR", tmp_path / "law_library" / "statutes")
    (tmp_path / "law_library" / "statutes").mkdir(parents=True)

    (templates_dir / "checklist.txt").write_text("A standalone checklist with no citations.")
    (inbox_dir / "memo.txt").write_text("A short firm memo template.")

    inbox_result = library_scanner.scan_inbox(db_session)
    template_result = library_scanner.scan_templates(db_session, tracked_acts=[])

    path = report.write_scan_report(inbox_result, template_result)

    assert path.exists()
    content = path.read_text()
    assert "Library Scan Report" in content
    assert "Checklist" in content
    assert "memo" in content.lower()


def test_write_check_report_covers_changes_and_flags(db_session, fake_reports_dir):
    lib = build_sample_library(db_session)
    db_session.commit()

    event = ChangeEvent(
        clause_id=lib["clause"].id,
        old_text="Parts III to VI do not apply.",
        new_text="Parts 3, 4, 5 and 6 do not apply.",
        source=ChangeSource.LIVE,
    )
    db_session.add(event)
    db_session.commit()

    flags = impact_service.process_change_event(db_session, event)

    path = report.write_check_report([event], flags, highlighted_pdfs={})

    assert path.exists()
    content = path.read_text()
    assert "Statute Check Report" in content
    assert "Parts III to VI" in content
    assert lib["template_a"].name in content


def test_write_check_report_with_no_changes(fake_reports_dir):
    path = report.write_check_report([], [], highlighted_pdfs={})
    content = path.read_text()
    assert "no changes detected" in content
    assert "no documents affected" in content
