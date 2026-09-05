from app.models import ReasoningSource
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
    text, source = recommend_impact(
        document_name="Sample Applicability Checklist",
        document_text="Full checklist text mentioning section 4 exemptions.",
        document_excerpt="These exemptions are set out in section 4 of the Act.",
        clause_ref="4",
        old_clause_text="Parts III to VI shall not impose any obligation.",
        new_clause_text="Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation.",
        dependency_path=["Sample Applicability Checklist"],
    )
    assert source == ReasoningSource.HEURISTIC
    assert "Sample Applicability Checklist" in text
    assert "Parts III to VI" in text
    assert "Parts 3, 4, 5, 6, 6A and 6B" in text


def test_recommend_impact_transitive_heuristic_mentions_dependency_path():
    text, source = recommend_impact(
        document_name="Sample Onboarding Workflow",
        document_text="Step 1: run the checklist first.",
        document_excerpt="run the checklist first",
        clause_ref="4",
        old_clause_text="Parts III to VI shall not impose any obligation.",
        new_clause_text="Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation.",
        dependency_path=["Sample Applicability Checklist", "Sample Onboarding Workflow"],
    )
    assert source == ReasoningSource.HEURISTIC
    assert "Sample Applicability Checklist -> Sample Onboarding Workflow" in text
    assert "indirectly" in text
