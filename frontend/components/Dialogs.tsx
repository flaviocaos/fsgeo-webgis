"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Trash2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Api } from "@/lib/api";
import { createFeature } from "@/lib/edit/actions";
import { colorForId } from "@/lib/map/styles";
import type { FieldType, GeomType, Job, Layer, ServiceLayer } from "@/lib/types";
import { uploadFile } from "@/lib/upload";
import { canEdit, useWorkspace } from "@/stores/workspace";
import { CrsPicker } from "./CrsPicker";
import { Badge, Button, Dialog, Field, IconButton, Progress } from "./ui";

export function Dialogs({ onJobStarted }: { onJobStarted: (j: Job) => void }) {
  const dialog = useWorkspace((s) => s.dialog);
  const close = useWorkspace((s) => s.closeDialog);
  const onClose = useCallback(() => close(), [close]);
  if (!dialog) return null;
  switch (dialog.tipo) {
    case "importar": return <ImportDialog onClose={onClose} onJobStarted={onJobStarted} />;
    case "nova-camada": return <NewLayerDialog onClose={onClose} />;
    case "servico": return <ServiceDialog onClose={onClose} />;
    case "exportar": return <ExportDialog layerId={dialog.camada} onClose={onClose} onJobStarted={onJobStarted} />;
    case "propriedades": return <PropertiesDialog layerId={dialog.camada} onClose={onClose} />;
    case "atributos-nova": return <NewFeatureDialog geometry={dialog.geometria} onClose={onClose} />;
    case "excluir-camada": return <DeleteLayerDialog layerId={dialog.camada} onClose={onClose} />;
    case "compartilhar": return <ShareDialog onClose={onClose} />;
    case "crs-projeto": return <ProjectCrsDialog onClose={onClose} />;
    case "atalhos": return <ShortcutsDialog onClose={onClose} />;
    case "sobre": return <AboutDialog onClose={onClose} />;
    default: return null;
  }
}

// ------------------------------------------------------------------ importação

function ImportDialog({ onClose, onJobStarted }: { onClose: () => void; onJobStarted: (j: Job) => void }) {
  const project = useWorkspace((s) => s.project)!;
  const toast = useWorkspace((s) => s.toast);
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const add = (list: FileList | null) => list && setFiles((f) => [...f, ...Array.from(list).filter((x) => !f.some((y) => y.name === x.name))]);

  const start = async () => {
    setBusy(true); setErr(null);
    try {
      const ids: string[] = [];
      for (const f of files) ids.push(await uploadFile(project.id, f, (p) => setProgress((s) => ({ ...s, [p.arquivo]: Math.round((p.enviados / p.total) * 100) }))));
      const job = await Api.startImport(project.id, ids);
      onJobStarted(job);
      toast("Arquivos enviados. A importação continua na aba Processamentos.");
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog title="Importar dados" onClose={onClose} width={520} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" disabled={!files.length || busy} onClick={start}>{busy ? "Enviando…" : "Enviar e importar"}</Button>
    </>}>
      <label onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        className={`mb-3 flex cursor-pointer flex-col items-center gap-2 rounded border border-dashed px-4 py-6 text-center ${over ? "border-select bg-select/8" : "border-line"}`}>
        <FileUp size={22} className="text-muted" />
        <span>Arraste arquivos aqui ou clique para escolher</span>
        <span className="text-[12px] text-muted">GeoJSON · Shapefile (.zip, ou .shp com .shx, .dbf e .prj) · GeoPackage · GeoTIFF</span>
        <input type="file" multiple className="sr-only" onChange={(e) => add(e.target.files)}
          accept=".geojson,.json,.zip,.shp,.shx,.dbf,.prj,.cpg,.gpkg,.tif,.tiff" />
      </label>
      {files.length > 0 && (
        <ul className="mb-2">
          {files.map((f) => (
            <li key={f.name} className="flex items-center gap-2 py-1">
              <span className="flex-1 truncate">{f.name}</span>
              <span className="text-[12px] text-muted tabular">{(f.size / 1048576).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} MB</span>
              {progress[f.name] !== undefined ? <div className="w-24"><Progress value={progress[f.name]} /></div>
                : <IconButton label={`Remover ${f.name}`} disabled={busy} onClick={() => setFiles(files.filter((x) => x !== f))}><Trash2 size={13} /></IconButton>}
            </li>
          ))}
        </ul>
      )}
      <p className="text-[12px] text-muted">Os arquivos de um mesmo Shapefile são importados juntos. Arquivos grandes são enviados em partes de 8 MB.</p>
      {err && <p role="alert" className="mt-2 text-danger">{err}</p>}
    </Dialog>
  );
}

