"use client";
import {
  Crosshair, Hand, Info, Magnet, MousePointer2, Move, PenLine, PenTool, Redo2, Ruler, Save, Spline, SquareDashed,
  Table2, Trash2, Undo2, Upload, X, Square,
} from "lucide-react";
import { useState } from "react";
import { deleteSelected, discardEdits, redo, saveEdits, startEditing, stopEditing, undo } from "@/lib/edit/actions";
import { canEdit, useWorkspace } from "@/stores/workspace";
import { Button, Dialog, IconButton } from "./ui";

const sep = <div className="mx-1 h-5 w-px bg-line" />;

export function ToolStrip() {
  const ws = useWorkspace();
  const editing = !!ws.editLayerId;
  const editLayer = ws.layers.find((l) => l.id === ws.editLayerId);
  const active = ws.layers.find((l) => l.id === ws.activeLayerId);
  const pending = ws.editSession ? ws.editSession.diff() : null;
  const pendingCount = pending ? pending.criar.length + pending.atualizar.length + pending.excluir.length : 0;
  const [invalid, setInvalid] = useState<{ ref: string; erro: string }[] | null>(null);
  void ws.editTick; // re-renderiza contadores a cada comando

  const save = async (fix = false) => {
    const r = await saveEdits(fix);
    setInvalid(r.invalid ?? null);
  };

  return (
    <div className="flex h-9 items-center gap-0.5 border-b border-line bg-panel px-2" role="toolbar" aria-label="Ferramentas do mapa">
      <IconButton label="Importar dados (Ctrl+I)" disabled={!canEdit(ws.project)} onClick={() => ws.openDialog({ tipo: "importar" })}><Upload size={16} /></IconButton>
      <IconButton label="Tabela de atributos (Ctrl+T)" active={ws.panels.table} onClick={() => ws.togglePanel("table")}><Table2 size={16} /></IconButton>
      {sep}
      <IconButton label="Navegar" active={ws.tool === "pan" && !editing} disabled={editing} onClick={() => ws.setTool("pan")}><Hand size={16} /></IconButton>
      <IconButton label="Identificar feições (I)" active={ws.tool === "identify"} disabled={editing} onClick={() => ws.setTool("identify")}><Info size={16} /></IconButton>
      <IconButton label="Selecionar por clique na camada ativa (S); Shift alterna" active={ws.tool === "select"} disabled={editing} onClick={() => ws.setTool("select")}><MousePointer2 size={16} /></IconButton>
      <IconButton label="Selecionar por retângulo na camada ativa" active={ws.tool === "select-box"} disabled={editing} onClick={() => ws.setTool("select-box")}><SquareDashed size={16} /></IconButton>
      <IconButton label="Medir distância (M)" active={ws.tool === "measure-line"} disabled={editing} onClick={() => ws.setTool("measure-line")}><Ruler size={16} /></IconButton>
      <IconButton label="Medir área" active={ws.tool === "measure-area"} disabled={editing} onClick={() => ws.setTool("measure-area")}><Square size={16} /></IconButton>
      <IconButton label="Consultar coordenadas (C)" active={ws.tool === "coords"} disabled={editing} onClick={() => ws.setTool("coords")}><Crosshair size={16} /></IconButton>
      {sep}
      {!editing ? (
        <Button variant="ghost" disabled={!active || active.tipo !== "vetorial" || !canEdit(ws.project)}
          title={!active ? "Escolha uma camada vetorial no painel de camadas" : undefined}
          onClick={() => active && startEditing(active.id)}>
          <PenLine size={15} className="text-edit" />Editar {active?.tipo === "vetorial" ? <strong className="max-w-40 truncate">{active.nome}</strong> : "camada"}
        </Button>
      ) : (
        <div className="flex items-center gap-0.5 rounded bg-edit/10 px-1 ring-1 ring-edit/40">
          <span className="px-1.5 text-[12px] text-edit">Editando <strong>{editLayer?.nome}</strong></span>
          <IconButton tone="edit" label={`Adicionar ${geomLabel(editLayer?.geometria)}`} active={ws.editTool === "draw"} onClick={() => ws.setEditTool("draw")}><PenTool size={16} /></IconButton>
          <IconButton tone="edit" label="Editar vértices: arraste para mover, clique na aresta para inserir, Alt+clique para remover" active={ws.editTool === "modify"} onClick={() => ws.setEditTool("modify")}><Spline size={16} /></IconButton>
          <IconButton tone="edit" label="Mover feições: clique para selecionar e arraste" active={ws.editTool === "move"} onClick={() => ws.setEditTool("move")}><Move size={16} /></IconButton>
          <IconButton tone="edit" label="Selecionar feições (Shift adiciona)" active={ws.editTool === "select"} onClick={() => ws.setEditTool("select")}><MousePointer2 size={16} /></IconButton>
          <IconButton tone="edit" label="Excluir selecionadas (Del)" disabled={!ws.editSelected.length} onClick={deleteSelected}><Trash2 size={16} /></IconButton>
          <IconButton tone="edit" label={`Desfazer${ws.editSession?.undoLabel() ? `: ${ws.editSession.undoLabel()}` : ""} (Ctrl+Z)`} disabled={!ws.editSession?.canUndo()} onClick={undo}><Undo2 size={16} /></IconButton>
          <IconButton tone="edit" label="Refazer (Ctrl+Shift+Z)" disabled={!ws.editSession?.canRedo()} onClick={redo}><Redo2 size={16} /></IconButton>
          <IconButton tone="edit" label={`Snapping ${ws.snapping.ativo ? "ligado" : "desligado"} (tolerância ${ws.snapping.tolerancia} px)`} active={ws.snapping.ativo}
            onClick={() => ws.setSnapping({ ativo: !ws.snapping.ativo })}><Magnet size={16} /></IconButton>
          <SnapOptions />
          <span className="mx-1 tabular text-[12px] text-muted" aria-live="polite">{pendingCount} {pendingCount === 1 ? "alteração pendente" : "alterações pendentes"}</span>
          <Button variant="edit" disabled={!pendingCount} onClick={() => save()}><Save size={14} />Salvar</Button>
          <Button variant="ghost" disabled={!pendingCount} onClick={discardEdits}>Descartar</Button>
          <IconButton label="Parar edição" onClick={() => stopEditing()}><X size={16} /></IconButton>
        </div>
      )}
      {invalid && (
        <Dialog title="Geometrias inválidas" onClose={() => setInvalid(null)} footer={<>
          <Button onClick={() => setInvalid(null)}>Voltar e corrigir à mão</Button>
          <Button variant="edit" onClick={() => save(true)}>Corrigir automaticamente e salvar</Button>
        </>}>
          <p className="mb-2">Nada foi salvo. Estas geometrias são inválidas:</p>
          <ul className="mb-2 list-disc pl-5">{invalid.slice(0, 8).map((d) => <li key={d.ref}>{d.erro}</li>)}</ul>
          <p className="text-muted">A correção automática (ST_MakeValid) mantém o tipo da camada; por exemplo, um polígono que se cruza vira um multipolígono com duas partes.</p>
        </Dialog>
      )}
    </div>
  );
}

