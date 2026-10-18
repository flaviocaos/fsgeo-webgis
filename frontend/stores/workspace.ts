"use client";
import { create } from "zustand";
import type { EditSession } from "@/lib/edit/session";
import type { Locale, MessageKey } from "@/lib/i18n";
import { translate } from "@/lib/i18n";
import type { Layer, LayerStyle, Project, ServiceLayer } from "@/lib/types";

export type MapTool = "pan" | "identify" | "select" | "select-box" | "measure-line" | "measure-area" | "coords";
export type EditTool = "draw" | "modify" | "move" | "select";

export type DialogState =
  | { tipo: "importar" } | { tipo: "nova-camada" } | { tipo: "servico" } | { tipo: "compartilhar" }
  | { tipo: "atalhos" } | { tipo: "sobre" } | { tipo: "crs-projeto" }
  | { tipo: "exportar"; camada: string } | { tipo: "propriedades"; camada: string; aba?: string }
  | { tipo: "atributos-nova"; geometria: GeoJSON.Geometry }
  | { tipo: "atributos-editar"; chave: string }
  | { tipo: "excluir-camada"; camada: string };

export interface Toast { id: number; tipo: "info" | "ok" | "erro"; texto: string }

export interface Snapping {
  ativo: boolean;
  tolerancia: number;     // pixels
  vertices: boolean;
  segmentos: boolean;
  outrasCamadas: boolean; // também encaixa nas camadas vetoriais visíveis
}

interface WorkspaceState {
  project: Project | null;
  layers: Layer[];                 // ordem de exibição: índice 0 = topo
  services: ServiceLayer[];
  basemap: string;
  activeLayerId: string | null;
  tool: MapTool;
  selection: Record<string, number[]>;
  // edição
  editLayerId: string | null;
  editSession: EditSession | null;
  editTool: EditTool;
  editTick: number;
  editSelected: string[];          // chaves de feições selecionadas na edição
  snapping: Snapping;
  // interface
  panels: { left: boolean; right: boolean; table: boolean };
  theme: "dark" | "light";
  locale: Locale;
  cursor: { lon: number; lat: number } | null;
  resolution: number;
  scale: number;
  showGraticule: boolean;
  toasts: Toast[];
  zoomRequest: { extent4326: [number, number, number, number]; at: number } | null;
  stateDirty: number;
  vista: { centro: [number, number]; zoom: number } | null;
  dialog: DialogState | null;
  toolboxTool: string | null;

  openDialog: (d: DialogState) => void;
  closeDialog: () => void;
  openTool: (id: string | null) => void;

  setVista: (v: { centro: [number, number]; zoom: number }) => void;
  setProject: (p: Project) => void;
  setLayers: (l: Layer[]) => void;
  upsertLayer: (l: Layer) => void;
  removeLayer: (id: string) => void;
  updateDisplay: (id: string, patch: Partial<NonNullable<Layer["exibicao"]>> & { estilo?: LayerStyle }) => void;
  moveLayer: (id: string, toIndex: number) => void;
  setServices: (s: ServiceLayer[]) => void;
  setBasemap: (b: string) => void;
  setActiveLayer: (id: string | null) => void;
  setTool: (t: MapTool) => void;
  setSelection: (layerId: string, fids: number[], mode?: "replace" | "add" | "toggle") => void;
  clearSelection: (layerId?: string) => void;
  startEdit: (layerId: string, session: EditSession) => void;
  stopEdit: () => void;
  setEditTool: (t: EditTool) => void;
  bumpEdit: () => void;
  setEditSelected: (keys: string[]) => void;
  setSnapping: (p: Partial<Snapping>) => void;
  togglePanel: (p: keyof WorkspaceState["panels"]) => void;
  setTheme: (t: "dark" | "light") => void;
  setLocale: (l: Locale) => void;
  setCursor: (c: { lon: number; lat: number } | null) => void;
  setView: (resolution: number, scale: number) => void;
  toggleGraticule: () => void;
  toast: (texto: string, tipo?: Toast["tipo"]) => void;
  dismiss: (id: number) => void;
  zoomTo: (extent: [number, number, number, number]) => void;
  t: (k: MessageKey) => string;
}

let toastSeq = 0;

function sortByPosition(layers: Layer[]): Layer[] {
  return [...layers].sort((a, b) => (b.exibicao?.posicao ?? 0) - (a.exibicao?.posicao ?? 0));
}

function renumber(layers: Layer[]): Layer[] {
  const n = layers.length;
  return layers.map((l, i) => ({ ...l, exibicao: { ...(l.exibicao ?? defaultDisplay()), posicao: n - 1 - i } }));
}

