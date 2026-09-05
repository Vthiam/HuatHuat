import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.services import classifier, llm


@pytest.fixture(autouse=True)
def no_real_llm_calls(monkeypatch):
    """Tests must be deterministic and fast regardless of whatever .env
    happens to exist on a given machine -- classifier.py/llm.py build their
    OpenAI client once at import time from whatever key was present then,
    so a real key in backend/.env would otherwise make every test run hit
    the real network. Forcing _client = None here always exercises the
    heuristic fallback path in tests; real-API behavior is verified
    separately, by hand, not by the automated suite."""
    monkeypatch.setattr(classifier, "_client", None)
    monkeypatch.setattr(llm, "_client", None)


@pytest.fixture()
def db_session():
    """A fresh in-memory SQLite DB per test -- never touches the real
    backend/data/app.db."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
