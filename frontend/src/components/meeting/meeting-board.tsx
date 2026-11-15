"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ReactFlow, Background, Controls, Handle, Position, addEdge,
  applyEdgeChanges, applyNodeChanges, type Connection, type Edge,
  type EdgeChange, type Node, type NodeChange, type NodeProps,
} from "@xyflow/react";
import { ArrowUpRight, Check, Pause, Play, Plus, Save, Trash2 } from "lucide-react";
import { api, ApiError, type BoardNodeKind, type MeetingBoardNode, type MeetingBoardRecord } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type CardData = { kind: BoardNodeKind; title: string; text: string; origin: string } & Record<string, unknown>;
type FlowNode = Node<CardData, "boardCard">;

const KINDS: Record<BoardNodeKind, { label: string; accent: string }> = {
  summary: { label: "Overview", accent: "border-primary/50" },
  decision: { label: "Decision", accent: "border-primary" },
  task: { label: "Next step", accent: "border-success" },
  risk: { label: "Risk", accent: "border-warning" },
  question: { label: "Question", accent: "border-signal" },
  idea: { label: "Idea", accent: "border-primary/60" },
  note: { label: "Note", accent: "border-border" },
  timeline: { label: "Timeline", accent: "border-success/70" },
};

function BoardCard({ data, selected }: NodeProps<FlowNode>) {
  const style = KINDS[data.kind];
  return <div className={`w-64 rounded-2xl border-l-4 bg-card p-4 shadow-md ring-1 ring-border ${style.accent} ${selected ? "ring-2 ring-primary" : ""}`}>
    <Handle type="target" position={Position.Left} className="!size-2 !bg-primary" />
    <p className="text-[11px] font-semibold text-muted-foreground">{style.label}{data.origin === "ai" ? " · AI draft" : ""}</p>
    <h3 className="mt-2 line-clamp-3 font-heading text-sm font-semibold leading-snug text-foreground">{data.title}</h3>
    {data.text && <p className="mt-2 line-clamp-4 text-xs leading-5 text-muted-foreground">{data.text}</p>}
    <Handle type="source" position={Position.Right} className="!size-2 !bg-primary" />
  </div>;
}

const nodeTypes = { boardCard: BoardCard };

function toFlowNodes(board: MeetingBoardRecord): FlowNode[] {
  return board.nodes.map((item) => ({
    id: item.id, type: "boardCard", position: { x: item.x, y: item.y },
    data: { kind: item.kind, title: item.title, text: item.text, origin: item.origin },
  }));
}

