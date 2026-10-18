"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Api } from "@/lib/api";
import { config } from "@/lib/config";
import { deleteSelected, discardEdits, redo, saveEdits, startEditing, stopEditing, undo } from "@/lib/edit/actions";
import type { MessageKey } from "@/lib/i18n";
import type { Tool } from "@/lib/types";
import { canEdit, useWorkspace } from "@/stores/workspace";

interface Item {
  label: string;
  action?: () => void;
  shortcut?: string;
  disabled?: boolean;
  unavailable?: string;   // texto do motivo (ex.: "Fase 2")
  checked?: boolean;
  separator?: boolean;
}

export function MenuBar({ onSaveProject, onZoomAll }: { onSaveProject: () => void; onZoomAll: () => void }) {
  const router = useRouter();
  const [open, setOpen] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const ws = useWorkspace();
  const { data: tools = [] } = useQuery({ queryKey: ["tools"], queryFn: Api.tools, staleTime: Infinity });
  const active = ws.layers.find((l) => l.id === ws.activeLayerId);
  const editable = canEdit(ws.project);
  const editing = !!ws.editLayerId;

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(null); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);

  const toolItems = (filter: (t: Tool) => boolean): Item[] => tools.filter(filter).map((t) => ({
    label: t.nome, action: () => ws.openTool(t.id),
    unavailable: t.status === "indisponivel" ? `Fase ${t.fase}` : undefined,
    disabled: t.status === "disponivel" && !editable,
  }));
  const phase2 = (label: string): Item => ({ label, unavailable: "Fase 2" });

  const menus: { key: MessageKey; items: Item[] }[] = [
    { key: "menu.projeto", items: [
      { label: "Salvar projeto", action: onSaveProject, disabled: !editable },
      { label: "Sistema de referência do projeto…", action: () => ws.openDialog({ tipo: "crs-projeto" }), disabled: !editable },
      { label: "Compartilhar…", action: () => ws.openDialog({ tipo: "compartilhar" }) },
      { separator: true, label: "" },
      { label: "Voltar aos projetos", action: () => router.push("/projetos") },
      phase2("Versões do projeto"),
    ] },
    { key: "menu.arquivo", items: [
      { label: "Importar dados…", shortcut: "Ctrl+I", action: () => ws.openDialog({ tipo: "importar" }), disabled: !editable },
      { label: "Exportar camada ativa…", action: () => active && ws.openDialog({ tipo: "exportar", camada: active.id }), disabled: !active },
      { label: "Adicionar serviço WMS, WMTS ou XYZ…", action: () => ws.openDialog({ tipo: "servico" }) },
      phase2("Conectar a PostGIS externo"),
      phase2("Exportar projeto"),
    ] },
    { key: "menu.editar", items: [
      editing
        ? { label: "Parar edição", action: () => stopEditing() }
        : { label: "Editar camada ativa", shortcut: "Ctrl+E", action: () => active && startEditing(active.id),
            disabled: !active || active.tipo !== "vetorial" || !editable },
      { label: `Desfazer${ws.editSession?.undoLabel() ? ` (${ws.editSession.undoLabel()})` : ""}`, shortcut: "Ctrl+Z", action: undo, disabled: !ws.editSession?.canUndo() },
      { label: "Refazer", shortcut: "Ctrl+Shift+Z", action: redo, disabled: !ws.editSession?.canRedo() },
      { label: "Salvar edições", shortcut: "Ctrl+S", action: () => saveEdits(), disabled: !editing },
      { label: "Descartar edições", action: discardEdits, disabled: !editing },
      { label: "Excluir feições selecionadas", shortcut: "Del", action: deleteSelected, disabled: !ws.editSelected.length },
      { separator: true, label: "" },
      phase2("Rotacionar feição"), phase2("Escalar feição"), phase2("Dividir linhas e polígonos"),
      phase2("Mesclar polígonos"), phase2("Recortar polígono"), phase2("Criar buraco em polígono"),
    ] },
    { key: "menu.visualizar", items: [
      { label: "Painel de camadas", checked: ws.panels.left, action: () => ws.togglePanel("left") },
      { label: "Caixa de ferramentas", checked: ws.panels.right, action: () => ws.togglePanel("right") },
      { label: "Tabela de atributos", shortcut: "Ctrl+T", checked: ws.panels.table, action: () => ws.togglePanel("table") },
      { label: "Grade de coordenadas", checked: ws.showGraticule, action: ws.toggleGraticule },
      { separator: true, label: "" },
      { label: "Mapa-base: OpenStreetMap vetorial (MapLibre)", checked: ws.basemap === "osm-vetorial", action: () => ws.setBasemap("osm-vetorial") },
      { label: "Mapa-base: OpenStreetMap raster", checked: ws.basemap === "osm", action: () => ws.setBasemap("osm") },
      { label: "Mapa-base: satélite", checked: ws.basemap === "satelite", action: () => ws.setBasemap("satelite"),
        unavailable: config.satelliteUrl ? undefined : "configure o provedor" },
      { label: "Sem mapa-base", checked: ws.basemap === "nenhum", action: () => ws.setBasemap("nenhum") },
      { separator: true, label: "" },
      { label: "Enquadrar todas as camadas", action: onZoomAll },
    ] },
    { key: "menu.camadas", items: [
      { label: "Nova camada vetorial…", action: () => ws.openDialog({ tipo: "nova-camada" }), disabled: !editable },
      { label: "Importar dados…", action: () => ws.openDialog({ tipo: "importar" }), disabled: !editable },
      { label: "Propriedades da camada ativa…", action: () => active && ws.openDialog({ tipo: "propriedades", camada: active.id }), disabled: !active },
      { label: "Enquadrar camada ativa", action: () => active?.bbox && ws.zoomTo(active.bbox), disabled: !active?.bbox },
      { label: "Remover camada ativa…", action: () => active && ws.openDialog({ tipo: "excluir-camada", camada: active.id }), disabled: !active || !editable },
      phase2("Simbologia categorizada e graduada"), phase2("Rótulos"),
    ] },
    { key: "menu.vetor", items: toolItems((t) => t.grupo.startsWith("Vetor")) },
    { key: "menu.raster", items: toolItems((t) => t.grupo.startsWith("Raster")) },
    { key: "menu.geoprocessamento", items: [
      { label: "Abrir caixa de ferramentas", action: () => { ws.openTool(null); if (!ws.panels.right) ws.togglePanel("right"); } },
      { separator: true, label: "" },
      ...toolItems((t) => ["vector.buffer", "vector.clip", "vector.intersection", "vector.dissolve", "vector.difference"].includes(t.id)),
    ] },
    { key: "menu.analise", items: toolItems((t) => t.grupo.startsWith("Análise") || t.grupo === "Redes") },
    { key: "menu.ferramentas", items: [
      { label: "Identificar feições", shortcut: "I", action: () => ws.setTool("identify"), checked: ws.tool === "identify", disabled: editing },
      { label: "Selecionar por clique", shortcut: "S", action: () => ws.setTool("select"), checked: ws.tool === "select", disabled: editing },
      { label: "Selecionar por retângulo", action: () => ws.setTool("select-box"), checked: ws.tool === "select-box", disabled: editing },
      { label: "Medir distância", shortcut: "M", action: () => ws.setTool("measure-line"), checked: ws.tool === "measure-line", disabled: editing },
      { label: "Medir área", action: () => ws.setTool("measure-area"), checked: ws.tool === "measure-area", disabled: editing },
      { label: "Consultar coordenadas", shortcut: "C", action: () => ws.setTool("coords"), checked: ws.tool === "coords", disabled: editing },
      phase2("Layout de impressão"),
    ] },
    { key: "menu.configuracoes", items: [
      { label: "Tema escuro", checked: ws.theme === "dark", action: () => ws.setTheme("dark") },
      { label: "Tema claro", checked: ws.theme === "light", action: () => ws.setTheme("light") },
      { separator: true, label: "" },
      { label: "Português (Brasil)", checked: ws.locale === "pt-BR", action: () => ws.setLocale("pt-BR") },
      { label: "English (parcial)", checked: ws.locale === "en", action: () => ws.setLocale("en") },
      { label: "Español (parcial)", checked: ws.locale === "es", action: () => ws.setLocale("es") },
      { separator: true, label: "" },
      { label: "Snapping ativo", checked: ws.snapping.ativo, action: () => ws.setSnapping({ ativo: !ws.snapping.ativo }) },
    ] },
    { key: "menu.ajuda", items: [
      { label: "Atalhos de teclado", shortcut: "?", action: () => ws.openDialog({ tipo: "atalhos" }) },
      { label: "Sobre esta versão", action: () => ws.openDialog({ tipo: "sobre" }) },
    ] },
  ];

  return (
    <div ref={ref} role="menubar" className="relative z-40 flex h-7 items-center gap-px whitespace-nowrap border-b border-line bg-panel px-1 text-[12.5px]">
      {menus.map((m) => (
        <div key={m.key} className="relative">
          <button role="menuitem" aria-haspopup="menu" aria-expanded={open === m.key}
            className={clsx("rounded px-2 py-0.5 hover:bg-panel-2 max-xl:px-1.5", open === m.key && "bg-panel-2")}
            onClick={() => setOpen(open === m.key ? null : m.key)}
            onMouseEnter={() => open && setOpen(m.key)}>
            {ws.t(m.key)}
          </button>
          {open === m.key && (
            <div role="menu" className="absolute left-0 top-full z-40 mt-0.5 min-w-64 rounded border border-line bg-panel py-1 shadow-2xl">
              {m.items.length === 0 && <div className="px-3 py-1 text-muted">Carregando…</div>}
              {m.items.map((it, i) => it.separator ? <div key={i} className="my-1 border-t border-line" /> : (
                <button key={i} role="menuitem" disabled={it.disabled || !!it.unavailable}
                  className="flex w-full items-center gap-2 px-3 py-1 text-left hover:bg-panel-2 disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:bg-transparent"
                  onClick={() => { setOpen(null); it.action?.(); }}>
                  <span className="w-3.5">{it.checked && <Check size={13} className="text-select" />}</span>
                  <span className="flex-1">{it.label}</span>
                  {it.unavailable && <span className="rounded border border-line px-1 text-[10.5px] text-muted">{ws.t("indisponivel")} · {it.unavailable}</span>}
                  {it.shortcut && !it.unavailable && <span className="text-[11px] text-muted">{it.shortcut}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="flex-1" />
      <span className="hidden truncate px-2 text-muted xl:inline">{ws.project?.nome}</span>
    </div>
  );
}
