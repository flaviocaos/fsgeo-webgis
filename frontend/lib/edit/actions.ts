"use client";
/** Ações do editor, compartilhadas por menus, barra de ferramentas e atalhos de teclado. */
import { Api, ApiError } from "../api";
import { useWorkspace } from "@/stores/workspace";
import { EditSession } from "./session";

const st = () => useWorkspace.getState();

export async function startEditing(layerId: string): Promise<void> {
  const s = st();
  if (s.editLayerId) {
    if (s.editLayerId === layerId) return;
    if (s.editSession && s.editSession.pendingCount() > 0) {
      s.toast("Salve ou descarte as alterações da camada em edição antes de editar outra.", "erro");
      return;
    }
    s.stopEdit();
  }
  const layer = s.layers.find((l) => l.id === layerId);
  if (!layer || layer.tipo !== "vetorial") return;
  if (!layer.crs) { s.toast("Defina o sistema de referência da camada antes de editá-la.", "erro"); return; }
  if (s.project?.papel === "viewer") { s.toast("Seu papel neste projeto é somente leitura.", "erro"); return; }
  const fresh = await Api.layer(layerId);
  s.upsertLayer(fresh);
  s.startEdit(layerId, new EditSession(layerId, fresh.versao));
  // Garante a camada visível durante a edição.
  if (fresh.exibicao && !fresh.exibicao.visivel) s.updateDisplay(layerId, { visivel: true });
}

export function undo() { const s = st(); if (s.editSession?.undo().length) s.bumpEdit(); }
export function redo() { const s = st(); if (s.editSession?.redo().length) s.bumpEdit(); }

export function deleteSelected() {
  const s = st();
  if (!s.editSession || !s.editSelected.length) return;
  const n = s.editSelected.length;
  s.editSession.remove(s.editSelected, n === 1 ? "Excluir feição" : `Excluir ${n} feições`);
  s.setEditSelected([]);
  s.bumpEdit();
}

export function createFeature(geometry: GeoJSON.Geometry, attrs: Record<string, unknown>) {
  const s = st();
  if (!s.editSession) return;
  const key = s.editSession.create(geometry, attrs);
  s.setEditSelected([key]);
  s.bumpEdit();
}

/** Salva o lote. Com geometrias inválidas, pergunta (via retorno) se deve corrigir automaticamente. */
export async function saveEdits(fixInvalid = false): Promise<{ ok: boolean; invalid?: { ref: string; erro: string }[] }> {
  const s = st();
  const session = s.editSession;
  if (!session || !s.editLayerId) return { ok: true };
  const batch = session.diff();
  const total = batch.criar.length + batch.atualizar.length + batch.excluir.length;
  if (!total) { s.toast("Nenhuma alteração para salvar."); return { ok: true }; }
  try {
    const r = await Api.edits(s.editLayerId, { ...batch, corrigir_invalidas: fixInvalid });
    session.markSaved(r.criadas, r.versao);
    const fresh = await Api.layer(s.editLayerId);
    s.upsertLayer(fresh);
    s.setEditSelected([]);
    s.bumpEdit();
    s.toast(`Edições salvas: ${r.criadas ? Object.keys(r.criadas).length : 0} criada(s), ${r.alteradas} alterada(s), ${r.excluidas} excluída(s).`, "ok");
    return { ok: true };
  } catch (e) {
    if (e instanceof ApiError && e.code === "edicao_invalida") {
      const det = (e.details as { ref: string; erro: string; corrigivel?: boolean }[]) ?? [];
      if (det.length && det.every((d) => d.corrigivel)) return { ok: false, invalid: det };
      s.toast(`${e.message} ${det.slice(0, 3).map((d) => d.erro).join(" · ")}`, "erro");
    } else if (e instanceof ApiError && e.code === "conflito_versao") {
      s.toast(e.message, "erro");
    } else {
      s.toast((e as Error).message, "erro");
    }
    return { ok: false };
  }
}

export function discardEdits() {
  const s = st();
  const id = s.editLayerId;
  s.stopEdit();
  if (id) Api.layer(id).then(s.upsertLayer).catch(() => {});
}

export function stopEditing(): boolean {
  const s = st();
  if (s.editSession && s.editSession.pendingCount() > 0) {
    s.toast("Há alterações pendentes: salve ou descarte antes de sair da edição.", "erro");
    return false;
  }
  s.stopEdit();
  return true;
}
