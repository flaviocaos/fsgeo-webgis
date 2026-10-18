"use client";
import clsx from "clsx";
import {
  Download, Eye, EyeOff, Grid3x3, Image as ImageIcon, MoreHorizontal, PenLine, Plus, Settings2, Spline, Square, Table2,
  Trash2, Circle, ZoomIn, Globe, Upload,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Api } from "@/lib/api";
import { startEditing } from "@/lib/edit/actions";
import { colorForId } from "@/lib/map/styles";
import type { Layer } from "@/lib/types";
import { canEdit, useWorkspace } from "@/stores/workspace";
import { Empty, IconButton } from "./ui";

function GeomIcon({ l }: { l: Layer }) {
  const color = l.exibicao?.estilo?.cor || colorForId(l.id);
  if (l.tipo === "raster") return <ImageIcon size={14} className="text-muted" />;
  if (l.geometria?.includes("Point")) return <Circle size={12} fill={color} stroke="none" />;
  if (l.geometria?.includes("Line")) return <Spline size={14} style={{ color }} />;
  return <Square size={13} style={{ color, fill: `${color}55` }} />;
}

export function LayerPanel() {
  const ws = useWorkspace();
  const [dragId, setDragId] = useState<string | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const editable = canEdit(ws.project);

  let lastGroup: string | null | undefined;
  return (
    <aside className="flex h-full flex-col border-r border-line bg-panel" aria-label="Camadas">
      <div className="flex h-8 shrink-0 items-center justify-between border-b border-line pl-3 pr-1">
        <h2 className="font-semibold">{ws.t("painel.camadas")}</h2>
        <div className="flex">
          <IconButton label="Importar dados" disabled={!editable} onClick={() => ws.openDialog({ tipo: "importar" })}><Upload size={15} /></IconButton>
          <IconButton label="Nova camada vetorial" disabled={!editable} onClick={() => ws.openDialog({ tipo: "nova-camada" })}><Plus size={15} /></IconButton>
          <IconButton label="Adicionar serviço WMS/WMTS/XYZ" onClick={() => ws.openDialog({ tipo: "servico" })}><Globe size={15} /></IconButton>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto py-1" role="tree" aria-label="Ordem de desenho: o primeiro item fica por cima">
        {ws.layers.length === 0 && <Empty>Nenhuma camada. Importe um Shapefile, GeoPackage, GeoJSON ou GeoTIFF, ou crie uma camada vazia para desenhar.</Empty>}
        {ws.layers.map((l, idx) => {
          const g = l.exibicao?.grupo ?? null;
          const header = g && g !== lastGroup ? <GroupHeader key={`g-${g}-${idx}`} name={g} /> : null;
          lastGroup = g;
          const visible = l.exibicao?.visivel !== false;
          const isActive = ws.activeLayerId === l.id;
          const isEditing = ws.editLayerId === l.id;
          const selCount = ws.selection[l.id]?.length ?? 0;
          return (
            <div key={l.id}>
              {header}
              <div role="treeitem" aria-selected={isActive}
                draggable={editable && renaming !== l.id}
                onDragStart={(e) => { setDragId(l.id); e.dataTransfer.effectAllowed = "move"; }}
                onDragOver={(e) => { e.preventDefault(); setOverIdx(idx); }}
                onDragEnd={() => { setDragId(null); setOverIdx(null); }}
                onDrop={(e) => { e.preventDefault(); if (dragId) ws.moveLayer(dragId, idx); setDragId(null); setOverIdx(null); }}
                onClick={() => ws.setActiveLayer(l.id)}
                onDoubleClick={() => ws.openDialog({ tipo: "propriedades", camada: l.id })}
                className={clsx("group relative flex h-7 cursor-default items-center gap-1.5 pr-1 select-none",
                  g ? "pl-5" : "pl-2",
                  isActive ? "bg-select/12" : "hover:bg-panel-2",
                  isEditing && "bg-edit/12",
                  overIdx === idx && dragId && dragId !== l.id && "shadow-[inset_0_2px_0_var(--select)]")}>
                <button aria-label={visible ? "Ocultar camada" : "Mostrar camada"} className="text-muted hover:text-text"
                  onClick={(e) => { e.stopPropagation(); ws.updateDisplay(l.id, { visivel: !visible }); }}>
                  {visible ? <Eye size={14} /> : <EyeOff size={14} />}
                </button>
                <span className="w-4 shrink-0 grid place-items-center"><GeomIcon l={l} /></span>
                {renaming === l.id ? (
                  <RenameInput layer={l} onDone={() => setRenaming(null)} />
                ) : (
                  <span className={clsx("min-w-0 flex-1 truncate", !visible && "text-muted", isActive && "font-medium")}
                    title={`${l.nome} · ${l.crs ?? "CRS indefinido"}`}>{l.nome}</span>
                )}
                {isEditing && <PenLine size={13} className="shrink-0 text-edit" aria-label="Em edição" />}
                {!l.crs && l.tipo === "vetorial" && <span className="shrink-0 text-[10.5px] text-danger" title="Sistema de referência indefinido">sem CRS</span>}
                {selCount > 0 && <span className="shrink-0 rounded bg-select/20 px-1 text-[10.5px] text-select tabular" title="Feições selecionadas">{selCount}</span>}
                {l.tipo === "vetorial" && <span className="shrink-0 text-[10.5px] text-muted tabular">{l.feicoes.toLocaleString("pt-BR")}</span>}
                <button aria-label={`Ações da camada ${l.nome}`} className="shrink-0 rounded p-0.5 text-muted opacity-60 hover:bg-panel hover:text-text group-hover:opacity-100"
                  onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === l.id ? null : l.id); }}>
                  <MoreHorizontal size={15} />
                </button>
                {menuFor === l.id && <LayerMenu layer={l} onClose={() => setMenuFor(null)} onRename={() => setRenaming(l.id)} />}
              </div>
            </div>
          );
        })}
        {ws.services.length > 0 && (
          <div className="mt-2 border-t border-line pt-1">
            <p className="px-3 py-1 text-[11.5px] text-muted">Serviços externos</p>
            {ws.services.map((sv) => (
              <div key={sv.id} className="group flex h-7 items-center gap-1.5 px-2 hover:bg-panel-2">
                <button aria-label={sv.visivel ? "Ocultar serviço" : "Mostrar serviço"} className="text-muted hover:text-text"
                  onClick={() => ws.setServices(ws.services.map((x) => x.id === sv.id ? { ...x, visivel: !x.visivel } : x))}>
                  {sv.visivel ? <Eye size={14} /> : <EyeOff size={14} />}
                </button>
                <Grid3x3 size={13} className="text-muted" />
                <span className="flex-1 truncate" title={sv.url}>{sv.nome}</span>
                <span className="text-[10.5px] uppercase text-muted">{sv.tipo}</span>
                <input type="range" min={0} max={1} step={0.05} value={sv.opacidade} aria-label="Opacidade do serviço" className="w-14"
                  onChange={(e) => ws.setServices(ws.services.map((x) => x.id === sv.id ? { ...x, opacidade: Number(e.target.value) } : x))} />
                <IconButton label="Remover serviço" disabled={!editable} onClick={() => ws.setServices(ws.services.filter((x) => x.id !== sv.id))}><Trash2 size={13} /></IconButton>
              </div>
            ))}
          </div>
        )}
      </div>
      <label className="flex shrink-0 items-center gap-2 border-t border-line px-3 py-2 text-[12px]">
        <span className="text-muted">Mapa-base</span>
        <select className="flex-1" value={ws.basemap} onChange={(e) => ws.setBasemap(e.target.value)}>
          <option value="osm-vetorial">OpenStreetMap vetorial</option>
          <option value="osm">OpenStreetMap raster</option>
          <option value="satelite">Satélite</option>
          <option value="nenhum">Nenhum</option>
        </select>
      </label>
    </aside>
  );
}

