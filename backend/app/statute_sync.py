"""Orchestrates keeping a tracked statute's DB rows and on-disk mirror
(`law_library/statutes/*.txt`) in sync with SSO.

This is the only module allowed to create/modify Clause, ClauseVersion, or
ChangeEvent rows, and the only one that writes into law_library/statutes/.
Everything downstream (which other documents are affected, what to
recommend) is feature/graph-impact's job -- this module's output is just
the ChangeEvent rows it creates.

Auto-sync is safe here specifically because a statute's local copy is a
mirror of an authoritative external source: there's no legal judgment in
updating it, the law now says X so the copy should say X. That is NOT true
for any other document type in this library, which is why this pattern
must not be copied to templates/cases later.
"""
import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from .config import LAW_LIBRARY_DIR, SSO_BASE_URL, STATUTES_DIR
from .models import (
    ChangeEvent,
    ChangeSource,
    Clause,
    ClauseVersion,
    Document,
    DocumentGenre,
    DocumentSource,
)
from .services.diff_engine import has_changed
from .services.sso_client import ScrapedClause, fetch_tracked_clauses, fetch_tracked_historical_clauses


def _clause_sort_key(clause_ref: str):
    m = re.match(r"(\d+)(.*)", clause_ref)
    if m:
        return (int(m.group(1)), m.group(2))
    return (0, clause_ref)


def _write_statute_file(document: Document, clauses: List[Clause]) -> None:
    STATUTES_DIR.mkdir(parents=True, exist_ok=True)
    full_path = LAW_LIBRARY_DIR / document.file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [document.name, "=" * len(document.name), ""]
    for clause in sorted(clauses, key=lambda c: _clause_sort_key(c.clause_ref)):
        heading_line = f"[Section {clause.clause_ref}] {clause.heading or ''}".rstrip()
        lines.append(heading_line)
        lines.append(clause.text)
        lines.append("")
    full_path.write_text("\n".join(lines), encoding="utf-8")


def _get_or_create_statute_document(db: Session, act_config: dict) -> Document:
    doc = (
        db.query(Document)
        .filter_by(name=act_config["name"], genre=DocumentGenre.STATUTE)
        .first()
    )
    if doc is not None:
        return doc

    doc = Document(
        name=act_config["name"],
        genre=DocumentGenre.STATUTE,
        source=DocumentSource.SSO,
        file_path=f"statutes/{act_config['local_filename']}",
        sso_url=f"{SSO_BASE_URL}/Act/{act_config['act_id']}",
        last_synced_at=datetime.datetime.utcnow(),
    )
    db.add(doc)
    db.flush()
    return doc


def _ingest_scraped_clauses(
    db: Session, statute_doc: Document, scraped: List[ScrapedClause], source: ChangeSource
) -> List[ChangeEvent]:
    events: List[ChangeEvent] = []

    for sc in scraped:
        clause = (
            db.query(Clause)
            .filter_by(document_id=statute_doc.id, clause_ref=sc.clause_ref)
            .first()
        )

        if clause is None:
            # Brand new clause (first-time ingest, or a clause we've just
            # started tracking): establish the baseline, nothing to diff
            # against yet, so no ChangeEvent.
            clause = Clause(
                document_id=statute_doc.id,
                clause_ref=sc.clause_ref,
                heading=sc.heading,
                text=sc.text,
                version=1,
            )
            db.add(clause)
            db.flush()
            db.add(ClauseVersion(clause_id=clause.id, text=sc.text, version=1))
            continue

        if not has_changed(clause.text, sc.text):
            continue

        old_text = clause.text
        db.add(ClauseVersion(clause_id=clause.id, text=old_text, version=clause.version))
        clause.text = sc.text
        clause.heading = sc.heading or clause.heading
        clause.version += 1
        db.flush()

        change = ChangeEvent(clause_id=clause.id, old_text=old_text, new_text=sc.text, source=source)
        db.add(change)
        db.flush()
        events.append(change)

    statute_doc.last_synced_at = datetime.datetime.utcnow()
    db.flush()

    all_clauses = db.query(Clause).filter_by(document_id=statute_doc.id).all()
    _write_statute_file(statute_doc, all_clauses)

    db.commit()
    return events


def sync_live(db: Session, act_config: dict) -> List[ChangeEvent]:
    """Fetches CURRENT text from SSO and syncs against whatever's stored.
    This is the normal ongoing path -- first call after a seed establishes
    baselines with no ChangeEvents; later calls detect real amendments."""
    statute_doc = _get_or_create_statute_document(db, act_config)
    scraped = fetch_tracked_clauses(act_config["act_id"], act_config["clause_refs"])
    return _ingest_scraped_clauses(db, statute_doc, scraped, source=ChangeSource.LIVE)


def seed_from_historical(db: Session, act_config: dict, valid_date: str, doc_date: str) -> List[ChangeEvent]:
    """One-time bootstrap: seeds the tracked statute from a REAL past SSO
    snapshot (e.g. PDPA as it stood in 2013) rather than today's text, so
    the first sync_live() call afterwards produces a genuine redline
    against actual historical amendments -- not fabricated demo data."""
    statute_doc = _get_or_create_statute_document(db, act_config)
    scraped = fetch_tracked_historical_clauses(
        act_config["act_id"], act_config["clause_refs"], valid_date, doc_date
    )
    return _ingest_scraped_clauses(db, statute_doc, scraped, source=ChangeSource.LIVE)


def _apply_synthetic_edit(text: str) -> str:
    if "6A and 6B" in text:
        return text.replace("6A and 6B", "6A, 6B and 6C (Simulated Demo Amendment)")
    return text + " [Simulated demo amendment: this sentence was added for demonstration purposes.]"


def sync_simulated(db: Session, act_config: dict, clause_ref: str) -> List[ChangeEvent]:
    """Applies a small, clearly-synthetic edit to one already-tracked
    clause, so the rest of the pipeline can be demoed deterministically
    regardless of network conditions or whether a real SSO amendment
    happens to be live at demo time. Never fetches from the network."""
    statute_doc = (
        db.query(Document)
        .filter_by(name=act_config["name"], genre=DocumentGenre.STATUTE)
        .first()
    )
    if statute_doc is None:
        return []

    clause = (
        db.query(Clause)
        .filter_by(document_id=statute_doc.id, clause_ref=clause_ref)
        .first()
    )
    if clause is None:
        return []

    fake_scraped = [ScrapedClause(clause_ref=clause.clause_ref, heading=clause.heading, text=_apply_synthetic_edit(clause.text))]
    return _ingest_scraped_clauses(db, statute_doc, fake_scraped, source=ChangeSource.SIMULATED)
