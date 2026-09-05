from app.models import DocumentGenre, DocumentSource, FlagStatus
from app.testing.fixtures import build_sample_library


def test_fixture_builds_expected_shape(db_session):
    lib = build_sample_library(db_session)

    assert lib["statute"].genre == DocumentGenre.STATUTE
    assert lib["statute"].source == DocumentSource.SSO
    assert lib["template_a"].genre == DocumentGenre.TEMPLATE
    assert lib["template_b"].genre == DocumentGenre.TEMPLATE


def test_clause_belongs_to_statute(db_session):
    lib = build_sample_library(db_session)

    assert lib["clause"].document_id == lib["statute"].id
    assert lib["clause"] in lib["statute"].clauses
    assert lib["clause"].document is lib["statute"]


def test_direct_dependency_edge_points_at_clause(db_session):
    lib = build_sample_library(db_session)

    edge = lib["edge_direct"]
    assert edge.from_document_id == lib["template_a"].id
    assert edge.to_document_id == lib["statute"].id
    assert edge.to_clause_id == lib["clause"].id
    assert edge.to_clause is lib["clause"]
    assert edge.from_document is lib["template_a"]
    assert edge.to_document is lib["statute"]


def test_transitive_dependency_edge_has_no_clause(db_session):
    lib = build_sample_library(db_session)

    edge = lib["edge_transitive"]
    assert edge.from_document_id == lib["template_b"].id
    assert edge.to_document_id == lib["template_a"].id
    assert edge.to_clause_id is None
    assert edge.to_clause is None


def test_enum_values_round_trip(db_session):
    lib = build_sample_library(db_session)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(type(lib["statute"]), lib["statute"].id)
    assert reloaded.genre == DocumentGenre.STATUTE
    assert isinstance(reloaded.genre, DocumentGenre)


def test_flag_status_defaults_to_pending(db_session):
    from app.models import ChangeEvent, ChangeSource, Flag, FlagType

    lib = build_sample_library(db_session)
    change = ChangeEvent(
        clause_id=lib["clause"].id,
        old_text="old",
        new_text="new",
        source=ChangeSource.SIMULATED,
    )
    db_session.add(change)
    db_session.flush()

    flag = Flag(
        change_event_id=change.id,
        document_id=lib["template_a"].id,
        flag_type=FlagType.DIRECT_DEPENDENCY,
        depth=1,
    )
    db_session.add(flag)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(Flag, flag.id)
    assert reloaded.status == FlagStatus.PENDING
