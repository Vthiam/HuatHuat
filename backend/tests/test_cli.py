import hashlib
from unittest import mock

import pytest

from app import cli, library_scanner, report, statute_sync
from app.services import document_editor, pdf_highlighter
from app.services import docx_commenter
from app.models import ChangeEvent, ChangeSource, Flag, FlagStatus
from app.testing.fixtures import build_sample_library


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def fake_library(tmp_path, monkeypatch):
    law_library = tmp_path / "law_library"
    inbox, statutes, templates, reports = (
        law_library / "inbox",
        law_library / "statutes",
        law_library / "templates",
        law_library / "reports",
    )
    for d in (inbox, statutes, templates, reports):
        d.mkdir(parents=True)

    monkeypatch.setattr(library_scanner, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(library_scanner, "INBOX_DIR", inbox)
    monkeypatch.setattr(library_scanner, "STATUTES_DIR", statutes)
    monkeypatch.setattr(library_scanner, "TEMPLATES_DIR", templates)
    monkeypatch.setattr(statute_sync, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(statute_sync, "STATUTES_DIR", statutes)
    monkeypatch.setattr(pdf_highlighter, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(pdf_highlighter, "REPORTS_DIR", reports)
    monkeypatch.setattr(document_editor, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(docx_commenter, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(docx_commenter, "REPORTS_DIR", reports)
    monkeypatch.setattr(report, "REPORTS_DIR", reports)

    return {"root": law_library, "inbox": inbox, "statutes": statutes, "templates": templates, "reports": reports}


def test_check_sso_live_refuses_outside_window_without_override(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(cli, "should_run_now", lambda: False)

    def boom(*a, **kw):
        raise AssertionError("sync_live must not be called when refused")

    monkeypatch.setattr(cli.statute_sync, "sync_live", boom)

    result = cli.cmd_check_sso(db_session, live=True, simulate=False, clause_ref=None, override_schedule=False)

    assert result.ok is False


def test_check_sso_live_proceeds_with_override_schedule(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(cli, "should_run_now", lambda: False)
    called = {"n": 0}

    def fake_sync_live(db, act_config):
        called["n"] += 1
        return []

    monkeypatch.setattr(cli.statute_sync, "sync_live", fake_sync_live)

    result = cli.cmd_check_sso(db_session, live=True, simulate=False, clause_ref=None, override_schedule=True)

    assert result.ok is True
    assert called["n"] == 1


def test_check_sso_simulate_requires_clause_ref(db_session, fake_library):
    result = cli.cmd_check_sso(db_session, live=False, simulate=True, clause_ref=None, override_schedule=False)
    assert result.ok is False


def test_check_sso_rejects_both_live_and_simulate(db_session, fake_library):
    result = cli.cmd_check_sso(db_session, live=True, simulate=True, clause_ref="4", override_schedule=False)
    assert result.ok is False


def test_check_sso_creates_flags_and_highlights_pdf(db_session, fake_library, monkeypatch):
    lib = build_sample_library(db_session)
    db_session.commit()

    # Give template_a a real PDF file on disk containing the excerpt text,
    # matching what the fixture already declared as its dependency excerpt.
    import fitz

    pdf_path = fake_library["templates"] / "sample_checklist.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "These exemptions are set out in section 4 of the Act.")
    pdf.save(str(pdf_path))
    pdf.close()
    lib["template_a"].file_path = "templates/sample_checklist.pdf"
    db_session.commit()

    def fake_sync_live(db, act_config):
        event = ChangeEvent(
            clause_id=lib["clause"].id,
            old_text="Parts III to VI do not apply.",
            new_text="Parts 3, 4, 5 and 6 do not apply.",
            source=ChangeSource.LIVE,
        )
        db.add(event)
        db.commit()
        return [event]

    monkeypatch.setattr(cli.statute_sync, "sync_live", fake_sync_live)
    notify_calls = []
    monkeypatch.setattr(cli.notifier, "notify", lambda title, message: notify_calls.append((title, message)))

    result = cli.cmd_check_sso(db_session, live=True, simulate=False, clause_ref=None, override_schedule=True)

    assert result.ok is True
    flags = db_session.query(Flag).all()
    assert len(flags) == 2  # template_a direct + template_b transitive

    flagged_pdf = fake_library["reports"] / "flagged" / "sample_checklist_flagged.pdf"
    assert flagged_pdf.exists()

    assert len(notify_calls) == 1
    assert "2 document(s)" in notify_calls[0][1]


def test_check_sso_no_events_does_not_notify(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(cli.statute_sync, "sync_live", lambda db, act_config: [])
    notify_calls = []
    monkeypatch.setattr(cli.notifier, "notify", lambda title, message: notify_calls.append((title, message)))

    result = cli.cmd_check_sso(db_session, live=True, simulate=False, clause_ref=None, override_schedule=True)

    assert result.ok is True
    assert notify_calls == []


def test_review_accept_updates_status_without_touching_document(db_session, fake_library):
    lib = build_sample_library(db_session)
    db_session.commit()
    event = ChangeEvent(
        clause_id=lib["clause"].id, old_text="old", new_text="new", source=ChangeSource.SIMULATED
    )
    db_session.add(event)
    db_session.commit()

    from app import impact_service

    flags = impact_service.process_change_event(db_session, event)
    assert len(flags) == 2

    cli.cmd_review(db_session, status="pending", auto_answers=["a", "r"])

    db_session.expire_all()
    resolved = db_session.query(Flag).order_by(Flag.id).all()
    assert {f.status for f in resolved} == {FlagStatus.ACCEPTED, FlagStatus.REJECTED}
    assert all(f.resolved_at is not None for f in resolved)


def test_review_with_no_pending_flags_does_not_crash(db_session, fake_library, capsys):
    cli.cmd_review(db_session, status="pending")
    captured = capsys.readouterr()
    assert "No flags" in captured.out


def test_scan_auto_loop_flags_new_document_against_existing_change(db_session, fake_library, monkeypatch):
    """The auto-loop: a statute clause already changed (ChangeEvent exists)
    BEFORE this document ever existed. Dropping the document in and
    scanning should immediately flag it -- not wait for the next
    check-sso, which wouldn't detect anything new for a clause that
    hasn't changed again."""
    lib = build_sample_library(db_session)
    db_session.commit()
    event = ChangeEvent(
        clause_id=lib["clause"].id, old_text="old", new_text="new", source=ChangeSource.SIMULATED
    )
    db_session.add(event)
    db_session.commit()

    # scan_templates' citation detection uses config.TRACKED_ACTS by
    # default (real PDPA) -- override it to recognize the fixture's
    # synthetic "Sample Act 2024" so the new document's citation is found.
    monkeypatch.setattr(
        library_scanner,
        "TRACKED_ACTS",
        [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"]}],
    )

    (fake_library["templates"] / "new_checklist.txt").write_text(
        "These exemptions are set out in section 4 of the Sample Act 2024."
    )
    notify_calls = []
    monkeypatch.setattr(cli.notifier, "notify", lambda title, message: notify_calls.append((title, message)))

    result = cli.cmd_scan(db_session)

    assert len(result.template_result.new_documents) == 1
    new_doc_names = {f.document.name for f in result.new_flags}
    assert "New Checklist" in new_doc_names
    # the fixture's own pre-existing documents (never checked before this
    # scan) get swept up too -- that's the auto-loop working correctly,
    # not a bug: nobody had run impact analysis against this ChangeEvent
    # until now.
    assert len(result.new_flags) == 3

    assert len(notify_calls) == 1
    assert "flagged for review" in notify_calls[0][1]


def test_scan_auto_loop_notifies_informationally_when_no_flag_applies(db_session, fake_library, monkeypatch):
    """A brand new document with no pre-existing change to match against
    still gets a lighter, informational notification -- "this is now
    being watched" -- rather than silence."""
    (fake_library["templates"] / "standalone.txt").write_text("A document that cites nothing tracked.")
    notify_calls = []
    monkeypatch.setattr(cli.notifier, "notify", lambda title, message: notify_calls.append((title, message)))

    result = cli.cmd_scan(db_session)

    assert result.new_flags == []
    assert len(notify_calls) == 1
    assert "being watched" in notify_calls[0][1]
