import pytest

from app import statute_sync
from app.models import Clause, ClauseVersion, Document, DocumentGenre
from app.services.sso_client import ScrapedClause

ACT_CONFIG = {
    "act_id": "TESTACT2024",
    "name": "Test Act 2024",
    "clause_refs": ["4"],
    "local_filename": "TestAct2024.txt",
}


@pytest.fixture()
def fake_library(tmp_path, monkeypatch):
    law_library = tmp_path / "law_library"
    statutes = law_library / "statutes"
    statutes.mkdir(parents=True)
    monkeypatch.setattr(statute_sync, "LAW_LIBRARY_DIR", law_library)
    monkeypatch.setattr(statute_sync, "STATUTES_DIR", statutes)
    return {"root": law_library, "statutes": statutes}


def test_sync_live_first_time_creates_baseline_with_no_change_event(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(
        statute_sync,
        "fetch_tracked_clauses",
        lambda act_id, refs: [ScrapedClause("4", "Application", "Parts III to VI shall not apply.")],
    )

    events = statute_sync.sync_live(db_session, ACT_CONFIG)

    assert events == []
    doc = db_session.query(Document).filter_by(genre=DocumentGenre.STATUTE).first()
    assert doc is not None
    clause = db_session.query(Clause).filter_by(document_id=doc.id, clause_ref="4").first()
    assert clause.text == "Parts III to VI shall not apply."
    assert (fake_library["statutes"] / "TestAct2024.txt").exists()


def test_sync_live_second_call_with_changed_text_creates_change_event(db_session, fake_library, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(act_id, refs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [ScrapedClause("4", "Application", "Parts III to VI shall not apply.")]
        return [ScrapedClause("4", "Application", "Parts 3, 4, 5, 6, 6A and 6B do not apply.")]

    monkeypatch.setattr(statute_sync, "fetch_tracked_clauses", fake_fetch)

    first_events = statute_sync.sync_live(db_session, ACT_CONFIG)
    assert first_events == []

    second_events = statute_sync.sync_live(db_session, ACT_CONFIG)
    assert len(second_events) == 1
    change = second_events[0]
    assert "III to VI" in change.old_text
    assert "3, 4, 5, 6, 6A and 6B" in change.new_text

    clause = db_session.query(Clause).filter_by(clause_ref="4").first()
    assert clause.version == 2
    assert clause.text == "Parts 3, 4, 5, 6, 6A and 6B do not apply."

    history = db_session.query(ClauseVersion).filter_by(clause_id=clause.id).all()
    assert any(v.text == "Parts III to VI shall not apply." for v in history)


def test_sync_live_no_change_creates_no_event(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(
        statute_sync,
        "fetch_tracked_clauses",
        lambda act_id, refs: [ScrapedClause("4", "Application", "Same text every time.")],
    )
    statute_sync.sync_live(db_session, ACT_CONFIG)
    events = statute_sync.sync_live(db_session, ACT_CONFIG)
    assert events == []


def test_seed_from_historical_uses_historical_fetch(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(
        statute_sync,
        "fetch_tracked_historical_clauses",
        lambda act_id, refs, valid_date, doc_date: [ScrapedClause("4", "Application", "Historical text.")],
    )
    events = statute_sync.seed_from_historical(db_session, ACT_CONFIG, "20130102", "20121203")
    assert events == []
    clause = db_session.query(Clause).filter_by(clause_ref="4").first()
    assert clause.text == "Historical text."


def test_sync_simulated_applies_synthetic_edit_without_network(db_session, fake_library, monkeypatch):
    monkeypatch.setattr(
        statute_sync,
        "fetch_tracked_clauses",
        lambda act_id, refs: [ScrapedClause("4", "Application", "Parts 3, 4, 5, 6, 6A and 6B do not apply.")],
    )
    statute_sync.sync_live(db_session, ACT_CONFIG)  # baseline

    def boom(*a, **kw):
        raise AssertionError("sync_simulated must not touch the network")

    monkeypatch.setattr(statute_sync, "fetch_tracked_clauses", boom)
    monkeypatch.setattr(statute_sync, "fetch_tracked_historical_clauses", boom)

    events = statute_sync.sync_simulated(db_session, ACT_CONFIG, clause_ref="4")
    assert len(events) == 1
    assert events[0].source.value == "simulated"
    assert "6C" in events[0].new_text


def test_sync_simulated_on_untracked_statute_returns_empty(db_session, fake_library):
    events = statute_sync.sync_simulated(db_session, ACT_CONFIG, clause_ref="4")
    assert events == []
