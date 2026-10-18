"use client";
import { api, ApiError, authHeaders, request } from "./api";

export interface UploadProgress {
  arquivo: string;
  enviados: number;
  total: number;
}

/** Fatia um tamanho em partes do tamanho indicado (a última pode ser menor). */
export function planParts(size: number, partSize: number): { n: number; start: number; end: number }[] {
  const parts = [];
  const count = Math.max(1, Math.ceil(size / partSize));
  for (let i = 0; i < count; i++) parts.push({ n: i + 1, start: i * partSize, end: Math.min(size, (i + 1) * partSize) });
  return parts;
}

/** Envia um arquivo em partes e devolve o id do dataset criado no servidor. */
export async function uploadFile(projectId: string, file: File, onProgress?: (p: UploadProgress) => void): Promise<string> {
  const up = await request<{ id: string; tamanho_parte: number; partes: number }>(`/projects/${projectId}/uploads`, {
    method: "POST", json: { nome_arquivo: file.name, tamanho: file.size },
  });
  let sent = 0;
  for (const part of planParts(file.size, up.tamanho_parte)) {
    const blob = file.slice(part.start, part.end);
    let lastErr: unknown;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const r = await fetch(`${api}/uploads/${up.id}/parts/${part.n}`, {
          method: "PUT", headers: { ...(await authHeaders()), "Content-Type": "application/octet-stream" }, body: blob,
        });
        if (!r.ok) {
          const e = (await r.json().catch(() => null))?.erro;
          throw new ApiError(r.status, e?.codigo || "erro", e?.mensagem || `Falha ao enviar parte ${part.n}`);
        }
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e;
        if (e instanceof ApiError && e.status >= 400 && e.status < 500) break;
        await new Promise((res) => setTimeout(res, 800 * (attempt + 1)));
      }
    }
    if (lastErr) throw lastErr;
    sent += part.end - part.start;
    onProgress?.({ arquivo: file.name, enviados: sent, total: file.size });
  }
  const done = await request<{ dataset_id: string }>(`/uploads/${up.id}/complete`, { method: "POST" });
  return done.dataset_id;
}
