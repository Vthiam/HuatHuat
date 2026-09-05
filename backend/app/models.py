"""The frozen contract every other branch depends on.

Two things live on disk for this project, and it's easy to conflate them:

1. Real files in law_library/ (inbox, statutes, templates, reports) -- plain
   text, editable in an editor, not defined here at all.
2. This database (backend/data/app.db) -- structured records that describe
   and link those files (which genre, what depends on what, what changed).
   THIS file defines that second thing. A Document row POINTS AT a file via
   `file_path`; it is not the file.

Enums are used (not raw strings) for every closed-set field so a typo in
one branch's code fails at import/type-check time instead of silently at
runtime in another branch's code.
"""
import datetime
import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


def utcnow():
    return datetime.datetime.utcnow()


class DocumentGenre(str, enum.Enum):
    STATUTE = "statute"
    TEMPLATE = "template"
    CASE = "case"  # reserved, unused in v1 -- see PRODUCT_SPEC.md P1-4


class DocumentSource(str, enum.Enum):
    SSO = "sso"
    FIRM = "firm"


class ChangeSource(str, enum.Enum):
    LIVE = "live"
    SIMULATED = "simulated"


class ReasoningSource(str, enum.Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    HEURISTIC = "heuristic"


class FlagType(str, enum.Enum):
    DIRECT_DEPENDENCY = "direct_dependency"
    TRANSITIVE_DEPENDENCY = "transitive_dependency"


class FlagStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Document(Base):
    """A node in the firm's library: a statute mirrored from SSO, or a
    firm-authored template/checklist. `file_path` is relative to
    law_library/ and is the on-disk mirror every branch reads/writes.

    classification_source/classification_confidence are null when a human
    placed the file directly in statutes/ or templates/. They're set when
    feature/ingestion-citations auto-filed the document in from inbox/
    instead -- this is what lets a low-confidence auto-classification
    surface for human confirmation instead of being silently trusted.
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    genre = Column(SAEnum(DocumentGenre), nullable=False)
    source = Column(SAEnum(DocumentSource), nullable=False)
    file_path = Column(String, nullable=False, unique=True)
    sso_url = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    classification_source = Column(SAEnum(ReasoningSource), nullable=True)
    classification_confidence = Column(Float, nullable=True)

    clauses = relationship("Clause", back_populates="document", cascade="all, delete-orphan")


class Clause(Base):
    """One numbered section of a statute. Only Document.genre == STATUTE
    documents have clauses."""

    __tablename__ = "clauses"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    clause_ref = Column(String, nullable=False)  # e.g. "4"
    heading = Column(String, nullable=True)
    text = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("document_id", "clause_ref", name="uq_clause_document_ref"),)

    document = relationship("Document", back_populates="clauses")
    versions = relationship("ClauseVersion", back_populates="clause", cascade="all, delete-orphan")


class ClauseVersion(Base):
    """Append-only history of a clause's text, so a redline / "what was
    deleted" can always be reconstructed even after auto-sync overwrites
    Clause.text with the latest version."""

    __tablename__ = "clause_versions"

    id = Column(Integer, primary_key=True)
    clause_id = Column(Integer, ForeignKey("clauses.id"), nullable=False)
    text = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    captured_at = Column(DateTime, default=utcnow)

    clause = relationship("Clause", back_populates="versions")


class DependencyEdge(Base):
    """Declares that from_document relies on either a specific statute
    clause (to_clause_id set -> direct dependency) or another document
    generically (to_clause_id null -> e.g. a workflow that invokes a
    checklist template). The null case is what makes transitive
    propagation possible: feature/graph-impact walks from a changed clause
    to its direct citers, then from each of those to whatever cites THEM,
    by following this same table with to_clause_id IS NULL.

    Declared once at ingestion time (by feature/ingestion-citations), so
    impact analysis later is a graph query, not a re-read of every
    document in the library.
    """

    __tablename__ = "dependency_edges"

    id = Column(Integer, primary_key=True)
    from_document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    to_document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    to_clause_id = Column(Integer, ForeignKey("clauses.id"), nullable=True)
    excerpt = Column(Text, nullable=False)

    from_document = relationship("Document", foreign_keys=[from_document_id])
    to_document = relationship("Document", foreign_keys=[to_document_id])
    to_clause = relationship("Clause")


class ChangeEvent(Base):
    """A detected difference between a statute clause's stored text and
    its latest text (from a real SSO fetch, or a simulated stand-in for
    demo reliability -- `source` always says which)."""

    __tablename__ = "change_events"

    id = Column(Integer, primary_key=True)
    clause_id = Column(Integer, ForeignKey("clauses.id"), nullable=False)
    old_text = Column(Text, nullable=False)
    new_text = Column(Text, nullable=False)
    source = Column(SAEnum(ChangeSource), nullable=False)
    legal_effect_summary = Column(Text, nullable=True)
    summary_source = Column(SAEnum(ReasoningSource), nullable=True)
    detected_at = Column(DateTime, default=utcnow)

    clause = relationship("Clause")
    flags = relationship("Flag", back_populates="change_event", cascade="all, delete-orphan")


class Flag(Base):
    """A document that may need a lawyer's attention because of a
    ChangeEvent -- either it directly cites the changed clause, or it
    depends on another document that was itself flagged (transitive).

    Revised design (explicit product decision, overriding the original
    "never auto-edit downstream documents" rule): Accepting a flag DOES
    apply suggested_replacement in place of original_sentence in the real
    document -- but only for .docx/.txt (see document_editor.py); PDFs
    keep the original highlight-only, human-edits-it-themselves behavior.
    Rejecting a flag applies no AI-suggested text, but the human can
    self-edit instead (human_edit_text), which still counts as
    document_edited if applied.
    """

    __tablename__ = "flags"

    id = Column(Integer, primary_key=True)
    change_event_id = Column(Integer, ForeignKey("change_events.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    flag_type = Column(SAEnum(FlagType), nullable=False)
    depth = Column(Integer, nullable=False, default=1)  # hop count from the changed clause
    via_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)  # set for transitive flags
    recommendation_text = Column(Text, nullable=True)
    recommendation_source = Column(SAEnum(ReasoningSource), nullable=True)
    # original_sentence/suggested_replacement are the AI's proposed edit --
    # always a suggestion, never applied by anything that creates a Flag.
    # Only accepting the flag (see cli.py/routers/flags.py) applies
    # suggested_replacement in place of original_sentence, and only for
    # .docx/.txt documents (see document_editor.py) -- PDFs keep the
    # highlight-only behavior since reliable in-place PDF text replacement
    # isn't feasible. Both null when the model found nothing to change, or
    # the heuristic fallback produced this flag (it can't verify a quote
    # against real document text, so it never proposes one).
    original_sentence = Column(Text, nullable=True)
    suggested_replacement = Column(Text, nullable=True)
    document_edited = Column(Boolean, nullable=False, default=False)  # true once an edit actually changed the file
    human_edit_text = Column(Text, nullable=True)  # set when a human wrote their own replacement instead of the AI's
    status = Column(SAEnum(FlagStatus), nullable=False, default=FlagStatus.PENDING)
    created_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)

    change_event = relationship("ChangeEvent", back_populates="flags")
    document = relationship("Document", foreign_keys=[document_id])
    via_document = relationship("Document", foreign_keys=[via_document_id])
