"use client";

import dagre from "@dagrejs/dagre";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import { memo, useEffect, useMemo } from "react";
import { label, type Graph, type GraphNode } from "@/lib/api";

const W = 210;
const H = 48;

type Data = { rec: GraphNode; flash?: string; selected: boolean };

const RecordNode = memo(function RecordNode({ data }: NodeProps<Node<Data>>) {
  const { rec, flash, selected } = data;
  const cls = ["node", rec.status, flash ? `flash-${flash}` : "", selected ? "selected" : ""].join(" ");
  return (
    <div className={cls} title={rec.text}>
      <Handle type="target" position={Position.Left} />
      <div className="name">
        <span>{label(rec)}</span>
        <span>
          {rec.kind} v{rec.version}
        </span>
      </div>
      <div className="text">{rec.text}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});

const nodeTypes = { record: RecordNode };

function layout(graph: Graph): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 10, ranksep: 70, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  graph.nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }));
  graph.edges.forEach((e) => g.setEdge(e.parent_id, e.child_id));
  dagre.layout(g);
  const out = new Map<string, { x: number; y: number }>();
  graph.nodes.forEach((n) => {
    const p = g.node(n.id);
    out.set(n.id, { x: p.x - W / 2, y: p.y - H / 2 });
  });
  return out;
}

// Pan and zoom to the selected node and its direct inputs. At full-graph zoom
// node text is too small to read.
function FocusOnSelect({ selected, graph }: { selected: string | null; graph: Graph }) {
  const flow = useReactFlow();
  useEffect(() => {
    if (!selected) return;
    const ids = [selected, ...graph.edges.filter((e) => e.child_id === selected).map((e) => e.parent_id)];
    flow.fitView({ nodes: ids.map((id) => ({ id })), duration: 600, padding: 0.4, maxZoom: 1.1 });
    // Refocus only when the selection changes, not on every graph update.
  }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export default function GraphView({
  graph,
  flashes,
  selected,
  onSelect,
}: {
  graph: Graph;
  flashes: Record<string, string>;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  // Layout depends only on the shape of the graph, not on statuses.
  const shape = useMemo(
    () => graph.nodes.map((n) => n.id).join() + "|" + graph.edges.map((e) => e.child_id + e.parent_id).join(),
    [graph],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const positions = useMemo(() => layout(graph), [shape]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<Data>>([]);
  useEffect(() => {
    // Keep each node's measured size across updates. React Flow hides nodes
    // it has not measured, and an unchanged size never triggers a re-measure.
    setNodes((prev) => {
      const measured = new Map(prev.map((n) => [n.id, n.measured]));
      return graph.nodes.map((rec) => ({
        id: rec.id,
        type: "record",
        position: positions.get(rec.id) ?? { x: 0, y: 0 },
        data: { rec, flash: flashes[rec.id], selected: rec.id === selected },
        draggable: false,
        measured: measured.get(rec.id),
      }));
    });
  }, [graph, positions, flashes, selected, setNodes]);

  const edges: Edge[] = graph.edges.map((e) => ({
    id: `${e.parent_id}-${e.child_id}`,
    source: e.parent_id,
    target: e.child_id,
    style: e.alias ? { strokeDasharray: "4 3" } : undefined,
    markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
  }));

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, n) => onSelect(n.id)}
      fitView
      minZoom={0.1}
      proOptions={{ hideAttribution: true }}
    >
      <FocusOnSelect selected={selected} graph={graph} />
      <Background gap={24} />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => {
          const status = (n.data as Data).rec.status;
          return status === "stale" ? "#b7791f" : status === "rebuilding" ? "#2b6cb0"
            : status === "retracted" ? "#c53030" : "#9c9b95";
        }}
      />
    </ReactFlow>
  );
}