export function MeetingBoard({ meetingId, captureId }: { meetingId?: string; captureId?: string }) {
  const [board, setBoard] = useState<MeetingBoardRecord | null>(null);
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const result = meetingId ? await api.getMeetingBoard(meetingId) : await api.getCaptureBoard(captureId!);
    setBoard(result);
    setNodes(toFlowNodes(result));
    setEdges(result.edges.map((edge) => ({ ...edge, type: "smoothstep" })));
    setDirty(false);
    setError(null);
  }, [meetingId, captureId]);

  useEffect(() => { void load().catch(() => setError("Could not load this board.")); }, [load]);
  useEffect(() => {
    if (dirty || board?.external_url) return;
    const timer = window.setInterval(() => { void load().catch(() => undefined); }, 8000);
    return () => window.clearInterval(timer);
  }, [dirty, load, board?.external_url]);

  const selected = useMemo(() => board?.nodes.find((item) => item.id === selectedId) ?? null, [board, selectedId]);

  const onNodesChange = useCallback((changes: NodeChange<FlowNode>[]) => {
    setNodes((current) => applyNodeChanges(changes, current));
    if (changes.some((change) => change.type === "position" && change.dragging === false)) setDirty(true);
  }, []);
  const onEdgesChange = useCallback((changes: EdgeChange<Edge>[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
    if (changes.some((change) => change.type === "remove")) setDirty(true);
  }, []);
  const onConnect = useCallback((connection: Connection) => {
    setEdges((current) => addEdge({ ...connection, id: crypto.randomUUID(), type: "smoothstep" }, current));
    setDirty(true);
  }, []);

  function updateNode(patch: Partial<MeetingBoardNode>) {
    if (!board || !selectedId) return;
    setBoard({ ...board, nodes: board.nodes.map((item) => item.id === selectedId ? { ...item, ...patch } : item) });
    setNodes((current) => current.map((node) => node.id === selectedId ? {
      ...node, data: { ...node.data, ...patch },
    } : node));
    setDirty(true);
    setSaved(false);
  }

  function addIdea() {
    if (!board) return;
    const id = crypto.randomUUID();
    const position = { x: 120 + (board.nodes.length % 3) * 300, y: 120 + Math.floor(board.nodes.length / 3) * 190 };
    const item: MeetingBoardNode = { id, kind: "idea", title: "New idea", text: "", x: position.x, y: position.y, origin: "manual", locked: false, source_start_ms: null, source_id: null };
    setBoard({ ...board, nodes: [...board.nodes, item] });
    setNodes((current) => [...current, { id, type: "boardCard", position, data: { kind: item.kind, title: item.title, text: "", origin: "manual" } }]);
    setSelectedId(id);
    setDirty(true);
    setSaved(false);
  }

  function removeSelected() {
    if (!board || !selectedId) return;
    setBoard({ ...board, nodes: board.nodes.filter((node) => node.id !== selectedId) });
    setNodes((current) => current.filter((node) => node.id !== selectedId));
    setEdges((current) => current.filter((edge) => edge.source !== selectedId && edge.target !== selectedId));
    setSelectedId(null);
    setDirty(true);
    setSaved(false);
  }

  async function save() {
    if (!board || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      const positions = new Map(nodes.map((node) => [node.id, node.position]));
      const updated = await api.saveMeetingBoard({
        ...board,
        nodes: board.nodes.map((item) => ({ ...item, x: positions.get(item.id)?.x ?? item.x, y: positions.get(item.id)?.y ?? item.y })),
        edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
      });
      setBoard(updated);
      setNodes(toFlowNodes(updated));
      setEdges(updated.edges.map((edge) => ({ ...edge, type: "smoothstep" })));
      setDirty(false);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 409
        ? "Someone changed this board. Copy any unsaved text, then reload the board to review their changes."
        : "Could not save the board. Your edits are still here.");
    } finally {
      setSaving(false);
    }
  }

  if (!board) return <div className="rounded-2xl border p-8 text-sm text-muted-foreground">{error || "Loading the meeting board…"}</div>;
  if (board.external_url) return <section className="flex flex-col gap-3 rounded-2xl border bg-card p-5" aria-label="Shared FigJam board">
    <h2 className="font-heading text-lg font-semibold">Your board is in FigJam</h2>
    <p className="text-sm text-muted-foreground">Open the editable file and use Figma’s Share button to invite collaborators.</p>
    <Button className="w-fit" nativeButton={false} render={<a href={board.external_url} target="_blank" rel="noopener noreferrer" />}><ArrowUpRight data-icon="inline-start" />Open FigJam</Button>
  </section>;

  return <section className="overflow-hidden rounded-2xl border bg-card" aria-label="Meeting whiteboard">
    <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3 sm:px-5">
      <div className="min-w-0 flex-1">
        <h2 className="font-heading text-base font-semibold">Meeting board</h2>
        <p className="text-xs text-muted-foreground">Move ideas, connect related points, and edit the AI draft together.</p>
      </div>
      <Button size="sm" variant="outline" onClick={addIdea}><Plus className="size-4" />Add idea</Button>
      {captureId && <Button size="sm" variant="outline" onClick={() => void api.pauseMeetingBoard(board.id, !board.paused).then(setBoard).catch(() => setError("Could not change AI board updates."))}>
        {board.paused ? <Play className="size-4" /> : <Pause className="size-4" />}{board.paused ? "Resume AI" : "Pause AI"}
      </Button>}
      <Button size="sm" onClick={() => void save()} disabled={!dirty || saving}><Save className="size-4" />{saving ? "Saving…" : "Save board"}</Button>
    </div>
    {error && <div className="flex items-center justify-between gap-3 border-b px-4 py-2 text-sm text-destructive" role="alert"><span>{error}</span><Button size="sm" variant="outline" onClick={() => void load()}>Reload board</Button></div>}
    {saved && !error && <p className="flex items-center gap-1.5 border-b px-4 py-2 text-xs text-success" role="status"><Check className="size-3.5" />Board saved</p>}
    <div className="grid lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="h-[36rem] min-w-0 bg-background/40">
        <ReactFlow<FlowNode, Edge> nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, node) => setSelectedId(node.id)}
          onNodeDragStop={() => setDirty(true)} onPaneClick={() => setSelectedId(null)} fitView minZoom={0.3} maxZoom={1.8} nodesConnectable>
          <Background gap={24} color="var(--border)" />
          <Controls className="!border-border !bg-card" />
        </ReactFlow>
      </div>
      <aside className="border-t p-4 lg:border-l lg:border-t-0" aria-label="Selected board item">
        {selected ? <div className="space-y-4">
          <div className="flex items-center justify-between"><p className="text-sm font-semibold">Edit point</p><Button size="icon-sm" variant="ghost" onClick={removeSelected} aria-label="Remove point"><Trash2 className="size-4" /></Button></div>
          <div><label htmlFor="board-kind" className="mb-1 block text-xs font-medium">Type</label><select id="board-kind" className="w-full rounded-lg border bg-background px-3 py-2 text-sm" value={selected.kind} onChange={(event) => updateNode({ kind: event.target.value as BoardNodeKind })}>{Object.entries(KINDS).map(([value, detail]) => <option key={value} value={value}>{detail.label}</option>)}</select></div>
          <div><label htmlFor="board-title" className="mb-1 block text-xs font-medium">Title</label><Input id="board-title" value={selected.title} maxLength={160} onChange={(event) => updateNode({ title: event.target.value })} /></div>
          <div><label htmlFor="board-text" className="mb-1 block text-xs font-medium">Details</label><Textarea id="board-text" value={selected.text} maxLength={4000} rows={5} onChange={(event) => updateNode({ text: event.target.value })} /></div>
          {selected.source_start_ms != null && <Link className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline" href={meetingId ? `?tab=transcript&t=${selected.source_start_ms}` : "#live-captions"}><ArrowUpRight className="size-3.5" />Open source moment</Link>}
          <p className="text-xs text-muted-foreground">{selected.origin === "ai" ? "AI draft. Your changes will be kept during future updates." : "Edited by your team."}</p>
        </div> : <p className="text-sm leading-6 text-muted-foreground">Select a point to edit it. Drag from a point’s right handle to connect it to another.</p>}
      </aside>
    </div>
  </section>;
}
