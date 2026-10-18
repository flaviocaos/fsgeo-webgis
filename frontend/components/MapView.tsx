"use client";
import { X } from "lucide-react";
import OLMap from "ol/Map";
import View from "ol/View";
import Feature from "ol/Feature";
import Overlay from "ol/Overlay";
import GeoJSON from "ol/format/GeoJSON";
import type { Geometry as OLGeometry } from "ol/geom";
import { LineString, Polygon } from "ol/geom";
import Graticule from "ol/layer/Graticule";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import VectorTileLayer from "ol/layer/VectorTile";
import type BaseLayer from "ol/layer/Base";
import OSM from "ol/source/OSM";
import VectorSource from "ol/source/Vector";
import XYZ from "ol/source/XYZ";
import { DragBox, Draw, Modify, Select, Snap, Translate } from "ol/interaction";
import { defaults as defaultInteractions } from "ol/interaction/defaults";
import { platformModifierKeyOnly, shiftKeyOnly, altKeyOnly, click } from "ol/events/condition";
import { ScaleLine, Attribution } from "ol/control";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj";
import { getArea, getLength } from "ol/sphere";
import { Stroke } from "ol/style";
import { unByKey } from "ol/Observable";
import { useEffect, useRef, useState } from "react";
import { Api } from "@/lib/api";
import { config } from "@/lib/config";
import { fidKey } from "@/lib/edit/session";
import { MapLibreLayer } from "@/lib/map/maplibreLayer";
import { formatCoord, fromLonLat4326, ensureProjection, toDMS } from "@/lib/map/proj";
import { rasterTileSource, vectorTileSource, wmsSource, wmtsSource, xyzSource } from "@/lib/map/sources";
import { colorForId, editStyle, measureStyle, vectorStyle } from "@/lib/map/styles";
import type { Layer } from "@/lib/types";
import { useWorkspace } from "@/stores/workspace";

const gj = new GeoJSON({ dataProjection: "EPSG:4326", featureProjection: "EPSG:3857" });
const EDIT_LOAD_LIMIT = 5000;

export type DrawnGeometry = GeoJSON.Geometry;

interface IdentifyResult { at: [number, number]; items: { layer: string; content: any }[] }

export function geomToGeoJSON(g: OLGeometry): GeoJSON.Geometry {
  return gj.writeGeometryObject(g) as GeoJSON.Geometry;
}

function toMulti(g: GeoJSON.Geometry, layerType: string | null): GeoJSON.Geometry {
  if (layerType?.startsWith("Multi") && !g.type.startsWith("Multi") && g.type !== "GeometryCollection") {
    return { type: `Multi${g.type}`, coordinates: [(g as any).coordinates] } as GeoJSON.Geometry;
  }
  return g;
}

function sirgasUtm(lon: number, lat: number): string {
  const zone = Math.floor((lon + 180) / 6) + 1;
  if (lat < 0 && zone >= 17 && zone <= 25) return `EPSG:${31960 + zone}`;
  if (lat >= 0 && zone >= 17 && zone <= 22) return `EPSG:${31954 + zone}`;
  return `EPSG:${(lat < 0 ? 32700 : 32600) + zone}`;
}