// ------------------------------------------------------------------ nova camada

const GEOMS: { v: GeomType; l: string }[] = [
  { v: "Point", l: "Ponto" }, { v: "LineString", l: "Linha" }, { v: "Polygon", l: "Polígono" },
  { v: "MultiPoint", l: "Multiponto" }, { v: "MultiLineString", l: "Multilinha" }, { v: "MultiPolygon", l: "Multipolígono" },
];
const TYPES: { v: FieldType; l: string }[] = [
  { v: "text", l: "Texto" }, { v: "integer", l: "Inteiro" }, { v: "real", l: "Decimal" },
  { v: "boolean", l: "Sim/não" }, { v: "date", l: "Data" }, { v: "datetime", l: "Data e hora" },
];

function NewLayerDialog({ onClose }: { onClose: () => void }) {
  const ws = useWorkspace();
  const [nome, setNome] = useState("");
  const [geometria, setGeometria] = useState<GeomType>("Polygon");
  const [crs, setCrs] = useState(ws.project!.crs);
  const [campos, setCampos] = useState<{ nome: string; tipo: FieldType }[]>([{ nome: "nome", tipo: "text" }]);
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => Api.createLayer(ws.project!.id, { nome: nome.trim(), geometria, crs, campos: campos.filter((c) => c.nome.trim()) }),
    onSuccess: (l) => { ws.upsertLayer(l); ws.setActiveLayer(l.id); ws.toast(`Camada "${l.nome}" criada. Use Editar para desenhar.`, "ok"); onClose(); },
    onError: (e) => setErr((e as Error).message),
  });
  return (
    <Dialog title="Nova camada vetorial" onClose={onClose} width={500} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" disabled={!nome.trim() || m.isPending} onClick={() => m.mutate()}>Criar camada</Button>
    </>}>
      <Field label="Nome"><input className="w-full h-8" value={nome} onChange={(e) => setNome(e.target.value)} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Tipo de geometria"><select className="w-full h-8" value={geometria} onChange={(e) => setGeometria(e.target.value as GeomType)}>
          {GEOMS.map((g) => <option key={g.v} value={g.v}>{g.l}</option>)}</select></Field>
        <Field label="Sistema de referência"><CrsPicker value={crs} onChange={setCrs} /></Field>
      </div>
      <p className="mb-1 text-[12px] text-muted">Campos</p>
      {campos.map((c, i) => (
        <div key={i} className="mb-1.5 flex gap-2">
          <input className="h-7 flex-1" placeholder="nome do campo" value={c.nome} aria-label="Nome do campo"
            onChange={(e) => setCampos(campos.map((x, j) => j === i ? { ...x, nome: e.target.value } : x))} />
          <select className="h-7" value={c.tipo} aria-label="Tipo do campo" onChange={(e) => setCampos(campos.map((x, j) => j === i ? { ...x, tipo: e.target.value as FieldType } : x))}>
            {TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
          </select>
          <IconButton label="Remover campo" onClick={() => setCampos(campos.filter((_, j) => j !== i))}><Trash2 size={13} /></IconButton>
        </div>
      ))}
      <Button variant="ghost" onClick={() => setCampos([...campos, { nome: "", tipo: "text" }])}>Adicionar campo</Button>
      {err && <p role="alert" className="mt-2 text-danger">{err}</p>}
    </Dialog>
  );
}

// ------------------------------------------------------------------ atributos da feição desenhada

