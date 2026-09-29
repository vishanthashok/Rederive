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
import { useTheme } from "next-themes";
import { memo, useEffect, useMemo, useState } from "react";
import { label, type Graph, type GraphNode, type Status } from "@/lib/api";
import { ancestors, descendants } from "@/lib/graph";
import { STATUS, cssVar } from "@/lib/status";

const W = 220;
const H = 48;

type Data = { rec: GraphNode; flash?: string; selected: boolean; dim: boolean; related: boolean };

const RecordNode = memo(function RecordNode({ data }: NodeProps<Node<Data>>) {
  const { rec, flash, selected, dim, related } = data;
  const s = STATUS[rec.status] ?? STATUS.valid;
  const Icon = s.icon;
  const cls = [
    "node",
    rec.status,
    flash ? `flash-${flash}` : "",
    selected ? "selected" : "",
    dim ? "dim" : "",
    related && !selected ? "related" : "",
  ].join(" ");
  return (
    <div className={cls} title={rec.text}>
      <Handle type="target" position={Position.Left} />
      <div className="name">
        <span>{label(rec)}</span>
        <span className="flex shrink-0 items-center gap-1 font-normal text-muted">
          <Icon
            aria-hidden
            className={`size-3 ${rec.status === "rebuilding" ? "animate-spin" : ""}`}
            style={{ color: s.color }}
          />
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
  hiddenStatuses,
  focusSelected,
}: {
  graph: Graph;
  flashes: Record<string, string>;
  selected: string | null;
  onSelect: (id: string) => void;
  /** Records with these statuses are dimmed. */
  hiddenStatuses: Set<Status>;
  /** Dim everything outside the selected record's lineage. */
  focusSelected: boolean;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const { resolvedTheme } = useTheme();

  // Layout depends only on the shape of the graph, not on statuses.
  const shape = useMemo(
    () => graph.nodes.map((n) => n.id).join() + "|" + graph.edges.map((e) => e.child_id + e.parent_id).join(),
    [graph],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const positions = useMemo(() => layout(graph), [shape]);

  // Lineage of the hovered node, or of the selected node in focus mode.
  const anchor = hovered ?? (focusSelected ? selected : null);
  const lineage = useMemo(() => {
    if (!anchor) return null;
    return new Set([anchor, ...ancestors(graph, anchor), ...descendants(graph, anchor)]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor, shape]);

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
        data: {
          rec,
          flash: flashes[rec.id],
          selected: rec.id === selected,
          dim: hiddenStatuses.has(rec.status) || (lineage !== null && !lineage.has(rec.id)),
          related: lineage?.has(rec.id) ?? false,
        },
        ariaLabel: `${label(rec)}, ${rec.kind} version ${rec.version}, ${STATUS[rec.status]?.label ?? rec.status}`,
        draggable: false,
        measured: measured.get(rec.id),
      }));
    });
  }, [graph, positions, flashes, selected, hiddenStatuses, lineage, setNodes]);

  const edges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: `${e.parent_id}-${e.child_id}`,
        source: e.parent_id,
        target: e.child_id,
        className: lineage && !(lineage.has(e.parent_id) && lineage.has(e.child_id)) ? "dim" : undefined,
        style: e.alias ? { strokeDasharray: "4 3" } : undefined,
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
      })),
    [graph.edges, lineage],
  );

  // Resolve status colors from CSS so the MiniMap follows the theme.
  const miniColors = useMemo(
    () => ({
      stale: cssVar("--stale", "#b7791f"),
      rebuilding: cssVar("--rebuilding", "#2b6cb0"),
      retracted: cssVar("--retracted", "#c53030"),
      other: cssVar("--muted", "#9c9b95"),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [resolvedTheme],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={(_, n) => onSelect(n.id)}
      onNodeMouseEnter={(_, n) => setHovered(n.id)}
      onNodeMouseLeave={() => setHovered(null)}
      onKeyDown={(e) => {
        // Nodes are focusable with Tab. Enter or Space selects the focused node.
        if (e.key !== "Enter" && e.key !== " ") return;
        const id = (e.target as HTMLElement).closest<HTMLElement>(".react-flow__node")?.dataset.id;
        if (id) {
          e.preventDefault();
          onSelect(id);
        }
      }}
      fitView
      minZoom={0.1}
      colorMode={resolvedTheme === "dark" ? "dark" : "light"}
      proOptions={{ hideAttribution: true }}
    >
      <FocusOnSelect selected={selected} graph={graph} />
      <Background gap={24} />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        ariaLabel="Graph overview"
        className="max-lg:!hidden"
        nodeColor={(n) => {
          const status = (n.data as Data).rec.status;
          return status === "stale" || status === "rebuilding" || status === "retracted"
            ? miniColors[status]
            : miniColors.other;
        }}
      />
    </ReactFlow>
  );
}
