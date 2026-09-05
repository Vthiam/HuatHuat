"""Shared test data other branches can build against before their own
upstream code exists.

Usage:

    from app.testing.fixtures import build_sample_library

    def test_something(db_session):
        lib = build_sample_library(db_session)
        lib["clause"]        # the one statute clause, "section 4"
        lib["template_a"]    # cites the clause directly
        lib["template_b"]    # depends on template_a, not the clause directly

feature/sso-diff-history can diff against lib["clause"].text without a
real fetch. feature/graph-impact can call find_affected_documents(db,
lib["clause"].id) and assert it gets back exactly [template_a (direct),
template_b (transitive)]. feature/cli-reports-review can format a fake
report from the same objects.
"""
from sqlalchemy.orm import Session

from ..models import (
    Clause,
    DependencyEdge,
    Document,
    DocumentGenre,
    DocumentSource,
)


def build_sample_library(db: Session) -> dict:
    statute = Document(
        name="Sample Act 2024",
        genre=DocumentGenre.STATUTE,
        source=DocumentSource.SSO,
        file_path="statutes/SampleAct2024.txt",
        sso_url="https://sso.agc.gov.sg/Act/SampleAct2024",
    )
    db.add(statute)
    db.flush()

    clause = Clause(
        document_id=statute.id,
        clause_ref="4",
        heading="Application of Act",
        text="Parts 3, 4, 5 and 6 do not impose any obligation on an individual acting in a personal capacity.",
        version=1,
    )
    db.add(clause)
    db.flush()

    template_a = Document(
        name="Sample Applicability Checklist",
        genre=DocumentGenre.TEMPLATE,
        source=DocumentSource.FIRM,
        file_path="templates/sample_checklist.txt",
    )
    db.add(template_a)
    db.flush()

    template_b = Document(
        name="Sample Onboarding Workflow",
        genre=DocumentGenre.TEMPLATE,
        source=DocumentSource.FIRM,
        file_path="templates/sample_workflow.txt",
    )
    db.add(template_b)
    db.flush()

    edge_direct = DependencyEdge(
        from_document_id=template_a.id,
        to_document_id=statute.id,
        to_clause_id=clause.id,
        excerpt="These exemptions are set out in section 4 of the Act.",
    )
    db.add(edge_direct)

    edge_transitive = DependencyEdge(
        from_document_id=template_b.id,
        to_document_id=template_a.id,
        to_clause_id=None,
        excerpt="run the Sample Applicability Checklist first",
    )
    db.add(edge_transitive)

    db.flush()

    return {
        "statute": statute,
        "clause": clause,
        "template_a": template_a,
        "template_b": template_b,
        "edge_direct": edge_direct,
        "edge_transitive": edge_transitive,
    }