function NewFeatureDialog({ geometry, onClose }: { geometry: GeoJSON.Geometry; onClose: () => void }) {
  const ws = useWorkspace();
  const layer = ws.layers.find((l) => l.id === ws.editLayerId);
  const [vals, setVals] = useState<Record<string, string>>({});
  if (!layer) return null;
  const confirm = () => {
    const attrs: Record<string, unknown> = {};
    for (const c of layer.campos) {
      const raw = vals[c.nome];
      if (raw === undefined || raw === "") continue;
      attrs[c.nome] = c.tipo === "integer" ? Number(raw) : c.tipo === "real" ? Number(raw.replace(",", "."))
        : c.tipo === "boolean" ? raw === "sim" : raw;
    }
    createFeature(geometry, attrs);
    onClose();
  };
  return (
    <Dialog title={`Nova feição · ${layer.nome}`} onClose={onClose} width={420} footer={<>
      <Button onClick={onClose}>Descartar desenho</Button>
      <Button variant="edit" onClick={confirm}>Adicionar feição</Button>
    </>}>
      {layer.campos.length === 0 && <p className="text-muted">A camada não tem campos de atributos.</p>}
      <form onSubmit={(e) => { e.preventDefault(); confirm(); }}>
        {layer.campos.map((c) => (
          <Field key={c.nome} label={c.nome}>
            {c.tipo === "boolean" ? (
              <select className="w-full h-8" value={vals[c.nome] ?? ""} onChange={(e) => setVals({ ...vals, [c.nome]: e.target.value })}>
                <option value="">nulo</option><option value="sim">sim</option><option value="não">não</option>
              </select>
            ) : (
              <input className="w-full h-8" value={vals[c.nome] ?? ""}
                type={c.tipo === "date" ? "date" : c.tipo === "datetime" ? "datetime-local" : c.tipo === "text" ? "text" : "number"}
                step={c.tipo === "integer" ? 1 : "any"} onChange={(e) => setVals({ ...vals, [c.nome]: e.target.value })} />
            )}
          </Field>
        ))}
        <button type="submit" className="sr-only">Adicionar</button>
      </form>
      <p className="text-[12px] text-muted">A feição fica pendente até você salvar as edições.</p>
    </Dialog>
  );
}

// ------------------------------------------------------------------ serviços

function ServiceDialog({ onClose }: { onClose: () => void }) {
  const ws = useWorkspace();
  const [tipo, setTipo] = useState<ServiceLayer["tipo"]>("wms");
  const [nome, setNome] = useState("");
  const [url, setUrl] = useState("");
  const [camadas, setCamadas] = useState("");
  const examples: Record<ServiceLayer["tipo"], string> = {
    wms: "https://geoservicos.ibge.gov.br/geoserver/ows",
    wmts: "https://servidor/wmts?SERVICE=WMTS&REQUEST=GetCapabilities",
    xyz: "https://servidor/tiles/{z}/{x}/{y}.png",
  };
  return (
    <Dialog title="Adicionar serviço de mapas" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" disabled={!url.trim() || (tipo !== "xyz" && !camadas.trim())} onClick={() => {
        ws.setServices([...ws.services, { id: crypto.randomUUID(), tipo, nome: nome.trim() || camadas || tipo.toUpperCase(), url: url.trim(), camadas: camadas.trim(), visivel: true, opacidade: 1 }]);
        onClose();
      }}>Adicionar serviço</Button>
    </>}>
      <Field label="Tipo"><select className="w-full h-8" value={tipo} onChange={(e) => setTipo(e.target.value as ServiceLayer["tipo"])}>
        <option value="wms">WMS</option><option value="wmts">WMTS (GetCapabilities)</option><option value="xyz">XYZ (tiles)</option></select></Field>
      <Field label="Endereço" hint={`Exemplo: ${examples[tipo]}`}><input className="w-full h-8" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
      {tipo !== "xyz" && <Field label={tipo === "wms" ? "Camadas (LAYERS)" : "Identificador da camada"}><input className="w-full h-8" value={camadas} onChange={(e) => setCamadas(e.target.value)} /></Field>}
      <Field label="Nome na lista (opcional)"><input className="w-full h-8" value={nome} onChange={(e) => setNome(e.target.value)} /></Field>
      <p className="text-[12px] text-muted">O servidor do serviço precisa permitir acesso a partir do navegador (CORS). Serviços externos são somente visualização.</p>
    </Dialog>
  );
}

// ------------------------------------------------------------------ exportação

