"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, Filter, Plus, Sigma, Trash2, X, ZoomIn } from "lucide-react";
import { useMemo, useState } from "react";
import { Api, filterParam } from "@/lib/api";
import { fidKey } from "@/lib/edit/session";
import type { FieldType, FilterCondition, Layer } from "@/lib/types";
import { canEdit, useWorkspace } from "@/stores/workspace";
import { Button, Dialog, Empty, Field, IconButton } from "./ui";

const PAGE = 100;
const OPS: { v: FilterCondition["operador"]; l: string }[] = [
  { v: "=", l: "igual a" }, { v: "!=", l: "diferente de" }, { v: ">", l: "maior que" }, { v: ">=", l: "maior ou igual" },
  { v: "<", l: "menor que" }, { v: "<=", l: "menor ou igual" }, { v: "contem", l: "contém" }, { v: "comeca", l: "começa com" },
  { v: "nulo", l: "é nulo" }, { v: "nao_nulo", l: "não é nulo" },
];
const TYPE_LABEL: Record<FieldType, string> = { text: "texto", integer: "inteiro", real: "decimal", boolean: "sim/não", date: "data", datetime: "data e hora" };

function bboxOf(g: GeoJSON.Geometry | null): [number, number, number, number] | null {
  if (!g) return null;
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  const walk = (c: any) => {
    if (typeof c[0] === "number") { w = Math.min(w, c[0]); e = Math.max(e, c[0]); s = Math.min(s, c[1]); n = Math.max(n, c[1]); }
    else c.forEach(walk);
  };
  walk((g as any).coordinates);
  return Number.isFinite(w) ? [w, s, e, n] : null;
}

export function AttributeTable() {
  const ws = useWorkspace();
  const layer = ws.layers.find((l) => l.id === ws.activeLayerId && l.tipo === "vetorial");
  if (!layer) {
    return (
      <section className="flex h-full flex-col border-t border-line bg-panel" aria-label="Tabela de atributos">
        <Header title="Tabela de atributos" />
        <Empty>Escolha uma camada vetorial no painel de camadas para ver os atributos.</Empty>
      </section>
    );
  }
  return <Table key={layer.id} layer={layer} />;
}

function Header({ title, children }: { title: string; children?: React.ReactNode }) {
  const toggle = useWorkspace((s) => s.togglePanel);
  return (
    <div className="flex h-8 shrink-0 items-center gap-1 overflow-x-auto whitespace-nowrap border-b border-line px-2">
      <h2 className="mr-2 font-semibold">{title}</h2>
      {children}
      <div className="flex-1" />
      <IconButton label="Fechar tabela" onClick={() => toggle("table")}><X size={15} /></IconButton>
    </div>
  );
}