export const defaultDisplay = () => ({ posicao: 0, grupo: null, visivel: true, opacidade: 1, estilo: {} as LayerStyle });

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  project: null,
  layers: [],
  services: [],
  basemap: "osm-vetorial",
  activeLayerId: null,
  tool: "pan",
  selection: {},
  editLayerId: null,
  editSession: null,
  editTool: "modify",
  editTick: 0,
  editSelected: [],
  snapping: { ativo: true, tolerancia: 10, vertices: true, segmentos: true, outrasCamadas: true },
  panels: { left: true, right: true, table: false },
  theme: "dark",
  locale: "pt-BR",
  cursor: null,
  resolution: 1,
  scale: 0,
  showGraticule: false,
  toasts: [],
  zoomRequest: null,
  stateDirty: 0,
  vista: null,
  dialog: null,
  toolboxTool: null,

  openDialog: (d) => set({ dialog: d }),
  closeDialog: () => set({ dialog: null }),
  openTool: (id) => set((s) => ({ toolboxTool: id, panels: id ? { ...s.panels, right: true } : s.panels })),

  setVista: (v) => set((s) => ({ vista: v, stateDirty: s.stateDirty + 1 })),
  setProject: (p) => set({
    vista: p.estado?.vista ?? null,
    project: p,
    layers: sortByPosition(Array.isArray(p.camadas) ? p.camadas : []),
    services: p.estado?.servicos ?? [],
    basemap: p.estado?.mapa_base ?? "osm-vetorial",
  }),
  setLayers: (l) => set({ layers: sortByPosition(l) }),
  upsertLayer: (l) => set((s) => {
    const i = s.layers.findIndex((x) => x.id === l.id);
    if (i >= 0) {
      const copy = [...s.layers];
      copy[i] = { ...l, exibicao: s.layers[i].exibicao ?? l.exibicao };
      return { layers: copy };
    }
    return { layers: renumber([{ ...l, exibicao: l.exibicao ?? defaultDisplay() }, ...s.layers]) };
  }),
  removeLayer: (id) => set((s) => ({
    layers: s.layers.filter((l) => l.id !== id),
    activeLayerId: s.activeLayerId === id ? null : s.activeLayerId,
    selection: Object.fromEntries(Object.entries(s.selection).filter(([k]) => k !== id)),
  })),
  updateDisplay: (id, patch) => set((s) => ({
    layers: s.layers.map((l) => l.id === id ? {
      ...l, exibicao: { ...(l.exibicao ?? defaultDisplay()), ...patch,
        estilo: { ...(l.exibicao?.estilo ?? {}), ...(patch.estilo ?? {}) } },
    } : l),
    stateDirty: s.stateDirty + 1,
  })),
  moveLayer: (id, toIndex) => set((s) => {
    const from = s.layers.findIndex((l) => l.id === id);
    if (from < 0) return {};
    const copy = [...s.layers];
    const [item] = copy.splice(from, 1);
    copy.splice(Math.max(0, Math.min(toIndex, copy.length)), 0, item);
    return { layers: renumber(copy), stateDirty: s.stateDirty + 1 };
  }),
  setServices: (sv) => set((s) => ({ services: sv, stateDirty: s.stateDirty + 1 })),
  setBasemap: (b) => set((s) => ({ basemap: b, stateDirty: s.stateDirty + 1 })),
  setActiveLayer: (id) => set({ activeLayerId: id }),
  setTool: (t) => set({ tool: t }),
  setSelection: (layerId, fids, mode = "replace") => set((s) => {
    const cur = new Set(s.selection[layerId] ?? []);
    let next: number[];
    if (mode === "replace") next = fids;
    else if (mode === "add") next = [...new Set([...cur, ...fids])];
    else {
      for (const f of fids) cur.has(f) ? cur.delete(f) : cur.add(f);
      next = [...cur];
    }
    return { selection: { ...s.selection, [layerId]: next } };
  }),
  clearSelection: (layerId) => set((s) => ({
    selection: layerId ? { ...s.selection, [layerId]: [] } : {},
  })),
  startEdit: (layerId, session) => set({ editLayerId: layerId, editSession: session, editTick: 0, editSelected: [],
    activeLayerId: layerId, editTool: "modify", tool: "pan" }),
  stopEdit: () => set({ editLayerId: null, editSession: null, editSelected: [] }),
  setEditTool: (t) => set({ editTool: t, editSelected: t === "draw" ? [] : get().editSelected }),
  bumpEdit: () => set((s) => ({ editTick: s.editTick + 1 })),
  setEditSelected: (keys) => set({ editSelected: keys }),
  setSnapping: (p) => set((s) => ({ snapping: { ...s.snapping, ...p } })),
  togglePanel: (p) => set((s) => ({ panels: { ...s.panels, [p]: !s.panels[p] } })),
  setTheme: (t) => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("webgis.tema", t); } catch {}
    set({ theme: t });
  },
  setLocale: (l) => {
    try { localStorage.setItem("webgis.idioma", l); } catch {}
    set({ locale: l });
  },
  setCursor: (c) => set({ cursor: c }),
  setView: (resolution, scale) => set({ resolution, scale }),
  toggleGraticule: () => set((s) => ({ showGraticule: !s.showGraticule })),
  toast: (texto, tipo = "info") => {
    const id = ++toastSeq;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, texto, tipo }] }));
    setTimeout(() => get().dismiss(id), tipo === "erro" ? 9000 : 4500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  zoomTo: (extent) => set({ zoomRequest: { extent4326: extent, at: Date.now() } }),
  t: (k) => translate(get().locale, k),
}));

export const canEdit = (p: Project | null) => !!p && p.papel !== "viewer";
