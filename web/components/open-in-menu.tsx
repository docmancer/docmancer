"use client";

import { ChevronDown, FileText, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiMutation, type JsonMap } from "@/lib/api";

type Editor = { id: string; label: string };

function editorRows(value: unknown): Editor[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const row = item as JsonMap;
    return row.id && row.label ? [{ id: String(row.id), label: String(row.label) }] : [];
  });
}

function editorMark(editor: Editor): string {
  const marks: Record<string, string> = {
    vscode: "⌁",
    cursor: "◈",
    sublime: "S",
    zed: "Z",
    textmate: "T",
    obsidian: "◇",
    typora: "T",
    default: "↗",
  };
  return marks[editor.id] ?? editor.label.slice(0, 1).toUpperCase();
}

export function OpenInMenu({ path }: { path: string }) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [editors, setEditors] = useState<Editor[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    function close(event: MouseEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    setError("");
    if (editors.length) return;
    setBusy("loading");
    try {
      const response = await apiGet(`/api/v1/editors?path=${encodeURIComponent(path)}`);
      setEditors(editorRows(response.items));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  async function launch(editor: Editor) {
    setBusy(editor.id);
    setError("");
    try {
      await apiMutation("/api/v1/editor/open", { path, editor: editor.id });
      setOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  return <div className="open-in" ref={root}>
    <button className="secondary open-in-trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => void toggle()}>
      Open in <ChevronDown size={13}/>
    </button>
    {open && <div className="editor-menu" role="menu">
      <div className="editor-menu-file"><FileText size={14}/><span title={path}>{path.split("/").pop()}</span></div>
      {busy === "loading" && <div className="editor-menu-state"><LoaderCircle className="spin" size={14}/>Finding installed editors</div>}
      {!busy && editors.map((editor) => <button role="menuitem" key={editor.id} disabled={Boolean(busy)} onClick={() => void launch(editor)}>
        <span className={`editor-mark editor-${editor.id}`}>{editorMark(editor)}</span>
        <span>{editor.label}</span>
        {busy === editor.id && <LoaderCircle className="spin" size={13}/>}
      </button>)}
      {error && <p className="editor-menu-error">{error}</p>}
    </div>}
  </div>;
}
