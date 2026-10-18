"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Api, ApiError } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { deleteSelected, redo, saveEdits, startEditing, stopEditing, undo } from "@/lib/edit/actions";
import type { Job } from "@/lib/types";
import { TERMINAL } from "@/lib/types";
import { canEdit, useWorkspace } from "@/stores/workspace";
import { AttributeTable } from "./AttributeTable";
import { Dialogs } from "./Dialogs";
import { LayerPanel } from "./LayerPanel";
import MapView from "./MapView";
import { MenuBar } from "./MenuBar";
import { StatusBar } from "./StatusBar";
import { ToolStrip } from "./ToolStrip";
import { Toolbox } from "./Toolbox";

export default function Workspace({ projectId }: { projectId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const ws = useWorkspace();
  const [authed, setAuthed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [tableHeight, setTableHeight] = useState(260);

  useEffect(() => { getToken().then((t) => (t ? setAuthed(true) : router.replace("/login"))); }, [router]);

  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => Api.project(projectId), enabled: authed, staleTime: Infinity });
  useEffect(() => {
    if (project.data && !loaded) {
      useWorkspace.setState({ editLayerId: null, editSession: null, selection: {}, activeLayerId: null, tool: "pan", dialog: null, toolboxTool: null });
      ws.setProject(project.data);
      setLoaded(true);
    }
  }, [project.data, loaded, ws]);

  // ---------------------------------------------------------------- processamentos
  const jobs = useQuery({
    queryKey: ["jobs", projectId],
    queryFn: () => Api.jobs(projectId),
    enabled: loaded,
    refetchInterval: (q) => ((q.state.data as Job[] | undefined)?.some((j) => !TERMINAL.includes(j.status)) ? 1200 : 15000),
  });
  const seen = useRef<Record<string, Job["status"]>>({});
  useEffect(() => {
    if (!jobs.data) return;
    let refresh = false;
    for (const j of jobs.data) {
      const prev = seen.current[j.id];
      if (prev && !TERMINAL.includes(prev) && TERMINAL.includes(j.status)) {
        if (j.status === "succeeded") {
          if (j.tipo !== "export") refresh = true;
          ws.toast(j.tipo === "import" ? "Importação concluída." : j.tipo === "export" ? "Exportação pronta para download em Processamentos." : "Processamento concluído: camada criada.", "ok");
        } else if (j.status === "failed") ws.toast(j.erro ?? "Processamento falhou.", "erro");
      }
      seen.current[j.id] = j.status;
    }
    if (refresh) {
      Api.project(projectId).then((p) => {
        const known = new Set(useWorkspace.getState().layers.map((l) => l.id));
        for (const l of (p.camadas as any[]) ?? []) if (!known.has(l.id)) useWorkspace.getState().upsertLayer(l);
      });
    }
  }, [jobs.data, projectId, ws]);
  const onJobStarted = useCallback((j: Job) => {
    seen.current[j.id] = j.status;
    qc.invalidateQueries({ queryKey: ["jobs", projectId] });
    if (!useWorkspace.getState().panels.right) useWorkspace.getState().togglePanel("right");
  }, [qc, projectId]);
  const running = jobs.data?.filter((j) => !TERMINAL.includes(j.status)).length ?? 0;

  // ---------------------------------------------------------------- salvamento automático do estado
  const saveState = useCallback(async () => {
    const s = useWorkspace.getState();
    if (!s.project || !canEdit(s.project)) return;
    try {
      await Api.saveLayersState(s.project.id, s.layers.map((l) => ({
        camada_id: l.id, posicao: l.exibicao?.posicao ?? 0, grupo: l.exibicao?.grupo ?? null,
        visivel: l.exibicao?.visivel ?? true, opacidade: l.exibicao?.opacidade ?? 1, estilo: l.exibicao?.estilo ?? {},
      })));
      await Api.patchProject(s.project.id, { estado: { ...(s.project.estado ?? {}), vista: s.vista ?? undefined, mapa_base: s.basemap, servicos: s.services } });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) s.toast(`Não foi possível salvar o estado do projeto: ${(e as Error).message}`, "erro");
    }
  }, []);
  useEffect(() => {
    if (!loaded || ws.stateDirty === 0) return;
    const t = setTimeout(saveState, 1500);
    return () => clearTimeout(t);
  }, [ws.stateDirty, loaded, saveState]);

  // Aviso ao fechar a aba com edições pendentes.
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (useWorkspace.getState().editSession?.pendingCount()) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, []);

  // ---------------------------------------------------------------- atalhos
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useWorkspace.getState();
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target as HTMLElement)?.isContentEditable;
      const mod = e.ctrlKey || e.metaKey;
      if (s.dialog) return;
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); if (s.editLayerId) saveEdits(); return; }
      if (mod && e.key.toLowerCase() === "i") { e.preventDefault(); if (canEdit(s.project)) s.openDialog({ tipo: "importar" }); return; }
      if (mod && e.key.toLowerCase() === "t") { e.preventDefault(); s.togglePanel("table"); return; }
      if (mod && e.key.toLowerCase() === "e") {
        e.preventDefault();
        if (s.editLayerId) stopEditing(); else if (s.activeLayerId) startEditing(s.activeLayerId);
        return;
      }
      if (typing) return;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
      if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
      if (mod) return;
      if (e.key === "Escape") {
        if (s.editLayerId) {
          window.dispatchEvent(new Event("webgis:cancelar-desenho"));
          s.setEditSelected([]);
        } else if (s.activeLayerId) s.clearSelection(s.activeLayerId);
        return;
      }
      if (s.editLayerId) {
        if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSelected(); }
        else if (e.key === "a") s.setEditTool("draw");
        else if (e.key === "v") s.setEditTool("modify");
        else if (e.key === "g") s.setEditTool("move");
        return;
      }
      const tools: Record<string, Parameters<typeof s.setTool>[0]> = { i: "identify", s: "select", m: "measure-line", c: "coords", h: "pan" };
      if (tools[e.key]) s.setTool(tools[e.key]);
      if (e.key === "?") s.openDialog({ tipo: "atalhos" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const zoomAll = useCallback(() => {
    const boxes = useWorkspace.getState().layers.map((l) => l.bbox).filter(Boolean) as number[][];
    if (!boxes.length) return;
    ws.zoomTo([Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])), Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))]);
  }, [ws]);

  const startResize = (e: React.PointerEvent) => {
    const y0 = e.clientY, h0 = tableHeight;
    const move = (ev: PointerEvent) => setTableHeight(Math.max(140, Math.min(window.innerHeight - 220, h0 - (ev.clientY - y0))));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  if (project.error) {
    const e = project.error as ApiError;
    return (
      <main className="grid h-screen place-items-center">
        <div className="text-center">
          <p className="mb-3">{e.status === 404 ? "Projeto não encontrado ou sem acesso." : e.message}</p>
          <button className="text-select hover:underline" onClick={() => router.push("/projetos")}>Voltar aos projetos</button>
        </div>
      </main>
    );
  }
  if (!loaded) return <main className="grid h-screen place-items-center text-muted">Abrindo projeto…</main>;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <MenuBar onSaveProject={async () => { await saveState(); ws.toast("Projeto salvo.", "ok"); }} onZoomAll={zoomAll} />
      <ToolStrip />
      <div className="flex min-h-0 flex-1">
        {ws.panels.left && <div className="w-[236px] shrink-0 xl:w-[272px] max-lg:absolute max-lg:inset-y-16 max-lg:left-0 max-lg:z-30 max-lg:shadow-2xl"><LayerPanel /></div>}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <MapView onDrawEnd={(g) => ws.openDialog({ tipo: "atributos-nova", geometria: g })} />
          </div>
          {ws.panels.table && (
            <div style={{ height: tableHeight }} className="relative shrink-0">
              <div role="separator" aria-orientation="horizontal" aria-label="Redimensionar tabela"
                className="absolute -top-1 left-0 right-0 z-10 h-2 cursor-row-resize" onPointerDown={startResize} />
              <AttributeTable />
            </div>
          )}
        </div>
        {ws.panels.right && <div className="w-[256px] shrink-0 xl:w-[300px] max-lg:absolute max-lg:inset-y-16 max-lg:right-0 max-lg:z-30 max-lg:shadow-2xl"><Toolbox jobs={jobs.data ?? []} /></div>}
      </div>
      <StatusBar running={running} />
      <Dialogs onJobStarted={onJobStarted} />
    </div>
  );
}
