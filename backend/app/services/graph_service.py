"""Dependency-graph traversal: given a changed clause, find every document
that could be affected, directly or transitively, by walking
DependencyEdge records declared at ingestion time.

This is the load-bearing idea of the whole project: impact analysis is a
graph query over structured data declared up front, not a re-read of
every document in the library after every change. Pure function, no LLM,
no side effects -- just DB reads -- so it's fully deterministic and cheap
to test exhaustively.
"""
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import DependencyEdge, Document, FlagType


@dataclass
class AffectedDocument:
    document: Document
    flag_type: FlagType
    depth: int
    via_document: Optional[Document]
    dependency_path: List[str]


def find_affected_documents(db: Session, changed_clause_id: int) -> List[AffectedDocument]:
    """BFS worklist: start from documents that cite the changed clause
    directly, then repeatedly follow edges into any newly-flagged document
    until a pass finds nothing new ("until the document list is
    finished"). A `visited` set guards against infinite loops if the
    dependency graph ever contains a cycle."""
    results: List[AffectedDocument] = []
    visited_document_ids = set()

    direct_edges = db.query(DependencyEdge).filter(DependencyEdge.to_clause_id == changed_clause_id).all()

    frontier: List[AffectedDocument] = []
    for edge in direct_edges:
        doc = edge.from_document
        if doc.id in visited_document_ids:
            continue
        visited_document_ids.add(doc.id)
        item = AffectedDocument(
            document=doc,
            flag_type=FlagType.DIRECT_DEPENDENCY,
            depth=1,
            via_document=None,
            dependency_path=[doc.name],
        )
        results.append(item)
        frontier.append(item)

    depth = 1
    while frontier:
        depth += 1
        next_frontier: List[AffectedDocument] = []
        for prev in frontier:
            edges = (
                db.query(DependencyEdge)
                .filter(
                    DependencyEdge.to_document_id == prev.document.id,
                    DependencyEdge.to_clause_id.is_(None),
                )
                .all()
            )
            for edge in edges:
                doc = edge.from_document
                if doc.id in visited_document_ids:
                    continue
                visited_document_ids.add(doc.id)
                item = AffectedDocument(
                    document=doc,
                    flag_type=FlagType.TRANSITIVE_DEPENDENCY,
                    depth=depth,
                    via_document=prev.document,
                    dependency_path=prev.dependency_path + [doc.name],
                )
                results.append(item)
                next_frontier.append(item)
        frontier = next_frontier

    return results