function ExportDialog({ layerId, onClose, onJobStarted }: { layerId: string; onClose: () => void; onJobStarted: (j: Job) => void }) {
  const ws = useWorkspace();
  const layer = ws.layers.find((l) => l.id === layerId);
  const options = layer?.tipo === "raster" ? [{ v: "geotiff", l: "GeoTIFF (COG)" }] : [
    { v: "gpkg", l: "GeoPackage" }, { v: "shp", l: "Shapefile (zip)" }, { v: "geojson", l: "GeoJSON (WGS 84)" }, { v: "csv", l: "CSV com WKT" },
  ];
  const [fmt, setFmt] = useState(options[0].v);
  const m = useMutation({
    mutationFn: () => Api.exportLayer(layerId, fmt),
    onSuccess: (j) => { onJobStarted(j); ws.toast("Exportação iniciada. O link de download aparece em Processamentos."); onClose(); },
    onError: (e) => ws.toast((e as Error).message, "erro"),
  });
  if (!layer) return null;
  return (
    <Dialog title={`Exportar · ${layer.nome}`} onClose={onClose} width={400} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" disabled={m.isPending} onClick={() => m.mutate()}>{ws.t("acao.exportar")}</Button>
    </>}>
      {options.map((o) => (
        <label key={o.v} className="flex items-center gap-2 py-1"><input type="radio" name="fmt" checked={fmt === o.v} onChange={() => setFmt(o.v)} />{o.l}</label>
      ))}
      {ws.editLayerId === layerId && <p className="mt-2 text-edit">Edições ainda não salvas não entram na exportação.</p>}
      <p className="mt-2 text-[12px] text-muted">O link de download é temporário (15 minutos) e pode ser gerado de novo.</p>
    </Dialog>
  );
}

// ------------------------------------------------------------------ propriedades e estilo

