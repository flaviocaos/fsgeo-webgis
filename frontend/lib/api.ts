"use client";
import { getToken } from "./auth";
import { config } from "./config";
import type { FeatureCollectionOut, FilterCondition, Job, Layer, Project, Tool } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export const api = config.apiUrl + "/api/v1";

export async function authHeaders(): Promise<Record<string, string>> {
  const t = await getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeaders()), ...(init.headers as Record<string, string>) };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let r: Response;
  try {
    r = await fetch(path.startsWith("http") ? path : api + path, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "rede", "Sem conexão com o servidor da API. Verifique se ela está em execução.");
  }
  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const e = data?.erro;
    if (r.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
      location.href = "/login?expirada=1";
    }
    throw new ApiError(r.status, e?.codigo || "erro", e?.mensagem || `Erro ${r.status}`, e?.detalhes);
  }
  return data as T;
}

export function filterParam(conds: FilterCondition[], combinar: "todas" | "qualquer" = "todas"): string | undefined {
  return conds.length ? JSON.stringify({ condicoes: conds, combinar }) : undefined;
}

function qs(params: Record<string, string | number | boolean | undefined>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const Api = {
  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (nome: string, crs: string, descricao = "") =>
    request<Project>("/projects", { method: "POST", json: { nome, crs, descricao } }),
  patchProject: (id: string, body: Partial<{ nome: string; crs: string; estado: unknown; descricao: string }>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", json: body }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  duplicateProject: (id: string) => request<Project>(`/projects/${id}/duplicate`, { method: "POST" }),
  saveLayersState: (id: string, state: unknown[]) =>
    request(`/projects/${id}/layers-state`, { method: "PUT", json: state }),
  members: (id: string) => request<{ id: string; email: string; papel: string }[]>(`/projects/${id}/members`),
  addMember: (id: string, email: string, papel: string) =>
    request(`/projects/${id}/members`, { method: "POST", json: { email, papel } }),
  removeMember: (id: string, uid: string) => request(`/projects/${id}/members/${uid}`, { method: "DELETE" }),

  layer: (id: string) => request<Layer>(`/layers/${id}`),
  createLayer: (pid: string, body: { nome: string; geometria: string; crs?: string; campos: { nome: string; tipo: string }[] }) =>
    request<Layer>(`/projects/${pid}/layers`, { method: "POST", json: body }),
  renameLayer: (id: string, nome: string) => request<Layer>(`/layers/${id}`, { method: "PATCH", json: { nome } }),
  deleteLayer: (id: string) => request<void>(`/layers/${id}`, { method: "DELETE" }),
  defineCrs: (id: string, crs: string) => request<Layer>(`/layers/${id}/crs`, { method: "POST", json: { crs } }),
  addField: (id: string, nome: string, tipo: string) =>
    request<Layer>(`/layers/${id}/fields`, { method: "POST", json: { nome, tipo } }),
  deleteField: (id: string, nome: string) =>
    request<Layer>(`/layers/${id}/fields/${encodeURIComponent(nome)}`, { method: "DELETE" }),
  renameField: (id: string, nome: string, novo: string) =>
    request<Layer>(`/layers/${id}/fields/${encodeURIComponent(nome)}`, { method: "PATCH", json: { novo_nome: novo } }),
  fieldStats: (id: string, nome: string, filtro?: string) =>
    request<Record<string, any>>(`/layers/${id}/fields/${encodeURIComponent(nome)}/stats${qs({ filtro })}`),
  features: (id: string, p: { bbox?: string; fids?: string; filtro?: string; ordenar?: string; direcao?: string;
    limite?: number; deslocamento?: number; geometria?: boolean; contar?: boolean }) =>
    request<FeatureCollectionOut>(`/layers/${id}/features${qs(p as Record<string, string>)}`),
  select: (id: string, body: { bbox?: number[]; geometria?: unknown; filtro?: unknown }) =>
    request<{ fids: number[]; limite_atingido: boolean }>(`/layers/${id}/select`, { method: "POST", json: body }),
  identify: (id: string, lon: number, lat: number, tol: number) =>
    request<any>(`/layers/${id}/identify${qs({ lon, lat, tolerancia_m: tol })}`),
  edits: (id: string, body: unknown) =>
    request<{ versao: number; criadas: Record<string, number>; alteradas: number; excluidas: number }>(
      `/layers/${id}/edits`, { method: "POST", json: body }),
  editHistory: (id: string) => request<any[]>(`/layers/${id}/edits`),

  tools: () => request<Tool[]>("/tools"),
  runTool: (pid: string, tool: string, parametros: Record<string, unknown>) =>
    request<Job>(`/projects/${pid}/tools/${tool}/run`, { method: "POST", json: { parametros } }),
  jobs: (pid: string) => request<Job[]>(`/projects/${pid}/jobs`),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  exportLayer: (id: string, formato: string) => request<Job>(`/layers/${id}/export`, { method: "POST", json: { formato } }),
  exportUrl: (id: string) => request<{ url: string; arquivo: string }>(`/exports/${id}/url`),
  startImport: (pid: string, datasets: string[]) =>
    request<Job>(`/projects/${pid}/imports`, { method: "POST", json: { datasets } }),

  crsSearch: (q: string) => request<{ codigo: string; nome: string; geografico: boolean }[]>(`/crs/search${qs({ q })}`),
  crsInfo: (code: string) => request<{ codigo: string | null; nome: string; proj4: string; unidade: string; geografico: boolean }>(
    `/crs/${encodeURIComponent(code)}`),
};
