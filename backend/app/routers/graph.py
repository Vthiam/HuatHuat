from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import ChangeEvent, Flag

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/{change_event_id}", response_model=schemas.GraphOut)
def get_graph(change_event_id: int, db: Session = Depends(get_db)):
    event = db.query(ChangeEvent).filter(ChangeEvent.id == change_event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Change event not found")

    clause = event.clause
    statute = clause.document

    nodes = {}
    edges = []

    statute_node_id = f"doc-{statute.id}"
    clause_node_id = f"clause-{clause.id}"
    nodes[statute_node_id] = schemas.GraphNodeOut(
        id=statute_node_id, label=statute.name, kind="document", highlight="none"
    )
    nodes[clause_node_id] = schemas.GraphNodeOut(
        id=clause_node_id,
        label=f"s.{clause.clause_ref} {clause.heading or ''}".strip(),
        kind="clause",
        highlight="changed",
    )
    edges.append(schemas.GraphEdgeOut(source=statute_node_id, target=clause_node_id))

    flags = db.query(Flag).filter(Flag.change_event_id == change_event_id).all()
    for flag in flags:
        doc = flag.document
        doc_node_id = f"doc-{doc.id}"
        highlight = "direct" if flag.flag_type.value == "direct_dependency" else "transitive"
        nodes[doc_node_id] = schemas.GraphNodeOut(id=doc_node_id, label=doc.name, kind="document", highlight=highlight)

        if flag.flag_type.value == "direct_dependency":
            edges.append(schemas.GraphEdgeOut(source=clause_node_id, target=doc_node_id))
        elif flag.via_document_id:
            via_node_id = f"doc-{flag.via_document_id}"
            edges.append(schemas.GraphEdgeOut(source=via_node_id, target=doc_node_id))

    return schemas.GraphOut(nodes=list(nodes.values()), edges=edges)
