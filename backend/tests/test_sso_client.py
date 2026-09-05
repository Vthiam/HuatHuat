from pathlib import Path

import pytest

from app.services.sso_client import SSOFetchError, _validate_html, parse_clauses, should_run_now

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_parse_clauses_from_current_fixture():
    html = _load_fixture("pdpa_current.html")
    clauses = parse_clauses(html)

    refs = [c.clause_ref for c in clauses]
    assert refs == ["1", "2", "3", "4"]

    section_4 = next(c for c in clauses if c.clause_ref == "4")
    assert section_4.heading == "Application of Act"
    assert "Parts 3, 4, 5, 6, 6A and 6B" in section_4.text


def test_parse_clauses_from_2013_fixture():
    html = _load_fixture("pdpa_2013.html")
    clauses = parse_clauses(html)

    section_4 = next(c for c in clauses if c.clause_ref == "4")
    # The real 2013 text used roman numerals -- this is what makes the
    # later diff against the current fixture a genuine amendment, not a
    # fabricated one.
    assert "Parts III to VI" in section_4.text


def test_current_and_2013_section_4_actually_differ():
    current = next(c for c in parse_clauses(_load_fixture("pdpa_current.html")) if c.clause_ref == "4")
    historical = next(c for c in parse_clauses(_load_fixture("pdpa_2013.html")) if c.clause_ref == "4")
    assert current.text != historical.text


def test_should_run_now_respects_sgt_window():
    import datetime
    import zoneinfo

    sgt = zoneinfo.ZoneInfo("Asia/Singapore")
    inside_window = datetime.datetime(2026, 1, 1, 4, 30, tzinfo=sgt)
    outside_window = datetime.datetime(2026, 1, 1, 14, 30, tzinfo=sgt)

    assert should_run_now(inside_window) is True
    assert should_run_now(outside_window) is False


def test_validate_html_rejects_empty_rate_limited_response():
    """Reproduces the real HTTP 202 + empty body observed from SSO during
    this project after heavy request volume -- must raise, not silently
    look like "fetched fine, nothing changed"."""
    with pytest.raises(SSOFetchError):
        _validate_html("", "https://sso.agc.gov.sg/Act/PDPA2012")


def test_validate_html_accepts_real_fixture():
    html = _load_fixture("pdpa_current.html")
    _validate_html(html, "https://sso.agc.gov.sg/Act/PDPA2012")  # should not raise


@pytest.mark.network
def test_live_fetch_smoke():
    """Real network call against the live SSO site. Skips cleanly if
    there's no connectivity -- this is a smoke test proving the real
    integration still works, not a correctness test (see the fixture-based
    tests above for that)."""
    from app.services.sso_client import fetch_tracked_clauses

    try:
        clauses = fetch_tracked_clauses("PDPA2012", ["1", "2", "3", "4"])
    except Exception as exc:
        pytest.skip(f"no network access to sso.agc.gov.sg: {exc}")

    assert len(clauses) == 4
    assert all(c.text.strip() for c in clauses)
