import pytest

from app import impact_service
from app.models import ChangeEvent, ChangeSource, Clause, Flag, FlagStatus, FlagType, ReasoningSource
from app.testing.fixtures import build_sample_library


def _make_change_event(db, clause, old_text, new_text):
    event = ChangeEvent(
        clause_id=clause.id,
        old_text=old_text,
        new_text=new_text,
        source=ChangeSource.LIVE,
    )
    db.add(event)
    db.commit()
    return event


@pytest.fixture()
def fake_library(tmp_path, monkeypatch):
    from app.services import document_editor

    law_library = tmp_path / "law_library"
    templates = law_library / "templates"
    templates.mkdir(parents=True)
    monkeypatch.setattr(document_editor, "LAW_LIBRARY_DIR", law_library)
    return {"root": law_library, "templates": templates}


def test_creates_flags_for_direct_and_transitive(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()
    event = _make_change_event(
        db_session,
        lib["clause"],
        old_text="Parts III to VI do not impose any obligation.",
        new_text="Parts 3, 4, 5 and 6 do not impose any obligation.",
    )

    flags = impact_service.process_change_event(db_session, event)

    assert len(flags) == 2
    by_doc = {f.document_id: f for f in flags}

    direct = by_doc[lib["template_a"].id]
    assert direct.flag_type == FlagType.DIRECT_DEPENDENCY
    assert direct.depth == 1
    assert direct.via_document_id is None
    assert direct.recommendation_text
    assert direct.recommendation_source == ReasoningSource.HEURISTIC

    transitive = by_doc[lib["template_b"].id]
    assert transitive.flag_type == FlagType.TRANSITIVE_DEPENDENCY
    assert transitive.depth == 2
    assert transitive.via_document_id == lib["template_a"].id


def test_fills_in_legal_effect_summary_left_null_by_sso_branch(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()
    event = _make_change_event(db_session, lib["clause"], "old text here", "new text here")
    assert event.legal_effect_summary is None

    impact_service.process_change_event(db_session, event)

    db_session.refresh(event)
    assert event.legal_effect_summary is not None
    assert event.summary_source == ReasoningSource.HEURISTIC


def test_creates_no_flags_when_nothing_depends_on_the_clause(db_session):
    lib = build_sample_library(db_session)
    unrelated_clause = Clause(
        document_id=lib["statute"].id,
        clause_ref="9",
        heading="Unrelated",
        text="Nothing cites this.",
        version=1,
    )
    db_session.add(unrelated_clause)
    db_session.commit()

    event = _make_change_event(db_session, unrelated_clause, "old", "new")
    flags = impact_service.process_change_event(db_session, event)

    assert flags == []


def test_is_idempotent_on_repeated_calls(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()
    event = _make_change_event(db_session, lib["clause"], "old text", "new text")

    first_flags = impact_service.process_change_event(db_session, event)
    second_flags = impact_service.process_change_event(db_session, event)

    assert len(first_flags) == 2
    assert second_flags == []  # nothing NEW created
    assert db_session.query(Flag).count() == 2


def test_process_all_handles_multiple_change_events(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()

    unrelated_clause = Clause(
        document_id=lib["statute"].id, clause_ref="9", heading="Unrelated", text="x", version=1
    )
    db_session.add(unrelated_clause)
    db_session.commit()

    event_a = _make_change_event(db_session, lib["clause"], "old", "new")
    event_b = _make_change_event(db_session, unrelated_clause, "old", "new")

    flags = impact_service.process_all(db_session, [event_a, event_b])

    assert len(flags) == 2  # only from event_a; event_b has no dependents


def test_resolve_flag_accept_applies_edit_for_txt(db_session, fake_library):
    lib = build_sample_library(db_session)
    (fake_library["templates"] / "sample_checklist.txt").write_text(
        "Exempt from Parts III to VI where applicable."
    )
    db_session.commit()

    flag = Flag(
        change_event_id=_make_change_event(db_session, lib["clause"], "old", "new").id,
        document_id=lib["template_a"].id,
        flag_type=FlagType.DIRECT_DEPENDENCY,
        depth=1,
        recommendation_text="explanation",
        recommendation_source=ReasoningSource.OPENAI,
        original_sentence="Parts III to VI",
        suggested_replacement="Parts 3, 4, 5, 6, 6A and 6B",
    )
    db_session.add(flag)
    db_session.commit()

    resolved = impact_service.resolve_flag_accept(db_session, flag)

    assert resolved.status == FlagStatus.ACCEPTED
    assert resolved.resolved_at is not None
    assert resolved.document_edited is True
    assert (fake_library["templates"] / "sample_checklist.txt").read_text() == (
        "Exempt from Parts 3, 4, 5, 6, 6A and 6B where applicable."
    )


def test_resolve_flag_accept_without_verified_sentence_is_review_only(db_session, fake_library):
    lib = build_sample_library(db_session)
    (fake_library["templates"] / "sample_checklist.txt").write_text("Original text, untouched.")
    db_session.commit()

    flag = Flag(
        change_event_id=_make_change_event(db_session, lib["clause"], "old", "new").id,
        document_id=lib["template_a"].id,
        flag_type=FlagType.DIRECT_DEPENDENCY,
        depth=1,
        recommendation_text="heuristic explanation",
        recommendation_source=ReasoningSource.HEURISTIC,
        # no original_sentence/suggested_replacement -- heuristic fallback
    )
    db_session.add(flag)
    db_session.commit()

    resolved = impact_service.resolve_flag_accept(db_session, flag)

    assert resolved.status == FlagStatus.ACCEPTED
    assert resolved.document_edited is False
    assert (fake_library["templates"] / "sample_checklist.txt").read_text() == "Original text, untouched."


def test_resolve_flag_reject_with_self_edit_applies_human_text(db_session, fake_library):
    lib = build_sample_library(db_session)
    (fake_library["templates"] / "sample_checklist.txt").write_text(
        "Exempt from Parts III to VI where applicable."
    )
    db_session.commit()

    flag = Flag(
        change_event_id=_make_change_event(db_session, lib["clause"], "old", "new").id,
        document_id=lib["template_a"].id,
        flag_type=FlagType.DIRECT_DEPENDENCY,
        depth=1,
        recommendation_text="explanation",
        recommendation_source=ReasoningSource.OPENAI,
        original_sentence="Parts III to VI",
        suggested_replacement="Parts 3, 4, 5, 6, 6A and 6B",  # the AI's proposal -- should NOT be what gets applied
    )
    db_session.add(flag)
    db_session.commit()

    resolved = impact_service.resolve_flag_reject(
        db_session, flag, human_edit_text="Parts 3 through 6B inclusive"
    )

    assert resolved.status == FlagStatus.REJECTED
    assert resolved.human_edit_text == "Parts 3 through 6B inclusive"
    assert resolved.document_edited is True
    assert (fake_library["templates"] / "sample_checklist.txt").read_text() == (
        "Exempt from Parts 3 through 6B inclusive where applicable."
    )


def test_resolve_flag_reject_without_self_edit_leaves_document_untouched(db_session, fake_library):
    lib = build_sample_library(db_session)
    (fake_library["templates"] / "sample_checklist.txt").write_text("Untouched original.")
    db_session.commit()

    flag = Flag(
        change_event_id=_make_change_event(db_session, lib["clause"], "old", "new").id,
        document_id=lib["template_a"].id,
        flag_type=FlagType.DIRECT_DEPENDENCY,
        depth=1,
        recommendation_text="explanation",
        recommendation_source=ReasoningSource.OPENAI,
        original_sentence="something",
        suggested_replacement="something else",
    )
    db_session.add(flag)
    db_session.commit()

    resolved = impact_service.resolve_flag_reject(db_session, flag)

    assert resolved.status == FlagStatus.REJECTED
    assert resolved.document_edited is False
    assert resolved.human_edit_text is None
    assert (fake_library["templates"] / "sample_checklist.txt").read_text() == "Untouched original."
