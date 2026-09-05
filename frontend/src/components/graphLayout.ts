import type { Edge, Node } from "reactflow";
import type { Graph } from "../types";

export const HIGHLIGHT_COLOR: Record<string, string> = {
  changed: "#b5482f",
  direct: "#b8860b",
  transitive: "#2f7d4f",
  none: "#75726c",
};

export function layout(graph: Graph): { nodes: Node[]; edges: Edge[] } {
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
          transition: "background 200ms ease, border-color 200ms ease",
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
