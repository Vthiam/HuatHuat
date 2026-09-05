import hashlib
from unittest import mock

import pytest

from app import cli, library_scanner, report, statute_sync
from app.services import pdf_highlighter
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
