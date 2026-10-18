"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, CircleStop, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Api } from "@/lib/api";
import type { Job, Tool, ToolParam } from "@/lib/types";
import { TERMINAL } from "@/lib/types";
import { canEdit, useWorkspace } from "@/stores/workspace";
import { CrsPicker } from "./CrsPicker";
import { Badge, Button, Empty, Field, IconButton, Progress } from "./ui";

const STATUS: Record<Job["status"], { label: string; tone: "muted" | "select" | "ok" | "danger" }> = {
  queued: { label: "Na fila", tone: "muted" }, running: { label: "Executando", tone: "select" },
  succeeded: { label: "Concluído", tone: "ok" }, failed: { label: "Falhou", tone: "danger" },
  cancelling: { label: "Cancelando", tone: "muted" }, cancelled: { label: "Cancelado", tone: "muted" },
};

export function Toolbox({ jobs }: { jobs: Job[] }) {
  const ws = useWorkspace();
  const { data: tools = [], error } = useQuery({ queryKey: ["tools"], queryFn: Api.tools, staleTime: Infinity });
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"ferramentas" | "historico">("ferramentas");
  const current = tools.find((t) => t.id === ws.toolboxTool);

  const [showUnavailable, setShowUnavailable] = useState(false);
  const { groups, unavailable } = useMemo(() => {
    const norm = (x: string) => x.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
    const f = tools.filter((t) => !q || norm(`${t.nome} ${t.grupo} ${t.descricao}`).includes(norm(q)));
    const m = new Map<string, Tool[]>();
    for (const t of f.filter((x) => x.status === "disponivel")) m.set(t.grupo, [...(m.get(t.grupo) ?? []), t]);
    return { groups: [...m.entries()].sort(([a], [b]) => a.localeCompare(b)), unavailable: f.filter((x) => x.status !== "disponivel") };
  }, [tools, q]);

  return (
    <aside className="flex h-full flex-col border-l border-line bg-panel" aria-label="Caixa de ferramentas">
      <div className="flex h-8 shrink-0 items-center gap-3 border-b border-line px-3">
        {(["ferramentas", "historico"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t}
            className={clsx("h-full border-b-2 text-[12.5px]", tab === t ? "border-select font-semibold" : "border-transparent text-muted hover:text-text")}>
            {t === "ferramentas" ? "Ferramentas" : `Processamentos${jobs.some((j) => !TERMINAL.includes(j.status)) ? " •" : ""}`}
          </button>
        ))}
      </div>
      {tab === "historico" ? <JobList jobs={jobs} /> : current ? (
        <ToolForm tool={current} onBack={() => ws.openTool(null)} onStarted={() => setTab("historico")} />
      ) : (
        <>
          <div className="relative shrink-0 border-b border-line p-2">
            <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
            <input className="h-7 w-full pl-7" placeholder="Buscar ferramenta" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar ferramenta" />
          </div>
          <div className="min-h-0 flex-1 overflow-auto pb-2">
            {error && <p className="p-3 text-danger">{(error as Error).message}</p>}
            {groups.map(([g, ts]) => (
              <section key={g}>
                <h3 className="px-3 pb-0.5 pt-2.5 text-[11.5px] font-semibold text-muted">{g}</h3>
                {ts.map((t) => (
                  <button key={t.id} onClick={() => ws.openTool(t.id)} title={t.descricao}
                    className="flex w-full items-center px-3 py-1 text-left hover:bg-panel-2">{t.nome}</button>
                ))}
              </section>
            ))}
            {unavailable.length > 0 && (
              <section className="mt-3 border-t border-line">
                <button className="flex w-full items-center justify-between px-3 py-2 text-left text-muted hover:text-text"
                  aria-expanded={showUnavailable || !!q} onClick={() => setShowUnavailable(!showUnavailable)}>
                  <span>{ws.t("indisponivel")} nesta fase</span><span className="tabular">{unavailable.length}</span>
                </button>
                {(showUnavailable || !!q) && unavailable.map((t) => (
                  <div key={t.id} className="flex items-center justify-between px-3 py-1 text-muted" title={t.descricao}>
                    <span>{t.nome}</span><span className="text-[10.5px]">Fase {t.fase}</span>
                  </div>
                ))}
              </section>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

function ToolForm({ tool, onBack, onStarted }: { tool: Tool; onBack: () => void; onStarted: () => void }) {
  const ws = useWorkspace();
  const vectors = ws.layers.filter((l) => l.tipo === "vetorial" && l.crs);
  const initial = useMemo(() => {
    const v: Record<string, unknown> = {};
    for (const p of tool.parametros) {
      if (p.tipo === "camada") {
        const ok = vectors.filter((l) => !p.geometrias || p.geometrias.includes(l.geometria!));
        const active = ok.find((l) => l.id === ws.activeLayerId);
        v[p.nome] = (active ?? ok[0])?.id ?? "";
      } else v[p.nome] = p.padrao ?? (p.tipo === "campos" ? [] : "");
    }
    return v;
  }, [tool.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const [values, setValues] = useState<Record<string, unknown>>(initial);
  const [saida, setSaida] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setValues(initial), [initial]);
  const run = useMutation({
    mutationFn: () => Api.runTool(ws.project!.id, tool.id, { ...values, ...(saida.trim() ? { saida: saida.trim() } : {}) }),
    onSuccess: () => { ws.toast(`${tool.nome}: processamento iniciado.`); onStarted(); },
    onError: (e) => setErr((e as Error).message),
  });
  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }));

  return (
    <div className="min-h-0 flex-1 overflow-auto p-3">
      <button onClick={onBack} className="mb-2 flex items-center gap-1 text-muted hover:text-text"><ChevronLeft size={14} />Todas as ferramentas</button>
      <h3 className="text-[15px] font-semibold">{tool.nome}</h3>
      <p className="mb-3 mt-1 text-[12px] text-muted">{tool.descricao}</p>
      {tool.parametros.map((p) => (
        <ParamInput key={p.nome} p={p} value={values[p.nome]} onChange={(v) => set(p.nome, v)} values={values} />
      ))}
      <Field label="Nome da camada de saída (opcional)"><input className="w-full h-8" value={saida} onChange={(e) => setSaida(e.target.value)} placeholder="gerado automaticamente" /></Field>
      <p className="mb-3 text-[12px] text-muted">O resultado é uma camada nova; as camadas de entrada não são alteradas.</p>
      {err && <p role="alert" className="mb-2 text-danger">{err}</p>}
      <Button variant="primary" className="w-full h-8" disabled={run.isPending || !canEdit(ws.project)} onClick={() => { setErr(null); run.mutate(); }}>
        {ws.t("acao.executar")}
      </Button>
    </div>
  );
}

function ParamInput({ p, value, onChange, values }: { p: ToolParam; value: unknown; onChange: (v: unknown) => void; values: Record<string, unknown> }) {
  const layers = useWorkspace((s) => s.layers);
  if (p.tipo === "camada") {
    const ok = layers.filter((l) => l.tipo === "vetorial" && l.crs && (!p.geometrias || p.geometrias.includes(l.geometria!)));
    return (
      <Field label={p.rotulo} hint={p.geometrias && p.geometrias.length < 6 ? `Aceita: ${[...new Set(p.geometrias.map((g) => g.replace("Multi", "")))].join(", ")}` : undefined}>
        <select className="w-full h-8" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {!ok.length && <option value="">Nenhuma camada compatível</option>}
          {ok.map((l) => <option key={l.id} value={l.id}>{l.nome}</option>)}
        </select>
      </Field>
    );
  }
  if (p.tipo === "numero" || p.tipo === "inteiro") {
    return <Field label={p.rotulo}><input type="number" className="w-full h-8" step={p.tipo === "inteiro" ? 1 : "any"} min={p.minimo} max={p.maximo}
      value={value === "" || value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} /></Field>;
  }
  if (p.tipo === "booleano") {
    return <label className="mb-3 flex items-center gap-2"><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />{p.rotulo}</label>;
  }
  if (p.tipo === "escolha") {
    return <Field label={p.rotulo}><select className="w-full h-8" value={String(value)} onChange={(e) => onChange(e.target.value)}>
      {p.opcoes?.map((o) => <option key={o} value={o}>{o}</option>)}</select></Field>;
  }
  if (p.tipo === "crs") return <Field label={p.rotulo}><CrsPicker value={String(value ?? "")} onChange={onChange} /></Field>;
  if (p.tipo === "campos") {
    const layer = layers.find((l) => l.id === values[p.camada ?? "camada"]);
    const sel = new Set((value as string[]) ?? []);
    return (
      <Field label={p.rotulo}>
        <div className="max-h-32 overflow-auto rounded border border-line p-1.5">
          {!layer?.campos.length && <span className="text-muted">A camada não tem campos.</span>}
          {layer?.campos.map((c) => (
            <label key={c.nome} className="flex items-center gap-2 py-0.5">
              <input type="checkbox" checked={sel.has(c.nome)} onChange={(e) => {
                const n = new Set(sel); e.target.checked ? n.add(c.nome) : n.delete(c.nome); onChange([...n]);
              }} />{c.nome}
            </label>
          ))}
        </div>
      </Field>
    );
  }
  return <Field label={p.rotulo}><input className="w-full h-8" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} /></Field>;
}

function JobList({ jobs }: { jobs: Job[] }) {
  const ws = useWorkspace();
  const { data: tools = [] } = useQuery({ queryKey: ["tools"], queryFn: Api.tools, staleTime: Infinity });
  if (!jobs.length) return <Empty>Nenhum processamento ainda. Importações, ferramentas e exportações aparecem aqui.</Empty>;
  return (
    <ul className="min-h-0 flex-1 overflow-auto">
      {jobs.map((j) => {
        const st = STATUS[j.status];
        const title = j.tipo === "import" ? "Importação" : j.tipo === "export"
          ? `Exportação · ${String(j.parametros.camada ?? "")} (${String(j.parametros.formato ?? "").toUpperCase()})`
          : tools.find((t) => t.id === j.ferramenta)?.nome ?? j.ferramenta;
        const outLayer = j.resultado?.camada?.id as string | undefined;
        return (
          <li key={j.id} className="border-b border-line/70 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-medium">{title}</span>
              <Badge tone={st.tone}>{st.label}</Badge>
            </div>
            <div className="mt-0.5 text-[11px] text-muted tabular">{new Date(j.criado_em).toLocaleTimeString("pt-BR")}</div>
            {!TERMINAL.includes(j.status) && (
              <div className="mt-1.5 flex items-center gap-2">
                <Progress value={j.progresso} />
                <IconButton label="Cancelar processamento" onClick={() => Api.cancelJob(j.id).catch((e) => ws.toast(e.message, "erro"))}><CircleStop size={14} /></IconButton>
              </div>
            )}
            {j.erro && <p className="mt-1 text-[12px] text-danger">{j.erro}</p>}
            {j.status === "succeeded" && j.tipo === "import" && (
              <p className="mt-1 text-[12px]">{(j.resultado?.camadas ?? []).map((c: any) => `${c.nome} (${c.tipo === "raster" ? `${c.bandas} banda(s)` : `${c.feicoes} feições`})`).join(", ")}</p>
            )}
            {j.status === "succeeded" && j.tipo === "tool" && (
              <p className="mt-1 text-[12px]">
                Camada criada: <button className="text-select hover:underline" onClick={() => { ws.setActiveLayer(outLayer!); const l = ws.layers.find((x) => x.id === outLayer); if (l?.bbox) ws.zoomTo(l.bbox); }}>{j.resultado?.camada?.nome}</button>
                {" "}({j.resultado?.camada?.feicoes} feições)
              </p>
            )}
            {j.status === "succeeded" && j.tipo === "export" && (
              <button className="mt-1 text-[12px] text-select hover:underline" onClick={async () => {
                const r = await Api.exportUrl(j.resultado!.exportacao_id); window.open(r.url, "_blank", "noopener");
              }}>Baixar {j.resultado?.arquivo}</button>
            )}
            {j.mensagens.filter((m) => m.nivel === "aviso").map((m, i) => <p key={i} className="mt-1 text-[11.5px] text-edit">{m.texto}</p>)}
          </li>
        );
      })}
    </ul>
  );
}
