from app.models import DependencyEdge, FlagType
from app.services.graph_service import find_affected_documents
from app.testing.fixtures import build_sample_library


def test_finds_direct_and_transitive_dependents(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()

    affected = find_affected_documents(db_session, lib["clause"].id)

    by_id = {a.document.id: a for a in affected}
    assert set(by_id.keys()) == {lib["template_a"].id, lib["template_b"].id}

    direct = by_id[lib["template_a"].id]
    assert direct.flag_type == FlagType.DIRECT_DEPENDENCY
    assert direct.depth == 1
    assert direct.via_document is None

    transitive = by_id[lib["template_b"].id]
    assert transitive.flag_type == FlagType.TRANSITIVE_DEPENDENCY
    assert transitive.depth == 2
    assert transitive.via_document.id == lib["template_a"].id
    assert transitive.dependency_path == [lib["template_a"].name, lib["template_b"].name]


def test_returns_empty_when_nothing_depends_on_the_clause(db_session):
    lib = build_sample_library(db_session)

    from app.models import Clause

    unrelated_clause = Clause(
        document_id=lib["statute"].id,
        clause_ref="9",
        heading="Unrelated Section",
        text="Nothing cites this.",
        version=1,
    )
    db_session.add(unrelated_clause)
    db_session.commit()

    affected = find_affected_documents(db_session, unrelated_clause.id)
    assert affected == []


def test_does_not_infinite_loop_on_a_cyclic_dependency(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()

    # Introduce a cycle: template_a also depends on template_b (which
    # already depends on template_a via the fixture).
    cycle_edge = DependencyEdge(
        from_document_id=lib["template_a"].id,
        to_document_id=lib["template_b"].id,
        to_clause_id=None,
        excerpt="circular reference for test purposes",
    )
    db_session.add(cycle_edge)
    db_session.commit()

    affected = find_affected_documents(db_session, lib["clause"].id)

    document_ids = [a.document.id for a in affected]
    assert len(document_ids) == len(set(document_ids))  # each document appears at most once
    assert set(document_ids) == {lib["template_a"].id, lib["template_b"].id}