function SnapOptions() {
  const sn = useWorkspace((s) => s.snapping);
  const set = useWorkspace((s) => s.setSnapping);
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button className="px-1 text-[11px] text-muted hover:text-text" aria-expanded={open} onClick={() => setOpen(!open)}>opções</button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-64 rounded border border-line bg-panel p-3 shadow-xl" onMouseLeave={() => setOpen(false)}>
          <label className="mb-2 flex items-center gap-2"><input type="checkbox" checked={sn.vertices} onChange={(e) => set({ vertices: e.target.checked })} />Vértices</label>
          <label className="mb-2 flex items-center gap-2"><input type="checkbox" checked={sn.segmentos} onChange={(e) => set({ segmentos: e.target.checked })} />Segmentos</label>
          <label className="mb-2 flex items-center gap-2"><input type="checkbox" checked={sn.outrasCamadas} onChange={(e) => set({ outrasCamadas: e.target.checked })} />Outras camadas visíveis</label>
          <label className="flex items-center gap-2">Tolerância
            <input type="number" min={1} max={50} className="w-16" value={sn.tolerancia} onChange={(e) => set({ tolerancia: Math.max(1, Math.min(50, Number(e.target.value) || 10)) })} /> px
          </label>
        </div>
      )}
    </div>
  );
}

function geomLabel(g: string | null | undefined) {
  if (!g) return "feição";
  if (g.includes("Point")) return "ponto";
  if (g.includes("Line")) return "linha";
  return "polígono";
}