function PropertiesDialog({ layerId, onClose }: { layerId: string; onClose: () => void }) {
  const ws = useWorkspace();
  const layer = ws.layers.find((l) => l.id === layerId);
  const { data: info } = useQuery({ queryKey: ["layer", layerId, layer?.versao], queryFn: () => Api.layer(layerId) });
  const [tab, setTab] = useState<"estilo" | "info" | "crs" | "historico">("estilo");
  const { data: hist } = useQuery({ queryKey: ["hist", layerId, layer?.versao], queryFn: () => Api.editHistory(layerId), enabled: tab === "historico" });
  const [crs, setCrs] = useState("EPSG:4326");
  const [err, setErr] = useState<string | null>(null);
  const editable = canEdit(ws.project);
  if (!layer) return null;
  const d = layer.exibicao!;
  const st = d?.estilo ?? {};
  const setStyle = (patch: Record<string, unknown>) => ws.updateDisplay(layer.id, { estilo: patch });

  return (
    <Dialog title={`Propriedades · ${layer.nome}`} onClose={onClose} width={540}>
      <div className="mb-3 flex gap-3 border-b border-line">
        {(["estilo", "info", "crs", "historico"] as const).filter((t) => layer.tipo === "vetorial" || t !== "historico").map((t) => (
          <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t}
            className={`-mb-px border-b-2 pb-1.5 ${tab === t ? "border-select font-semibold" : "border-transparent text-muted"}`}>
            {{ estilo: "Simbologia", info: "Informações", crs: "Sistema de referência", historico: "Histórico de edições" }[t]}
          </button>
        ))}
      </div>
      {tab === "estilo" && (
        <div>
          <Field label={`Opacidade da camada: ${Math.round((d?.opacidade ?? 1) * 100)}%`}>
            <input type="range" min={0} max={1} step={0.05} className="w-full" value={d?.opacidade ?? 1} onChange={(e) => ws.updateDisplay(layer.id, { opacidade: Number(e.target.value) })} />
          </Field>
          <Field label="Grupo" hint="Camadas com o mesmo grupo aparecem juntas no painel."><input className="w-full h-8" value={d?.grupo ?? ""} placeholder="sem grupo"
            onChange={(e) => ws.updateDisplay(layer.id, { grupo: e.target.value || null })} /></Field>
          {layer.tipo === "vetorial" ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Cor"><input type="color" className="h-8 w-full p-0.5" value={st.cor || colorForId(layer.id)} onChange={(e) => setStyle({ cor: e.target.value })} /></Field>
              <Field label={`Espessura da linha: ${st.largura ?? 1.6} px`}><input type="range" min={0.5} max={8} step={0.5} className="w-full" value={st.largura ?? 1.6} onChange={(e) => setStyle({ largura: Number(e.target.value) })} /></Field>
              {!layer.geometria?.includes("Point") && !layer.geometria?.includes("Line") && (
                <Field label={`Preenchimento: ${Math.round((st.opacidade_preenchimento ?? 0.25) * 100)}%`}><input type="range" min={0} max={1} step={0.05} className="w-full" value={st.opacidade_preenchimento ?? 0.25} onChange={(e) => setStyle({ opacidade_preenchimento: Number(e.target.value) })} /></Field>
              )}
              {layer.geometria?.includes("Point") && (
                <Field label={`Tamanho do ponto: ${st.raio ?? 5} px`}><input type="range" min={2} max={14} step={1} className="w-full" value={st.raio ?? 5} onChange={(e) => setStyle({ raio: Number(e.target.value) })} /></Field>
              )}
            </div>
          ) : (
            <RasterStyle layer={layer} />
          )}
          <p className="mt-1 text-[12px] text-muted">Simbologia categorizada, graduada e rótulos: {ws.t("indisponivel").toLowerCase()} (Fase 2).</p>
        </div>
      )}
      {tab === "info" && (
        <table className="w-full"><tbody>
          {([
            ["Tipo", layer.tipo === "raster" ? "Raster" : `Vetorial · ${layer.geometria}`],
            ["Sistema de referência", info?.crs_info ? `${info.crs_info.codigo ?? ""} ${info.crs_info.nome}` : "indefinido"],
            ["Datum", info?.crs_info?.datum ?? "—"],
            ...(layer.tipo === "vetorial" ? [["Feições", layer.feicoes.toLocaleString("pt-BR")], ["Campos", layer.campos.map((c) => c.nome).join(", ") || "—"]] : [
              ["Dimensões", `${layer.raster?.largura} × ${layer.raster?.altura} px`],
              ["Resolução", layer.raster?.resolucao?.map((r) => r.toLocaleString("pt-BR", { maximumFractionDigits: 6 })).join(" × ")],
              ["Bandas", `${layer.raster?.bandas} (${layer.raster?.tipo_dado})`], ["NoData", String(layer.raster?.nodata ?? "não definido")],
            ]),
            ["Extensão (WGS 84)", layer.bbox?.map((v) => v.toFixed(6)).join(", ") ?? "—"],
            ["Versão", String(layer.versao)], ["Identificador", layer.id],
          ] as [string, string][]).map(([k, v]) => <tr key={k}><td className="py-1 pr-3 align-top text-muted">{k}</td><td className="break-all tabular">{v}</td></tr>)}
        </tbody></table>
      )}
      {tab === "crs" && (
        <div>
          <p className="mb-3">Atual: <strong>{layer.crs ?? "indefinido"}</strong>{info?.crs_info ? ` · ${info.crs_info.nome}` : ""}</p>
          {layer.tipo === "vetorial" ? (<>
            <p className="mb-2 text-[12px] text-muted">Definir o CRS só corrige a informação, sem mover coordenadas. Use quando o arquivo veio sem .prj ou com CRS errado. Para converter as coordenadas, use a ferramenta Reprojetar camada.</p>
            <Field label="Definir como"><CrsPicker value={crs} onChange={setCrs} /></Field>
            {err && <p role="alert" className="mb-2 text-danger">{err}</p>}
            <div className="flex gap-2">
              <Button variant="primary" disabled={!editable || ws.editLayerId === layer.id} onClick={async () => {
                try { setErr(null); ws.upsertLayer(await Api.defineCrs(layer.id, crs)); ws.toast(`CRS definido como ${crs}.`, "ok"); }
                catch (e) { setErr((e as Error).message); }
              }}>Definir CRS</Button>
              <Button onClick={() => { ws.openTool("vector.reproject"); onClose(); }} disabled={!layer.crs || !editable}>Reprojetar camada…</Button>
            </div>
          </>) : <p className="text-muted">Reprojetar raster: {ws.t("indisponivel").toLowerCase()} (Fase 2).</p>}
        </div>
      )}
      {tab === "historico" && (
        <div className="max-h-80 overflow-auto">
          {!hist?.length && <p className="text-muted">Nenhuma edição registrada.</p>}
          <table className="w-full tabular"><tbody>
            {hist?.map((h) => (
              <tr key={h.id} className="border-b border-line/50">
                <td className="py-1 pr-2 text-muted">{new Date(h.quando).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</td>
                <td className="pr-2"><Badge tone={h.operacao === "delete" ? "danger" : h.operacao === "insert" ? "ok" : "edit"}>
                  {{ insert: "criou", update: "alterou", delete: "excluiu" }[h.operacao as "insert"]}</Badge></td>
                <td className="pr-2">fid {h.fid}</td><td className="text-muted">{h.usuario}</td><td className="text-muted">v{h.versao}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      )}
    </Dialog>
  );
}

function RasterStyle({ layer }: { layer: Layer }) {
  const ws = useWorkspace();
  const st = layer.exibicao?.estilo ?? {};
  const n = layer.raster?.bandas ?? 1;
  const bands = st.bandas ?? (n >= 3 ? [1, 2, 3] : [1]);
  const mode = bands.length === 3 ? "rgb" : "single";
  const desc = (b: number) => layer.raster?.estatisticas?.[b - 1]?.descricao;
  const opts = Array.from({ length: n }, (_, i) => i + 1);
  const set = (patch: Record<string, unknown>) => ws.updateDisplay(layer.id, { estilo: patch });
  return (
    <div>
      <Field label="Renderização">
        <select className="w-full h-8" value={mode} onChange={(e) => set({ bandas: e.target.value === "rgb" ? [1, 2, 3].map((b) => Math.min(b, n)) : [1] })}>
          {n >= 3 && <option value="rgb">Composição colorida (RGB)</option>}
          <option value="single">Banda única</option>
        </select>
      </Field>
      <div className="grid grid-cols-3 gap-2">
        {(mode === "rgb" ? ["Vermelho", "Verde", "Azul"] : ["Banda"]).map((lbl, i) => (
          <Field key={lbl} label={lbl}>
            <select className="w-full h-8" value={bands[i]} onChange={(e) => { const b = [...bands]; b[i] = Number(e.target.value); set({ bandas: b }); }}>
              {opts.map((b) => <option key={b} value={b}>Banda {b}{desc(b) ? ` (${desc(b)})` : ""}</option>)}
            </select>
          </Field>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {mode === "single" && (
          <Field label="Paleta"><select className="w-full h-8" value={st.paleta ?? "cinza"} onChange={(e) => set({ paleta: e.target.value })}>
            {["cinza", "viridis", "terrain", "rdylgn", "magma", "spectral"].map((p) => <option key={p}>{p}</option>)}</select></Field>
        )}
        <Field label="Realce de contraste"><select className="w-full h-8" value={st.realce ?? "percentil"} onChange={(e) => set({ realce: e.target.value })}>
          <option value="percentil">Corte 2%–98%</option><option value="minmax">Mínimo–máximo</option></select></Field>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ demais

function DeleteLayerDialog({ layerId, onClose }: { layerId: string; onClose: () => void }) {
  const ws = useWorkspace();
  const layer = ws.layers.find((l) => l.id === layerId);
  const m = useMutation({
    mutationFn: () => Api.deleteLayer(layerId),
    onSuccess: () => { ws.removeLayer(layerId); ws.toast("Camada removida.", "ok"); onClose(); },
    onError: (e) => ws.toast((e as Error).message, "erro"),
  });
  if (!layer) return null;
  return (
    <Dialog title="Remover camada" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="danger" disabled={m.isPending} onClick={() => m.mutate()}>Remover camada</Button>
    </>}>
      <p>A camada <strong>{layer.nome}</strong> e seus dados serão excluídos do projeto. Esta ação não pode ser desfeita.</p>
    </Dialog>
  );
}

function ShareDialog({ onClose }: { onClose: () => void }) {
  const ws = useWorkspace();
  const qc = useQueryClient();
  const pid = ws.project!.id;
  const owner = ws.project!.papel === "owner";
  const { data } = useQuery({ queryKey: ["members", pid], queryFn: () => Api.members(pid) });
  const [email, setEmail] = useState("");
  const [papel, setPapel] = useState("editor");
  const [err, setErr] = useState<string | null>(null);
  const label = useMemo(() => ({ owner: "Dono", editor: "Editor", viewer: "Leitura" } as Record<string, string>), []);
  return (
    <Dialog title="Compartilhar projeto" onClose={onClose} width={480}>
      <ul className="mb-3">
        {data?.map((m) => (
          <li key={m.id} className="flex items-center gap-2 border-b border-line/60 py-1.5">
            <span className="flex-1">{m.email}</span><Badge>{label[m.papel]}</Badge>
            {owner && m.papel !== "owner" && <IconButton label={`Remover ${m.email}`} onClick={async () => {
              await Api.removeMember(pid, m.id); qc.invalidateQueries({ queryKey: ["members", pid] });
            }}><Trash2 size={13} /></IconButton>}
          </li>
        ))}
      </ul>
      {owner ? (
        <div className="flex gap-2">
          <input className="h-8 flex-1" type="email" placeholder="e-mail da pessoa" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="E-mail" />
          <select className="h-8" value={papel} onChange={(e) => setPapel(e.target.value)} aria-label="Papel">
            <option value="editor">Editor</option><option value="viewer">Leitura</option></select>
          <Button variant="primary" className="h-8" disabled={!email.includes("@")} onClick={async () => {
            try { setErr(null); await Api.addMember(pid, email, papel); setEmail(""); qc.invalidateQueries({ queryKey: ["members", pid] }); }
            catch (e) { setErr((e as Error).message); }
          }}>Convidar</Button>
        </div>
      ) : <p className="text-muted">Somente o dono do projeto gerencia o acesso.</p>}
      {err && <p role="alert" className="mt-2 text-danger">{err}</p>}
      <p className="mt-3 text-[12px] text-muted">A pessoa precisa ter entrado na plataforma ao menos uma vez. Editores alteram dados; leitura só visualiza e exporta.</p>
    </Dialog>
  );
}

function ProjectCrsDialog({ onClose }: { onClose: () => void }) {
  const ws = useWorkspace();
  const [crs, setCrs] = useState(ws.project!.crs);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog title="Sistema de referência do projeto" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" onClick={async () => {
        try { const p = await Api.patchProject(ws.project!.id, { crs }); useWorkspace.setState({ project: { ...ws.project!, crs: p.crs } }); onClose(); }
        catch (e) { setErr((e as Error).message); }
      }}>Aplicar</Button>
    </>}>
      <Field label="CRS" hint="Usado em novas camadas e na leitura de coordenadas da barra de status. O mapa é exibido em Web Mercator e as camadas são reprojetadas na visualização.">
        <CrsPicker value={crs} onChange={setCrs} />
      </Field>
      {err && <p role="alert" className="text-danger">{err}</p>}
    </Dialog>
  );
}

const SHORTCUTS: [string, string][] = [
  ["Ctrl+E", "Editar a camada ativa / parar edição"], ["Ctrl+S", "Salvar edições"], ["Ctrl+Z", "Desfazer"],
  ["Ctrl+Shift+Z ou Ctrl+Y", "Refazer"], ["Del", "Excluir feições selecionadas (em edição)"],
  ["A", "Adicionar feição (em edição)"], ["V", "Editar vértices (em edição)"], ["G", "Mover feições (em edição)"],
  ["Alt+clique no vértice", "Remover vértice"], ["Esc", "Cancelar desenho, limpar seleção, fechar diálogo"],
  ["I", "Identificar"], ["S", "Selecionar por clique"], ["M", "Medir distância"], ["C", "Consultar coordenadas"],
  ["Ctrl+I", "Importar dados"], ["Ctrl+T", "Tabela de atributos"], ["?", "Esta lista"],
];

function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Atalhos de teclado" onClose={onClose} width={440}>
      <table className="w-full"><tbody>
        {SHORTCUTS.map(([k, v]) => <tr key={k}><td className="py-1 pr-4 whitespace-nowrap"><kbd className="rounded border border-line bg-panel-2 px-1.5 text-[11.5px]">{k}</kbd></td><td>{v}</td></tr>)}
      </tbody></table>
    </Dialog>
  );
}

function AboutDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Sobre esta versão" onClose={onClose} width={480}>
      <p className="mb-2"><strong>FS Geotecnologias · WebGIS</strong> — Fase 1 (MVP).</p>
      <p className="mb-2">Disponível: importação de GeoJSON, Shapefile, GeoPackage e GeoTIFF; editor vetorial com snapping, desfazer/refazer e salvamento transacional; tabela de atributos; 10 ferramentas vetoriais executadas no PostGIS; exportação com link temporário.</p>
      <p className="text-muted">Ferramentas e menus marcados como “Indisponível” ainda não foram implementados e não executam nada.</p>
    </Dialog>
  );
}