function Table({ layer }: { layer: Layer }) {
  const ws = useWorkspace();
  const qc = useQueryClient();
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ f: string; d: "asc" | "desc" }>({ f: "fid", d: "asc" });
  const [conds, setConds] = useState<FilterCondition[]>([]);
  const [match, setMatch] = useState<"todas" | "qualquer">("todas");
  const [showFilter, setShowFilter] = useState(false);
  const [onlySel, setOnlySel] = useState(false);
  const [stats, setStats] = useState<string | null>(null);
  const [newField, setNewField] = useState(false);
  const [confirmDrop, setConfirmDrop] = useState<string | null>(null);
  const editing = ws.editLayerId === layer.id;
  const session = editing ? ws.editSession : null;
  const selected = useMemo(() => new Set(ws.selection[layer.id] ?? []), [ws.selection, layer.id]);
  const filtro = filterParam(conds, match);

  const { data, isFetching, error } = useQuery({
    queryKey: ["features", layer.id, layer.versao, page, sort, filtro, onlySel ? [...selected].join(",") : "", editing],
    queryFn: async () => {
      const fc = await Api.features(layer.id, {
        ordenar: sort.f, direcao: sort.d, filtro, limite: PAGE, deslocamento: page * PAGE,
        fids: onlySel ? [...selected].slice(0, 5000).join(",") || "-1" : undefined, geometria: true,
      });
      if (session && session.load(fc.features.map((f) => ({ id: f.id, geometry: f.geometry, properties: f.properties }))).length) ws.bumpEdit();
      return fc;
    },
    placeholderData: (prev) => prev,
  });

  void ws.editTick;
  const rows = data?.features ?? [];
  const pendingNew = session ? session.all().filter((f) => f.fid === null) : [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const editable = canEdit(ws.project);

  const valueOf = (fid: number, name: string, fallback: unknown) => {
    const f = session?.get(fidKey(fid));
    return f ? f.attrs[name] : fallback;
  };
  const isDeleted = (fid: number) => !!session && !session.get(fidKey(fid)) && session.diff().excluir.includes(fid);

  const selectAllFiltered = async () => {
    const r = await Api.select(layer.id, { filtro: conds.length ? { condicoes: conds, combinar: match }
      : { condicoes: [{ campo: "fid", operador: "nao_nulo" }], combinar: "todas" } });
    ws.setSelection(layer.id, r.fids);
    ws.toast(`${r.fids.length.toLocaleString("pt-BR")} feição(ões) selecionada(s).`);
  };

  const zoomFeature = (g: GeoJSON.Geometry | null) => { const b = bboxOf(g); if (b) ws.zoomTo(b); };

  return (
    <section className="flex h-full flex-col border-t border-line bg-panel" aria-label={`Tabela de atributos de ${layer.nome}`}>
      <Header title={layer.nome}>
        <span className="mr-2 text-[12px] text-muted tabular">{total.toLocaleString("pt-BR")} registro(s){selected.size ? ` · ${selected.size} selecionado(s)` : ""}</span>
        <Button variant={conds.length ? "primary" : "ghost"} onClick={() => setShowFilter(!showFilter)}><Filter size={13} />Filtrar{conds.length ? ` (${conds.length})` : ""}</Button>
        <Button variant="ghost" onClick={selectAllFiltered}>Selecionar {conds.length ? "filtradas" : "todas"}</Button>
        <Button variant="ghost" disabled={!selected.size} onClick={() => ws.clearSelection(layer.id)}>Limpar seleção</Button>
        <label className="flex shrink-0 items-center gap-1.5 px-2 text-[12px]"><input type="checkbox" checked={onlySel} onChange={(e) => { setOnlySel(e.target.checked); setPage(0); }} />Só selecionadas</label>
        <Button variant="ghost" disabled={!editable || editing} title={editing ? "Saia da edição para alterar a estrutura de campos" : undefined}
          onClick={() => setNewField(true)}><Plus size={13} />Campo</Button>
        {editing && <span className="ml-2 text-[12px] text-edit">Clique numa célula para editar</span>}
      </Header>
      {showFilter && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-panel-2 px-2 py-1.5">
          {conds.map((c, i) => (
            <div key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-muted">{match === "todas" ? "e" : "ou"}</span>}
              <select value={c.campo} onChange={(e) => setConds(conds.map((x, j) => j === i ? { ...x, campo: e.target.value } : x))}>
                <option value="fid">fid</option>{layer.campos.map((f) => <option key={f.nome}>{f.nome}</option>)}
              </select>
              <select value={c.operador} onChange={(e) => setConds(conds.map((x, j) => j === i ? { ...x, operador: e.target.value as FilterCondition["operador"] } : x))}>
                {OPS.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
              </select>
              {!["nulo", "nao_nulo"].includes(c.operador) && (
                <input className="w-32" value={String(c.valor ?? "")} aria-label="Valor"
                  onChange={(e) => setConds(conds.map((x, j) => j === i ? { ...x, valor: e.target.value } : x))} />
              )}
              <IconButton label="Remover condição" onClick={() => setConds(conds.filter((_, j) => j !== i))}><X size={13} /></IconButton>
            </div>
          ))}
          <Button variant="ghost" onClick={() => { setConds([...conds, { campo: layer.campos[0]?.nome ?? "fid", operador: "=", valor: "" }]); setPage(0); }}><Plus size={13} />Condição</Button>
          {conds.length > 1 && (
            <select value={match} onChange={(e) => setMatch(e.target.value as "todas" | "qualquer")} aria-label="Combinar condições">
              <option value="todas">todas as condições</option><option value="qualquer">qualquer condição</option>
            </select>
          )}
        </div>
      )}
      {error && <p className="px-3 py-2 text-danger">{(error as Error).message}</p>}
      <div className={clsx("min-h-0 flex-1 overflow-auto", isFetching && "opacity-70")}>
        <table className="w-max min-w-full border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-10 bg-panel-2">
            <tr>
              <th className="w-8" />
              <SortTh label="fid" active={sort.f === "fid"} dir={sort.d} onClick={() => setSort({ f: "fid", d: sort.f === "fid" && sort.d === "asc" ? "desc" : "asc" })} />
              {layer.campos.map((f) => (
                <SortTh key={f.nome} label={f.nome} sub={TYPE_LABEL[f.tipo]} active={sort.f === f.nome} dir={sort.d}
                  onClick={() => setSort({ f: f.nome, d: sort.f === f.nome && sort.d === "asc" ? "desc" : "asc" })}
                  extra={<>
                    <IconButton label={`Estatísticas de ${f.nome}`} className="size-5" onClick={() => setStats(f.nome)}><Sigma size={12} /></IconButton>
                    {editable && !editing && <IconButton label={`Excluir campo ${f.nome}`} className="size-5" onClick={() => setConfirmDrop(f.nome)}><Trash2 size={11} /></IconButton>}
                  </>} />
              ))}
            </tr>
          </thead>
          <tbody>
            {pendingNew.map((f) => (
              <tr key={f.key} className="bg-edit/8">
                <td />
                <td className="px-2 text-edit">nova</td>
                {layer.campos.map((c) => (
                  <Cell key={c.nome} type={c.tipo} value={f.attrs[c.nome]} editable
                    onChange={(v) => { session!.setAttributes(f.key, { [c.nome]: v }); ws.bumpEdit(); }} />
                ))}
              </tr>
            ))}
            {rows.map((r) => {
              const sel = selected.has(r.id);
              const deleted = isDeleted(r.id);
              return (
                <tr key={r.id} aria-selected={sel}
                  className={clsx("border-b border-line/50", sel ? "bg-select/14" : "hover:bg-panel-2", deleted && "line-through opacity-50")}
                  onClick={(e) => ws.setSelection(layer.id, [r.id], e.ctrlKey || e.metaKey ? "toggle" : e.shiftKey ? "add" : "replace")}
                  onDoubleClick={() => zoomFeature(r.geometry)}>
                  <td className="px-1"><IconButton label="Enquadrar feição" className="size-5" onClick={(e) => { e.stopPropagation(); zoomFeature(r.geometry); }}><ZoomIn size={12} /></IconButton></td>
                  <td className="px-2 text-muted tabular">{r.id}</td>
                  {layer.campos.map((c) => (
                    <Cell key={c.nome} type={c.tipo} value={valueOf(r.id, c.nome, r.properties[c.nome])}
                      changed={!!session && session.get(fidKey(r.id)) !== undefined && JSON.stringify(valueOf(r.id, c.nome, r.properties[c.nome])) !== JSON.stringify(r.properties[c.nome])}
                      editable={editing && !deleted}
                      onChange={(v) => { session!.setAttributes(fidKey(r.id), { [c.nome]: v }); ws.bumpEdit(); }} />
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && !pendingNew.length && !isFetching && <Empty>{conds.length || onlySel ? "Nenhum registro atende ao filtro." : "A camada não tem feições."}</Empty>}
      </div>
      <div className="flex h-7 shrink-0 items-center justify-end gap-2 border-t border-line px-2 text-[12px] tabular">
        <Button variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</Button>
        <span>Página {page + 1} de {pages}</span>
        <Button variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Próxima</Button>
      </div>
      {stats && <StatsDialog layer={layer} field={stats} filtro={filtro} onClose={() => setStats(null)} />}
      {newField && <NewFieldDialog layer={layer} onClose={() => setNewField(false)} />}
      {confirmDrop && (
        <Dialog title="Excluir campo" onClose={() => setConfirmDrop(null)} footer={<>
          <Button onClick={() => setConfirmDrop(null)}>Cancelar</Button>
          <Button variant="danger" onClick={async () => {
            try { ws.upsertLayer(await Api.deleteField(layer.id, confirmDrop)); qc.invalidateQueries({ queryKey: ["features", layer.id] }); }
            catch (e) { ws.toast((e as Error).message, "erro"); }
            setConfirmDrop(null);
          }}>Excluir campo</Button></>}>
          <p>O campo <strong>{confirmDrop}</strong> e todos os seus valores serão removidos da camada.</p>
        </Dialog>
      )}
    </section>
  );
}

function SortTh({ label, sub, active, dir, onClick, extra }: { label: string; sub?: string; active: boolean; dir: string; onClick: () => void; extra?: React.ReactNode }) {
  return (
    <th className="border-b border-line px-2 py-1 text-left font-medium whitespace-nowrap" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <div className="flex items-center gap-1">
        <button className="flex items-center gap-1 hover:text-select" onClick={onClick} title={sub}>
          {label}{active && (dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
        </button>
        {extra}
      </div>
    </th>
  );
}

function Cell({ type, value, editable, changed, onChange }: { type: FieldType; value: unknown; editable?: boolean; changed?: boolean; onChange: (v: unknown) => void }) {
  const [editingCell, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const shown = value === null || value === undefined ? <span className="text-muted/70">nulo</span>
    : type === "boolean" ? (value ? "sim" : "não") : String(value);
  const commit = () => {
    setEditing(false);
    let v: unknown = draft;
    if (draft === "") v = null;
    else if (type === "integer") v = Number.isInteger(Number(draft)) ? Number(draft) : draft;
    else if (type === "real") v = Number.isFinite(Number(draft.replace(",", "."))) ? Number(draft.replace(",", ".")) : draft;
    else if (type === "boolean") v = ["sim", "true", "1"].includes(draft.toLowerCase());
    if (JSON.stringify(v) !== JSON.stringify(value ?? null)) onChange(v);
  };
  if (editable && editingCell) {
    return (
      <td className="px-1" onClick={(e) => e.stopPropagation()}>
        {type === "boolean" ? (
          <select autoFocus className="h-6" value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}>
            <option value="">nulo</option><option value="sim">sim</option><option value="não">não</option>
          </select>
        ) : (
          <input autoFocus className="h-6 w-40" type={type === "date" ? "date" : type === "datetime" ? "datetime-local" : "text"}
            value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
            onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }} />
        )}
      </td>
    );
  }
  return (
    <td className={clsx("max-w-72 truncate px-2 py-0.5", (type === "integer" || type === "real") && "text-right tabular", changed && "text-edit", editable && "cursor-text")}
      onClick={(e) => { if (editable) { e.stopPropagation(); setDraft(value === null || value === undefined ? "" : type === "boolean" ? (value ? "sim" : "não") : String(value).slice(0, type === "datetime" ? 16 : undefined)); setEditing(true); } }}>
      {shown}
    </td>
  );
}

function StatsDialog({ layer, field, filtro, onClose }: { layer: Layer; field: string; filtro?: string; onClose: () => void }) {
  const { data, error } = useQuery({ queryKey: ["stats", layer.id, layer.versao, field, filtro], queryFn: () => Api.fieldStats(layer.id, field, filtro) });
  const fmt = (v: unknown) => typeof v === "number" ? v.toLocaleString("pt-BR", { maximumFractionDigits: 4 }) : v === null || v === undefined ? "—" : String(v);
  const rows: [string, unknown][] = data ? [
    ["Registros", data.total], ["Preenchidos", data.preenchidos], ["Valores distintos", data.distintos],
    ...(["min", "max", "media", "mediana", "soma", "desvio"] as const).filter((k) => k in data).map((k) => [
      { min: "Mínimo", max: "Máximo", media: "Média", mediana: "Mediana", soma: "Soma", desvio: "Desvio-padrão" }[k], data[k]] as [string, unknown]),
  ] : [];
  return (
    <Dialog title={`Estatísticas · ${field}`} onClose={onClose} width={380}>
      {error && <p className="text-danger">{(error as Error).message}</p>}
      {filtro && <p className="mb-2 text-[12px] text-muted">Considerando apenas os registros do filtro atual.</p>}
      <table className="w-full tabular"><tbody>
        {rows.map(([k, v]) => <tr key={k}><td className="py-0.5 text-muted">{k}</td><td className="text-right">{fmt(v)}</td></tr>)}
      </tbody></table>
      {data?.mais_frequentes?.length > 0 && (<>
        <p className="mb-1 mt-3 font-medium">Valores mais frequentes</p>
        <table className="w-full tabular"><tbody>
          {data!.mais_frequentes.map((r: any, i: number) => <tr key={i}><td className="py-0.5">{fmt(r.valor)}</td><td className="text-right text-muted">{r.n}</td></tr>)}
        </tbody></table>
      </>)}
    </Dialog>
  );
}

function NewFieldDialog({ layer, onClose }: { layer: Layer; onClose: () => void }) {
  const ws = useWorkspace();
  const [nome, setNome] = useState("");
  const [tipo, setTipo] = useState<FieldType>("text");
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title="Adicionar campo" onClose={onClose} width={360} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" disabled={!nome.trim()} onClick={async () => {
        try { ws.upsertLayer(await Api.addField(layer.id, nome.trim(), tipo)); onClose(); }
        catch (e) { setErr((e as Error).message); }
      }}>Adicionar campo</Button></>}>
      <Field label="Nome"><input className="w-full h-8" value={nome} onChange={(e) => setNome(e.target.value)} maxLength={100} /></Field>
      <Field label="Tipo"><select className="w-full h-8" value={tipo} onChange={(e) => setTipo(e.target.value as FieldType)}>
        {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      {err && <p role="alert" className="text-danger">{err}</p>}
    </Dialog>
  );
}
