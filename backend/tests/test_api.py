import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import cli as cli_module
from app import library_scanner, statute_sync
from app import report as report_module
from app.db import Base, get_db
from app.main import app
from app.services import pdf_highlighter
from app.testing.fixtures import build_sample_library


@pytest.fixture()
def api(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    law_library = tmp_path / "law_library"
    inbox, statutes, templates, reports = (
        law_library / "inbox",
        law_library / "statutes",
        law_library / "templates",
        law_library / "reports",
    )
    for d in (inbox, statutes, templates, reports):
        d.mkdir(parents=True)

    from app.routers import actions as actions_router
    from app.routers import library as library_router

    for module, attr, value in [
        (library_scanner, "LAW_LIBRARY_DIR", law_library),
        (library_scanner, "INBOX_DIR", inbox),
        (library_scanner, "STATUTES_DIR", statutes),
        (library_scanner, "TEMPLATES_DIR", templates),
        (statute_sync, "LAW_LIBRARY_DIR", law_library),
        (statute_sync, "STATUTES_DIR", statutes),
        (actions_router, "INBOX_DIR", inbox),
        (library_router, "LAW_LIBRARY_DIR", law_library),
        (pdf_highlighter, "LAW_LIBRARY_DIR", law_library),
        (pdf_highlighter, "REPORTS_DIR", reports),
        (report_module, "REPORTS_DIR", reports),
    ]:
        monkeypatch.setattr(module, attr, value)

    from app.routers import flags as flags_router

    monkeypatch.setattr(flags_router, "REPORTS_DIR", reports)
    monkeypatch.setattr(cli_module.notifier, "notify", lambda *a, **kw: None)

    client = TestClient(app)
    yield client, TestSessionLocal, {"root": law_library, "templates": templates, "inbox": inbox}

    app.dependency_overrides.clear()


def test_health(api):
    client, _, _ = api
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_documents_empty_then_seeded(api):
    client, SessionLocal, _ = api

    resp = client.get("/api/documents")
    assert resp.status_code == 200
    assert resp.json() == []

    db = SessionLocal()
    build_sample_library(db)
    db.commit()
    db.close()

    resp = client.get("/api/documents")
    data = resp.json()
    assert len(data) == 3
    names = {d["name"] for d in data}
    assert names == {"Sample Act 2024", "Sample Applicability Checklist", "Sample Onboarding Workflow"}


def test_get_document_detail_includes_clauses_and_dependencies(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    lib = build_sample_library(db)
    db.commit()
    statute_id, template_a_id = lib["statute"].id, lib["template_a"].id
    db.close()

    resp = client.get(f"/api/documents/{statute_id}")
    assert resp.status_code == 200
    assert len(resp.json()["clauses"]) == 1

    resp = client.get(f"/api/documents/{template_a_id}")
    data = resp.json()
    assert len(data["dependencies"]) == 1
    assert data["dependencies"][0]["to_clause_ref"] == "4"

    resp = client.get("/api/documents/99999")
    assert resp.status_code == 404


def test_run_scan_endpoint_ingests_real_files(api):
    client, _, dirs = api
    (dirs["templates"] / "checklist.txt").write_text("A standalone checklist with no citations.")
    (dirs["inbox"] / "memo.txt").write_text("A short firm memo template.")

    resp = client.post("/api/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["classified_from_inbox"]) == 1
    assert "Checklist" in data["new_documents"]


def test_schedule_status_endpoint(api):
    client, _, _ = api
    resp = client.get("/api/schedule-status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["within_window"], bool)
    assert "Singapore" in data["window_description"]


def test_check_sso_live_outside_window_refuses(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(cli_module, "should_run_now", lambda: False)

    resp = client.post("/api/check-sso", json={"live": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "3am-7am" in data["message"]


def test_check_sso_simulate_creates_flags_via_api(api, monkeypatch):
    client, SessionLocal, _ = api
    db = SessionLocal()
    build_sample_library(db)
    db.commit()
    db.close()

    monkeypatch.setattr(
        cli_module,
        "TRACKED_ACTS",
        [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"], "local_filename": "SampleAct2024.txt"}],
    )

    resp = client.post("/api/check-sso", json={"simulate": True, "clause_ref": "4"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["change_events"]) == 1
    assert len(data["flags"]) == 2

    # Confirm it's really persisted, not just returned once
    resp2 = client.get("/api/flags?status=pending")
    assert len(resp2.json()) == 2


def test_accept_and_reject_flag_via_api(api, monkeypatch):
    client, SessionLocal, _ = api
    db = SessionLocal()
    build_sample_library(db)
    db.commit()
    db.close()

    monkeypatch.setattr(
        cli_module,
        "TRACKED_ACTS",
        [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"], "local_filename": "SampleAct2024.txt"}],
    )
    client.post("/api/check-sso", json={"simulate": True, "clause_ref": "4"})

    flags = client.get("/api/flags").json()
    assert len(flags) == 2

    resp = client.post(f"/api/flags/{flags[0]['id']}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    resp = client.post(f"/api/flags/{flags[1]['id']}/reject")
    assert resp.json()["status"] == "rejected"

    resp = client.post("/api/flags/99999/accept")
    assert resp.status_code == 404


def test_graph_endpoint_shapes_nodes_and_edges(api, monkeypatch):
    client, SessionLocal, _ = api
    db = SessionLocal()
    build_sample_library(db)
    db.commit()
    db.close()

    monkeypatch.setattr(
        cli_module,
        "TRACKED_ACTS",
        [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"], "local_filename": "SampleAct2024.txt"}],
    )
    check_resp = client.post("/api/check-sso", json={"simulate": True, "clause_ref": "4"})
    change_event_id = check_resp.json()["change_events"][0]["id"]

    resp = client.get(f"/api/graph/{change_event_id}")
    assert resp.status_code == 200
    data = resp.json()

    highlights = {n["label"]: n["highlight"] for n in data["nodes"]}
    assert any(h == "changed" for h in highlights.values())
    assert any(h == "direct" for h in highlights.values())
    assert any(h == "transitive" for h in highlights.values())


def test_redline_endpoint(api, monkeypatch):
    client, SessionLocal, _ = api
    db = SessionLocal()
    build_sample_library(db)
    db.commit()
    db.close()

    monkeypatch.setattr(
        cli_module,
        "TRACKED_ACTS",
        [{"act_id": "SAMPLEACT2024", "name": "Sample Act 2024", "clause_refs": ["4"], "local_filename": "SampleAct2024.txt"}],
    )
    check_resp = client.post("/api/check-sso", json={"simulate": True, "clause_ref": "4"})
    change_event_id = check_resp.json()["change_events"][0]["id"]

    resp = client.get(f"/api/changes/{change_event_id}/redline")
    assert resp.status_code == 200
    ops = resp.json()["ops"]
    assert any(o["op"] == "insert" for o in ops)


def test_upload_saves_to_inbox_and_classifies(api):
    client, _, dirs = api
    content = b"A short firm memo template for testing upload."

    resp = client.post(
        "/api/upload",
        files={"file": ("memo.txt", content, "text/plain")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["classified_from_inbox"]) == 1
    assert data["classified_from_inbox"][0]["document_name"] == "Memo"
    # File should have been moved out of inbox by the scan that followed
    assert not (dirs["inbox"] / "memo.txt").exists()


def test_upload_rejects_unsupported_extension(api):
    client, _, _ = api
    resp = client.post(
        "/api/upload",
        files={"file": ("malware.exe", b"binary junk", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_sanitizes_path_traversal_filename(api):
    client, _, dirs = api
    resp = client.post(
        "/api/upload",
        files={"file": ("../../evil.txt", b"A short firm memo.", "text/plain")},
    )
    assert resp.status_code == 200
    # Must land inside inbox, never escape it
    assert (dirs["root"] / "evil.txt").exists() is False
    escaped = dirs["root"].parent / "evil.txt"
    assert not escaped.exists()


def test_get_document_text_for_txt(api):
    client, SessionLocal, dirs = api
    (dirs["templates"] / "checklist.txt").write_text("Some checklist content mentioning section 4.")
    client.post("/api/scan")

    docs = client.get("/api/documents").json()
    doc_id = next(d["id"] for d in docs if d["name"] == "Checklist")

    resp = client.get(f"/api/documents/{doc_id}/text")
    assert resp.status_code == 200
    data = resp.json()
    assert "section 4" in data["text"]
    assert data["is_pdf"] is False
    assert data["pdf_url"] is None


def test_get_document_text_for_pdf(api):
    client, SessionLocal, dirs = api
    import fitz

    pdf_path = dirs["templates"] / "checklist.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "This PDF mentions section 4 of the Act.")
    pdf.save(str(pdf_path))
    pdf.close()

    client.post("/api/scan")
    docs = client.get("/api/documents").json()
    doc_id = next(d["id"] for d in docs if d["name"] == "Checklist")

    resp = client.get(f"/api/documents/{doc_id}/text")
    data = resp.json()
    assert "section 4" in data["text"]
    assert data["is_pdf"] is True
    assert data["pdf_url"] == "/library/templates/checklist.pdf"
