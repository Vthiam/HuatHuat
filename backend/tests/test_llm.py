from unittest import mock

from app.models import ReasoningSource
from app.services import llm
from app.services.llm import recommend_impact, summarize_change


def test_summarize_change_heuristic_mentions_removed_and_added():
    text, source = summarize_change(
        clause_ref="4",
        heading="Application of Act",
        old_text="Parts III to VI shall not impose any obligation.",
        new_text="Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation.",
    )
    assert source == ReasoningSource.HEURISTIC
    assert "4" in text
    assert "Removed" in text or "removed" in text.lower()
    assert "Added" in text or "added" in text.lower()


def test_recommend_impact_direct_heuristic_grounds_in_old_and_new_text():
    rec = recommend_impact(
        document_name="Sample Applicability Checklist",
        document_text="Full checklist text mentioning section 4 exemptions.",
        document_excerpt="These exemptions are set out in section 4 of the Act.",
        clause_ref="4",
        old_clause_text="Parts III to VI shall not impose any obligation.",
        new_clause_text="Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation.",
        dependency_path=["Sample Applicability Checklist"],
    )
    assert rec.source == ReasoningSource.HEURISTIC
    assert "Sample Applicability Checklist" in rec.explanation
    assert "III to VI" in rec.explanation
    assert "3, 4, 5, 6, 6A and 6B" in rec.explanation
    # heuristic can't verify a quote against real document text, so it
    # never proposes an auto-editable suggestion
    assert rec.conflicting_sentence is None
    assert rec.suggested_replacement is None


def test_recommend_impact_transitive_heuristic_mentions_dependency_path():
    rec = recommend_impact(
        document_name="Sample Onboarding Workflow",
        document_text="Step 1: run the checklist first.",
        document_excerpt="run the checklist first",
        clause_ref="4",
        old_clause_text="Parts III to VI shall not impose any obligation.",
        new_clause_text="Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation.",
        dependency_path=["Sample Applicability Checklist", "Sample Onboarding Workflow"],
    )
    assert rec.source == ReasoningSource.HEURISTIC
    assert "Sample Applicability Checklist -> Sample Onboarding Workflow" in rec.explanation
    assert "indirectly" in rec.explanation


def test_recommend_impact_parses_valid_json_from_model(monkeypatch):
    fake_json = (
        '{"explanation": "This is a test explanation.", '
        '"conflicting_sentence": "The old sentence.", '
        '"suggested_replacement": "The new sentence."}'
    )
    monkeypatch.setattr(llm, "_call_openai", lambda **kwargs: fake_json)

    rec = recommend_impact(
        document_name="Doc",
        document_text="x",
        document_excerpt="x",
        clause_ref="4",
        old_clause_text="old",
        new_clause_text="new",
        dependency_path=["Doc"],
    )
    assert rec.source == ReasoningSource.OPENAI
    assert rec.explanation == "This is a test explanation."
    assert rec.conflicting_sentence == "The old sentence."
    assert rec.suggested_replacement == "The new sentence."


def test_recommend_impact_falls_back_to_heuristic_on_malformed_json(monkeypatch):
    monkeypatch.setattr(llm, "_call_openai", lambda **kwargs: "not valid json {{{")

    rec = recommend_impact(
        document_name="Doc",
        document_text="x",
        document_excerpt="x",
        clause_ref="4",
        old_clause_text="Parts III to VI.",
        new_clause_text="Parts 3-6.",
        dependency_path=["Doc"],
    )
    assert rec.source == ReasoningSource.HEURISTIC
    assert rec.conflicting_sentence is None


def test_recommend_impact_falls_back_when_explanation_missing(monkeypatch):
    monkeypatch.setattr(llm, "_call_openai", lambda **kwargs: '{"conflicting_sentence": "x"}')

    rec = recommend_impact(
        document_name="Doc",
        document_text="x",
        document_excerpt="x",
        clause_ref="4",
        old_clause_text="Parts III to VI.",
        new_clause_text="Parts 3-6.",
        dependency_path=["Doc"],
    )
    assert rec.source == ReasoningSource.HEURISTIC
