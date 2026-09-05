import { useEffect, useMemo, useState } from "react";
import ReactFlow, { Background, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import { api } from "../api";
import type { ChangeEvent, Graph } from "../types";

const HIGHLIGHT_COLOR: Record<string, string> = {
  changed: "#b5482f",
  direct: "#b8860b",
  transitive: "#2f7d4f",
  none: "#75726c",
};

function layout(graph: Graph): { nodes: Node[]; edges: Edge[] } {
  const levelOf = (highlight: string) =>
    highlight === "none" ? 0 : highlight === "changed" ? 1 : highlight === "direct" ? 2 : 3;

  const byLevel: Record<number, typeof graph.nodes> = {};
  for (const n of graph.nodes) {
    const lvl = levelOf(n.highlight);
    (byLevel[lvl] ??= []).push(n);
  }

  const nodes: Node[] = [];
  Object.entries(byLevel).forEach(([lvlStr, levelNodes]) => {
    const lvl = Number(lvlStr);
    const spacing = 220;
    const totalWidth = (levelNodes.length - 1) * spacing;
    levelNodes.forEach((n, i) => {
      nodes.push({
        id: n.id,
        position: { x: i * spacing - totalWidth / 2, y: lvl * 130 },
        data: { label: n.label },
        style: {
          background: HIGHLIGHT_COLOR[n.highlight] + "22",
          border: `2px solid ${HIGHLIGHT_COLOR[n.highlight]}`,
          borderRadius: 8,
          padding: 8,
          fontSize: 12,
          width: 190,
        },
      });
    });
  });

  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    animated: false,
  }));

  return { nodes, edges };
}

export function GraphView() {
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listChanges()
      .then((cs) => {
        setChanges(cs);
        if (cs.length > 0) setSelectedId(cs[0].id);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (selectedId === null) return;
    api
      .getGraph(selectedId)
      .then(setGraph)
      .catch((e) => setError((e as Error).message));
  }, [selectedId]);

  const { nodes, edges } = useMemo(() => (graph ? layout(graph) : { nodes: [], edges: [] }), [graph]);

  return (
    <div>
      {error && <div className="error-box">{error}</div>}

      <div className="controls-row">
        <label>
          Change event:
          <select
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(Number(e.target.value))}
            style={{ marginLeft: 6 }}
          >
            {changes.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.id} - s.{c.clause_ref} of {c.document_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="legend">
        <span>
          <span className="dot" style={{ background: HIGHLIGHT_COLOR.changed }} />
          Changed clause
        </span>
        <span>
          <span className="dot" style={{ background: HIGHLIGHT_COLOR.direct }} />
          Direct dependency
        </span>
        <span>
          <span className="dot" style={{ background: HIGHLIGHT_COLOR.transitive }} />
          Transitive dependency
        </span>
      </div>

      {changes.length === 0 ? (
        <div className="empty-state">No changes yet -- run a check on the Change Feed tab first.</div>
      ) : (
        <div className="graph-wrap">
          <ReactFlow nodes={nodes} edges={edges} fitView>
            <Background />
          </ReactFlow>
        </div>
      )}
    </div>
  );
}