function GroupHeader({ name }: { name: string }) {
  const ws = useWorkspace();
  const members = ws.layers.filter((l) => l.exibicao?.grupo === name);
  const allVisible = members.every((l) => l.exibicao?.visivel !== false);
  return (
    <div className="flex h-6 items-center gap-1.5 px-2 text-[12px] font-semibold text-muted">
      <button aria-label={allVisible ? "Ocultar grupo" : "Mostrar grupo"} className="hover:text-text"
        onClick={() => members.forEach((l) => ws.updateDisplay(l.id, { visivel: !allVisible }))}>
        {allVisible ? <Eye size={13} /> : <EyeOff size={13} />}
      </button>
      {name}
    </div>
  );
}

function RenameInput({ layer, onDone }: { layer: Layer; onDone: () => void }) {
  const [v, setV] = useState(layer.nome);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.select(); }, []);
  const commit = async () => {
    const name = v.trim();
    if (name && name !== layer.nome) {
      try {
        useWorkspace.getState().upsertLayer(await Api.renameLayer(layer.id, name));
      } catch (e) { useWorkspace.getState().toast((e as Error).message, "erro"); }
    }
    onDone();
  };
  return <input ref={ref} className="h-6 min-w-0 flex-1" value={v} onChange={(e) => setV(e.target.value)} aria-label="Novo nome da camada"
    onClick={(e) => e.stopPropagation()} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") onDone(); }} />;
}

function LayerMenu({ layer, onClose, onRename }: { layer: Layer; onClose: () => void; onRename: () => void }) {
  const ws = useWorkspace();
  const ref = useRef<HTMLDivElement>(null);
  const editable = canEdit(ws.project);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    setTimeout(() => document.addEventListener("mousedown", h));
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);
  const item = (icon: React.ReactNode, label: string, fn: () => void, disabled = false) => (
    <button role="menuitem" disabled={disabled} className="flex w-full items-center gap-2 px-3 py-1 text-left hover:bg-panel-2 disabled:opacity-45"
      onClick={(e) => { e.stopPropagation(); onClose(); fn(); }}>{icon}{label}</button>
  );
  return (
    <div ref={ref} role="menu" className="absolute right-1 top-full z-30 w-56 rounded border border-line bg-panel py-1 shadow-2xl">
      {item(<ZoomIn size={14} />, "Enquadrar camada", () => layer.bbox && ws.zoomTo(layer.bbox), !layer.bbox)}
      {layer.tipo === "vetorial" && item(<Table2 size={14} />, "Abrir tabela de atributos", () => { ws.setActiveLayer(layer.id); if (!ws.panels.table) ws.togglePanel("table"); })}
      {layer.tipo === "vetorial" && item(<PenLine size={14} />, "Editar camada", () => startEditing(layer.id), !editable || !layer.crs)}
      {item(<Settings2 size={14} />, "Propriedades e estilo", () => ws.openDialog({ tipo: "propriedades", camada: layer.id }))}
      {item(<Download size={14} />, "Exportar…", () => ws.openDialog({ tipo: "exportar", camada: layer.id }))}
      {item(<PenLine size={14} />, "Renomear", onRename, !editable)}
      <div className="my-1 border-t border-line" />
      {item(<Trash2 size={14} />, "Remover camada…", () => ws.openDialog({ tipo: "excluir-camada", camada: layer.id }), !editable || ws.editLayerId === layer.id)}
    </div>
  );
}