export default function MapView({ onDrawEnd }: { onDrawEnd: (g: DrawnGeometry) => void }) {
  const target = useRef<HTMLDivElement>(null);
  const mapRef = useRef<OLMap | null>(null);
  const dataLayers = useRef(new Map<string, { layer: BaseLayer; sig: string }>());
  const serviceLayers = useRef(new Map<string, { layer: TileLayer<any>; sig: string }>());
  const basemapLayer = useRef<BaseLayer | null>(null);
  const graticule = useRef<Graticule | null>(null);
  const editSource = useRef(new VectorSource());
  const editLayer = useRef<VectorLayer | null>(null);
  const snapSource = useRef(new VectorSource());
  const measureSource = useRef(new VectorSource());
  const drawCb = useRef(onDrawEnd);
  drawCb.current = onDrawEnd;
  const [identify, setIdentify] = useState<IdentifyResult | null>(null);
  const [coords, setCoords] = useState<{ lon: number; lat: number; rows: [string, string][] } | null>(null);

  const s = useWorkspace;
  const layers = useWorkspace((st) => st.layers);
  const services = useWorkspace((st) => st.services);
  const basemap = useWorkspace((st) => st.basemap);
  const selection = useWorkspace((st) => st.selection);
  const tool = useWorkspace((st) => st.tool);
  const editLayerId = useWorkspace((st) => st.editLayerId);
  const editTool = useWorkspace((st) => st.editTool);
  const editTick = useWorkspace((st) => st.editTick);
  const editSelected = useWorkspace((st) => st.editSelected);
  const snapping = useWorkspace((st) => st.snapping);
  const showGraticule = useWorkspace((st) => st.showGraticule);
  const zoomRequest = useWorkspace((st) => st.zoomRequest);
  const theme = useWorkspace((st) => st.theme);

  // ---------------------------------------------------------------- criação do mapa
  useEffect(() => {
    const st = s.getState();
    const vista = st.project?.estado?.vista;
    const map = new OLMap({
      target: target.current!,
      controls: [new ScaleLine({ units: "metric", bar: false }), new Attribution({ collapsible: true })],
      interactions: defaultInteractions({ doubleClickZoom: false }),
      view: new View({
        center: fromLonLat(vista?.centro ?? [-51.9, -14.2]),
        zoom: vista?.zoom ?? 4.2,
        maxZoom: 23,
      }),
    });
    mapRef.current = map;
    const el = new VectorLayer({ source: editSource.current, zIndex: 900 });
    editLayer.current = el;
    map.addLayer(el);
    map.addLayer(new VectorLayer({ source: measureSource.current, style: measureStyle, zIndex: 950 }));

    const updateView = () => {
      const v = map.getView();
      const res = v.getResolution() ?? 1;
      const center = toLonLat(v.getCenter()!);
      const groundRes = res * Math.cos((center[1] * Math.PI) / 180);
      s.getState().setView(groundRes, groundRes / 0.00028);
    };
    map.on("moveend", updateView);
    updateView();
    map.on("pointermove", (e) => {
      if (e.dragging) return;
      const [lon, lat] = toLonLat(e.coordinate);
      s.getState().setCursor({ lon, lat });
    });
    map.getViewport()?.addEventListener("mouseleave", () => s.getState().setCursor(null));

    // Sem vista salva: enquadra todas as camadas do projeto.
    if (!vista) {
      const boxes = st.layers.map((l) => l.bbox).filter(Boolean) as number[][];
      if (boxes.length) {
        const ext = [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])),
          Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))];
        map.getView().fit(transformExtent(ext, "EPSG:4326", "EPSG:3857"), { padding: [40, 40, 40, 40], maxZoom: 18 });
      }
    }
    (window as any).__webgisMap = map;
    return () => { map.setTarget(undefined); mapRef.current = null; dataLayers.current.clear(); serviceLayers.current.clear(); };
  }, [s]);

  // Salva a vista (centro/zoom) no estado do projeto quando o usuário para de mover o mapa.
  useEffect(() => {
    const map = mapRef.current!;
    let timer: ReturnType<typeof setTimeout>;
    const key = map.on("moveend", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const v = map.getView();
        const [lon, lat] = toLonLat(v.getCenter()!);
        s.getState().setVista({ centro: [lon, lat], zoom: v.getZoom() ?? 4 });
      }, 1200);
    });
    return () => { unByKey(key); clearTimeout(timer); };
  }, [s]);

  // ---------------------------------------------------------------- mapa-base
  useEffect(() => {
    const map = mapRef.current!;
    if (basemapLayer.current) map.removeLayer(basemapLayer.current);
    basemapLayer.current = null;
    let layer: BaseLayer | null = null;
    if (basemap === "osm-vetorial") {
      layer = new MapLibreLayer(config.basemapStyleUrl, '© <a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>');
    } else if (basemap === "osm") {
      layer = new TileLayer({ source: new OSM() });
    } else if (basemap === "satelite" && config.satelliteUrl) {
      layer = new TileLayer({ source: new XYZ({ url: config.satelliteUrl, attributions: config.satelliteAttribution, maxZoom: 20, crossOrigin: "anonymous" }) });
    }
    if (layer) {
      layer.setZIndex(-1);
      map.addLayer(layer);
      basemapLayer.current = layer;
    }
  }, [basemap]);

  // ---------------------------------------------------------------- camadas de dados
  useEffect(() => {
    const map = mapRef.current!;
    const present = new Set<string>();
    const n = layers.length;
    layers.forEach((l, idx) => {
      present.add(l.id);
      const d = l.exibicao;
      const st = d?.estilo ?? {};
      const sig = l.tipo === "raster"
        ? `${l.versao}|${JSON.stringify([st.bandas, st.paleta, st.realce])}`
        : `${l.versao}|${JSON.stringify(st)}`;
      let entry = dataLayers.current.get(l.id);
      if (!entry || entry.sig !== sig) {
        if (entry) map.removeLayer(entry.layer);
        const layer = createDataLayer(l, () => new Set(s.getState().selection[l.id] ?? []));
        if (!layer) return;
        map.addLayer(layer);
        entry = { layer, sig };
        dataLayers.current.set(l.id, entry);
      }
      entry.layer.setZIndex(10 + (n - idx));
      entry.layer.setOpacity(d?.opacidade ?? 1);
      entry.layer.setVisible((d?.visivel ?? true) && l.id !== editLayerId);
    });
    for (const [id, e] of dataLayers.current) {
      if (!present.has(id)) { map.removeLayer(e.layer); dataLayers.current.delete(id); }
    }
  }, [layers, editLayerId, s]);

  // Realce de seleção: só redesenha.
  useEffect(() => {
    for (const e of dataLayers.current.values()) e.layer.changed();
  }, [selection]);

  // ---------------------------------------------------------------- serviços WMS/WMTS/XYZ
  useEffect(() => {
    const map = mapRef.current!;
    const present = new Set<string>();
    services.forEach((sv, i) => {
      present.add(sv.id);
      const sig = `${sv.tipo}|${sv.url}|${sv.camadas}`;
      let entry = serviceLayers.current.get(sv.id);
      if (!entry || entry.sig !== sig) {
        if (entry) map.removeLayer(entry.layer);
        const layer = new TileLayer({ zIndex: 5 + i });
        if (sv.tipo === "wms") layer.setSource(wmsSource(sv));
        else if (sv.tipo === "xyz") layer.setSource(xyzSource(sv));
        else wmtsSource(sv).then((src) => layer.setSource(src)).catch((e) => s.getState().toast(`${sv.nome}: ${e.message}`, "erro"));
        map.addLayer(layer);
        entry = { layer, sig };
        serviceLayers.current.set(sv.id, entry);
      }
      entry.layer.setVisible(sv.visivel);
      entry.layer.setOpacity(sv.opacidade);
    });
    for (const [id, e] of serviceLayers.current) {
      if (!present.has(id)) { map.removeLayer(e.layer); serviceLayers.current.delete(id); }
    }
  }, [services, s]);

  // ---------------------------------------------------------------- grade de coordenadas
  useEffect(() => {
    const map = mapRef.current!;
    if (graticule.current) { map.removeLayer(graticule.current); graticule.current = null; }
    if (showGraticule) {
      const color = theme === "dark" ? "rgba(214,226,224,0.45)" : "rgba(21,38,44,0.4)";
      graticule.current = new Graticule({ strokeStyle: new Stroke({ color, width: 0.8, lineDash: [2, 4] }), showLabels: true, wrapX: false, zIndex: 800 });
      map.addLayer(graticule.current);
    }
  }, [showGraticule, theme]);

  // ---------------------------------------------------------------- pedidos de zoom
  useEffect(() => {
    if (!zoomRequest || !mapRef.current) return;
    const [w, so, e, n] = zoomRequest.extent4326;
    const ext = transformExtent([w, so, Math.max(e, w + 1e-6), Math.max(n, so + 1e-6)], "EPSG:4326", "EPSG:3857");
    mapRef.current.getView().fit(ext, { padding: [60, 60, 60, 60], maxZoom: 19, duration: 250 });
  }, [zoomRequest]);

  // ---------------------------------------------------------------- ferramentas de navegação
  useEffect(() => {
    const map = mapRef.current!;
    if (editLayerId) return;
    const keys: any[] = [];
    const interactions: any[] = [];
    const overlays: Overlay[] = [];
    const st = () => s.getState();
    const toleranceM = () => map.getView().getResolution()! * 6;

    if (tool === "identify") {
      keys.push(map.on("singleclick", async (e) => {
        const [lon, lat] = toLonLat(e.coordinate);
        const visible = st().layers.filter((l) => l.exibicao?.visivel !== false);
        const items: IdentifyResult["items"] = [];
        await Promise.all(visible.map(async (l) => {
          try {
            const r = await Api.identify(l.id, lon, lat, toleranceM());
            if ((r.feicoes && r.feicoes.length) || (r.valores && r.valores.length)) items.push({ layer: l.nome, content: r });
          } catch { /* camada sem CRS etc. */ }
        }));
        const order = visible.map((l) => l.nome);
        items.sort((a, b) => order.indexOf(a.layer) - order.indexOf(b.layer));
        setIdentify({ at: [lon, lat], items });
      }));
    }
    if (tool === "select") {
      keys.push(map.on("singleclick", async (e) => {
        const active = st().layers.find((l) => l.id === st().activeLayerId && l.tipo === "vetorial");
        if (!active) { st().toast("Escolha uma camada vetorial no painel de camadas para selecionar.", "info"); return; }
        const [lon, lat] = toLonLat(e.coordinate);
        const r = await Api.identify(active.id, lon, lat, toleranceM());
        const fids = (r.feicoes ?? []).slice(0, 1).map((f: any) => f.id);
        const mode = shiftKeyOnly(e as any) || platformModifierKeyOnly(e as any) ? "toggle" : "replace";
        st().setSelection(active.id, fids, mode);
      }));
    }
    if (tool === "select-box") {
      const box = new DragBox({ condition: () => true });
      box.on("boxend", async (ev) => {
        const active = st().layers.find((l) => l.id === st().activeLayerId && l.tipo === "vetorial");
        if (!active) { st().toast("Escolha uma camada vetorial no painel de camadas para selecionar.", "info"); return; }
        const ext = transformExtent(box.getGeometry().getExtent(), "EPSG:3857", "EPSG:4326");
        const r = await Api.select(active.id, { bbox: ext });
        st().setSelection(active.id, r.fids, (ev as any).mapBrowserEvent?.originalEvent?.shiftKey ? "add" : "replace");
        if (r.limite_atingido) st().toast("A seleção atingiu o limite de feições.", "info");
      });
      interactions.push(box);
    }
    if (tool === "measure-line" || tool === "measure-area") {
      const draw = new Draw({ source: measureSource.current, type: tool === "measure-line" ? "LineString" : "Polygon", style: measureStyle });
      let tip: Overlay | null = null;
      let listener: any;
      draw.on("drawstart", (ev) => {
        measureSource.current.clear();
        overlays.forEach((o) => map.removeOverlay(o));
        const el = document.createElement("div");
        el.className = "measure-tip";
        tip = new Overlay({ element: el, offset: [10, -10], positioning: "bottom-left" });
        map.addOverlay(tip);
        overlays.push(tip);
        listener = ev.feature.getGeometry()!.on("change", (ge) => {
          const g = ge.target as LineString | Polygon;
          if (g instanceof Polygon) {
            const a = getArea(g);
            el.textContent = a > 1e6 ? `${(a / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 3 })} km² · ${(a / 1e4).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ha`
              : `${a.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} m² · ${(a / 1e4).toLocaleString("pt-BR", { maximumFractionDigits: 4 })} ha`;
            tip!.setPosition(g.getInteriorPoint().getCoordinates());
          } else {
            const len = getLength(g);
            el.textContent = len > 1000 ? `${(len / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 3 })} km`
              : `${len.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} m`;
            tip!.setPosition(g.getLastCoordinate());
          }
        });
      });
      draw.on("drawend", () => unByKey(listener));
      interactions.push(draw);
    }
    if (tool === "coords") {
      keys.push(map.on("singleclick", async (e) => {
        const [lon, lat] = toLonLat(e.coordinate);
        const proj = st().project?.crs ?? "EPSG:4326";
        const utm = sirgasUtm(lon, lat);
        await Promise.all([ensureProjection(proj), ensureProjection(utm)]);
        const rows: [string, string][] = [
          ["WGS 84 (graus decimais)", `${formatCoord(lat, true)}, ${formatCoord(lon, true)}`],
          ["WGS 84 (GMS)", `${toDMS(lat, "lat")}  ${toDMS(lon, "lon")}`],
        ];
        for (const code of [proj, utm]) {
          if (code === "EPSG:4326") continue;
          const p = fromLonLat4326(code, lon, lat);
          if (p) rows.push([code, `${formatCoord(p[0], code === "EPSG:4674")} ; ${formatCoord(p[1], code === "EPSG:4674")}`]);
        }
        setCoords({ lon, lat, rows });
      }));
    }
    interactions.forEach((i) => map.addInteraction(i));
    return () => {
      keys.forEach(unByKey);
      interactions.forEach((i) => map.removeInteraction(i));
      overlays.forEach((o) => map.removeOverlay(o));
      if (!tool.startsWith("measure")) measureSource.current.clear();
    };
  }, [tool, editLayerId, s]);

  useEffect(() => {
    if (!tool.startsWith("measure")) measureSource.current.clear();
    if (tool !== "identify") setIdentify(null);
    if (tool !== "coords") setCoords(null);
  }, [tool]);

  // ---------------------------------------------------------------- edição: carga por extensão
  useEffect(() => {
    const map = mapRef.current!;
    if (!editLayerId) { editSource.current.clear(); snapSource.current.clear(); return; }
    let cancelled = false;
    const load = async () => {
      const st = s.getState();
      const session = st.editSession;
      if (!session) return;
      const ext = transformExtent(map.getView().calculateExtent(map.getSize()), "EPSG:3857", "EPSG:4326");
      const bbox = ext.map((v, i) => Math.max(i % 2 ? -90 : -180, Math.min(i % 2 ? 90 : 180, v))).join(",");
      try {
        const fc = await Api.features(editLayerId, { bbox, limite: EDIT_LOAD_LIMIT });
        if (cancelled) return;
        const added = session.load(fc.features.map((f) => ({ id: f.id, geometry: f.geometry, properties: f.properties })));
        if (added.length) st.bumpEdit();
        if ((fc.total ?? 0) > EDIT_LOAD_LIMIT) {
          st.toast(`Há ${fc.total!.toLocaleString("pt-BR")} feições nesta área; carregadas ${EDIT_LOAD_LIMIT.toLocaleString("pt-BR")}. Aproxime o mapa para editar as demais.`, "info");
        }
      } catch (e) {
        st.toast(`Não foi possível carregar feições para edição: ${(e as Error).message}`, "erro");
      }
    };
    load();
    const key = map.on("moveend", load);
    return () => { cancelled = true; unByKey(key); };
  }, [editLayerId, s]);

  // Feições de outras camadas para snapping (carregadas pela extensão visível).
  useEffect(() => {
    const map = mapRef.current!;
    snapSource.current.clear();
    if (!editLayerId || !snapping.ativo || !snapping.outrasCamadas) return;
    let cancelled = false;
    const load = async () => {
      const st = s.getState();
      const others = st.layers.filter((l) => l.tipo === "vetorial" && l.id !== editLayerId && l.exibicao?.visivel !== false && l.crs);
      const ext = transformExtent(map.getView().calculateExtent(map.getSize()), "EPSG:3857", "EPSG:4326");
      const bbox = ext.join(",");
      const feats: Feature[] = [];
      await Promise.all(others.map(async (l) => {
        try {
          const fc = await Api.features(l.id, { bbox, limite: 2000, contar: false });
          for (const f of fc.features) if (f.geometry) feats.push(new Feature(gj.readGeometry(f.geometry) ?? undefined));
        } catch { /* ignora camadas indisponíveis */ }
      }));
      if (cancelled) return;
      snapSource.current.clear();
      snapSource.current.addFeatures(feats);
    };
    load();
    const key = map.on("moveend", load);
    return () => { cancelled = true; unByKey(key); };
  }, [editLayerId, snapping.ativo, snapping.outrasCamadas, layers, s]);

  // Sincroniza a camada de edição com a sessão (após qualquer comando, desfazer ou refazer).
  useEffect(() => {
    const session = s.getState().editSession;
    const src = editSource.current;
    if (!session || !editLayerId) { src.clear(); return; }
    const wanted = new Map(session.all().map((f) => [f.key, f]));
    for (const f of src.getFeatures()) {
      const key = String(f.getId());
      const w = wanted.get(key);
      if (!w || !w.geometry) { src.removeFeature(f); continue; }
      const cur = JSON.stringify(geomToGeoJSON(f.getGeometry()!));
      if (cur !== JSON.stringify(w.geometry)) f.setGeometry(gj.readGeometry(w.geometry));
      wanted.delete(key);
    }
    for (const w of wanted.values()) {
      if (!w.geometry) continue;
      const f = new Feature(gj.readGeometry(w.geometry) ?? undefined);
      f.setId(w.key);
      src.addFeature(f);
    }
  }, [editTick, editLayerId, s]);

  useEffect(() => {
    const sel = () => new Set(s.getState().editSelected);
    editLayer.current?.setStyle(editStyle(sel));
    editLayer.current?.changed();
  }, [editSelected, theme, s]);

  // ---------------------------------------------------------------- edição: interações
  useEffect(() => {
    const map = mapRef.current!;
    if (!editLayerId) return;
    const st = () => s.getState();
    const layerInfo = st().layers.find((l) => l.id === editLayerId)!;
    const interactions: any[] = [];
    const cleanups: (() => void)[] = [];
    const before = new Map<string, GeoJSON.Geometry>();
    const capture = (features: Feature[]) => {
      before.clear();
      for (const f of features) before.set(String(f.getId()), geomToGeoJSON(f.getGeometry()!));
    };
    const commit = (features: Feature[], label: string) => {
      const changes = features.map((f) => ({ key: String(f.getId()), geometry: geomToGeoJSON(f.getGeometry()!) }))
        .filter((c) => JSON.stringify(before.get(c.key)) !== JSON.stringify(c.geometry));
      if (changes.length) { st().editSession!.setGeometries(changes, label); st().bumpEdit(); }
    };

    if (editTool === "draw") {
      const base = (layerInfo.geometria ?? "Point").replace("Multi", "") as "Point" | "LineString" | "Polygon";
      const draw = new Draw({ type: base, style: editStyle(() => new Set()) });
      draw.on("drawend", (e) => {
        const g = toMulti(geomToGeoJSON(e.feature.getGeometry()!), layerInfo.geometria);
        drawCb.current(g);
      });
      const abort = () => draw.abortDrawing();
      window.addEventListener("webgis:cancelar-desenho", abort);
      cleanups.push(() => window.removeEventListener("webgis:cancelar-desenho", abort));
      interactions.push(draw);
    } else {
      const select = new Select({
        layers: [editLayer.current!],
        style: null,
        condition: click,
        toggleCondition: shiftKeyOnly,
        hitTolerance: 4,
      });
      // Mantém a seleção do OpenLayers alinhada com a do estado global.
      const keys = new Set(st().editSelected);
      for (const f of editSource.current.getFeatures()) if (keys.has(String(f.getId()))) select.getFeatures().push(f);
      select.on("select", () => st().setEditSelected(select.getFeatures().getArray().map((f) => String(f.getId()))));
      interactions.push(select);

      if (editTool === "modify") {
        const modify = new Modify({
          source: editSource.current,
          deleteCondition: (e) => altKeyOnly(e) && click(e),
          pixelTolerance: 8,
        });
        modify.on("modifystart", (e) => capture(e.features.getArray() as Feature[]));
        modify.on("modifyend", (e) => commit(e.features.getArray() as Feature[], "Editar vértices"));
        interactions.push(modify);
      }
      if (editTool === "move") {
        const translate = new Translate({ features: select.getFeatures() });
        translate.on("translatestart", (e) => capture(e.features.getArray() as Feature[]));
        translate.on("translateend", (e) => commit(e.features.getArray() as Feature[], "Mover feições"));
        interactions.push(translate);
      }
    }
    if (snapping.ativo) {
      const opts = { pixelTolerance: snapping.tolerancia, vertex: snapping.vertices, edge: snapping.segmentos };
      interactions.push(new Snap({ source: editSource.current, ...opts }));
      if (snapping.outrasCamadas) interactions.push(new Snap({ source: snapSource.current, ...opts }));
    }
    interactions.forEach((i) => map.addInteraction(i));
    return () => { interactions.forEach((i) => map.removeInteraction(i)); cleanups.forEach((c) => c()); };
  }, [editLayerId, editTool, snapping, s]);

  return (
    <div className="relative h-full w-full neatline" style={{ background: "var(--map-bg)" }}>
      <div ref={target} className="absolute inset-[5px]" data-testid="mapa" />
      {identify && (
        <aside className="absolute right-3 top-3 z-10 max-h-[70%] w-80 overflow-auto rounded border border-line bg-panel shadow-xl" aria-label="Resultado da identificação">
          <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
            <span className="font-semibold">Identificar</span>
            <button aria-label="Fechar" className="text-muted hover:text-text" onClick={() => setIdentify(null)}><X size={14} /></button>
          </div>
          {identify.items.length === 0 && <p className="px-3 py-3 text-muted">Nenhuma feição ou pixel neste ponto.</p>}
          {identify.items.map((it, i) => (
            <div key={i} className="border-b border-line/60 px-3 py-2">
              <p className="mb-1 font-medium text-select">{it.layer}</p>
              {it.content.tipo === "raster" ? (
                <table className="w-full tabular">
                  <tbody>{it.content.valores.map((v: any) => (
                    <tr key={v.banda}><td className="text-muted">Banda {v.banda}</td><td className="text-right">{v.valor ?? "NoData"}</td></tr>
                  ))}</tbody>
                </table>
              ) : it.content.feicoes.map((f: any) => (
                <table key={f.id} className="mb-2 w-full">
                  <tbody>
                    <tr><td className="text-muted">fid</td><td className="tabular">{f.id}</td></tr>
                    {Object.entries(f.properties).map(([k, v]) => (
                      <tr key={k}><td className="pr-2 align-top text-muted">{k}</td><td className="break-all">{v === null ? <span className="text-muted">nulo</span> : typeof v === "boolean" ? (v ? "sim" : "não") : String(v)}</td></tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </div>
          ))}
        </aside>
      )}
      {coords && (
        <aside className="absolute right-3 top-3 z-10 w-96 rounded border border-line bg-panel shadow-xl" aria-label="Coordenadas do ponto">
          <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
            <span className="font-semibold">Coordenadas do ponto</span>
            <button aria-label="Fechar" className="text-muted hover:text-text" onClick={() => setCoords(null)}><X size={14} /></button>
          </div>
          <table className="m-2 w-[calc(100%-1rem)]">
            <tbody>{coords.rows.map(([k, v]) => (
              <tr key={k}><td className="py-0.5 pr-3 text-muted">{k}</td><td className="tabular select-all">{v}</td></tr>
            ))}</tbody>
          </table>
        </aside>
      )}
    </div>
  );
}

function createDataLayer(l: Layer, selected: () => Set<number>): BaseLayer | null {
  if (l.tipo === "raster") {
    return new TileLayer({ source: rasterTileSource(l) });
  }
  if (!l.crs) return null;
  return new VectorTileLayer({
    source: vectorTileSource(l),
    style: vectorStyle(l.exibicao?.estilo ?? {}, colorForId(l.id), selected),
    declutter: false,
    renderMode: "hybrid",
  });
}

export { fidKey };
