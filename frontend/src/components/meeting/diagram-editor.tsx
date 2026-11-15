"use client";

import "@excalidraw/excalidraw/index.css";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import type { DiagramScene } from "@/lib/api";

// Excalidraw touches window at import time, so it only loads in the browser.
const Excalidraw = dynamic(async () => (await import("@excalidraw/excalidraw")).Excalidraw, {
  ssr: false,
  loading: () => <p className="p-6 text-sm text-muted-foreground">Opening the drawing…</p>,
});

type Elements = DiagramScene["elements"];
type EditorApi = { getSceneElements: () => readonly unknown[] };

/** Convert Mermaid to editable Excalidraw elements. null = this diagram type converts only to a picture. */
export async function mermaidToElements(source: string): Promise<Elements | null> {
  const [{ parseMermaidToExcalidraw }, { convertToExcalidrawElements }] = await Promise.all([
    import("@excalidraw/mermaid-to-excalidraw"),
    import("@excalidraw/excalidraw"),
  ]);
  const { elements, files } = await parseMermaidToExcalidraw(source, { themeVariables: { fontSize: "20px" } });
  // Unsupported diagram types come back as a single embedded image; we keep drawings image-free.
  if (files && Object.keys(files).length) return null;
  return JSON.parse(JSON.stringify(convertToExcalidrawElements(elements, { regenerateIds: true }))) as Elements;
}

export function DiagramEditor({ title, source, scene, onSave, onClose }: {
  title: string;
  source: string;
  scene: DiagramScene | null | undefined;
  onSave: (scene: DiagramScene) => void;
  onClose: () => void;
}) {
  const [elements, setElements] = useState<Elements | null>(scene?.elements ?? null);
  const [unsupported, setUnsupported] = useState(false);
  const [failed, setFailed] = useState(false);
  const [editor, setEditor] = useState<EditorApi | null>(null);

  useEffect(() => {
    if (scene?.elements) return;
    let cancelled = false;
    mermaidToElements(source)
      .then((converted) => { if (cancelled) return; if (converted) setElements(converted); else setUnsupported(true); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [scene, source]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function save() {
    if (!editor) return;
    const drawn = JSON.parse(JSON.stringify(editor.getSceneElements())) as Elements;
    onSave({ elements: drawn });
  }

  return <div className="fixed inset-0 z-50 flex flex-col bg-background" role="dialog" aria-modal="true" aria-label={`Edit ${title} in Excalidraw`}>
    <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
      <div className="min-w-0 flex-1">
        <h2 className="truncate font-heading text-base font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">Drag, restyle and annotate. Changing the diagram by voice later starts a fresh drawing from its Mermaid.</p>
      </div>
      <Button size="sm" variant="outline" onClick={onClose}>Cancel</Button>
      <Button size="sm" onClick={save} disabled={!editor || !elements}>Save drawing</Button>
    </div>
    <div className="relative min-h-0 flex-1">
      {unsupported && <p className="p-6 text-sm text-muted-foreground">This diagram type can’t be edited as a drawing yet. Flowcharts, sequence and class diagrams can. Edit its Mermaid source instead.</p>}
      {failed && <p className="p-6 text-sm text-destructive">This diagram has a syntax error, so it can’t be opened as a drawing. Fix its Mermaid source first.</p>}
      {elements && <div className="absolute inset-0">
        <Excalidraw
          excalidrawAPI={(api) => setEditor(api as unknown as EditorApi)}
          initialData={{ elements: elements as never, appState: { viewBackgroundColor: "#ffffff" }, scrollToContent: true }}
          UIOptions={{ canvasActions: { loadScene: false, saveToActiveFile: false, export: false, saveAsImage: true }, tools: { image: false } }}
        />
      </div>}
    </div>
  </div>;
}

/** Read-only picture of a saved drawing for the board card. */
export function DrawingPreview({ scene }: { scene: DiagramScene }) {
  const [svg, setSvg] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    import("@excalidraw/excalidraw")
      .then(({ exportToSvg }) => exportToSvg({
        elements: scene.elements as never, files: null,
        appState: { exportBackground: true, viewBackgroundColor: "#ffffff", exportPadding: 12 },
      }))
      .then((element) => { if (!cancelled) setSvg(element.outerHTML); })
      .catch(() => { if (!cancelled) setSvg(null); });
    return () => { cancelled = true; };
  }, [scene]);
  if (!svg) return <p className="text-xs text-muted-foreground">Drawing…</p>;
  return <div className="[&_svg]:h-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />;
}
