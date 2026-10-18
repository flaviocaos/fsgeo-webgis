"use client";
import type ImageTile from "ol/ImageTile";
import MVT from "ol/format/MVT";
import type VectorTile from "ol/VectorTile";
import TileWMS from "ol/source/TileWMS";
import VectorTileSource from "ol/source/VectorTile";
import WMTS, { optionsFromCapabilities } from "ol/source/WMTS";
import XYZ from "ol/source/XYZ";
import WMTSCapabilities from "ol/format/WMTSCapabilities";
import { api, authHeaders } from "../api";
import type { Layer, ServiceLayer } from "../types";

const EMPTY_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

/** Tiles vetoriais (MVT) da API, com o token no cabeçalho. A versão na URL invalida o cache após edições. */
export function vectorTileSource(layer: Layer): VectorTileSource {
  return new VectorTileSource({
    format: new MVT(),
    url: `${api}/layers/${layer.id}/tiles/{z}/{x}/{y}.pbf?v=${layer.versao}`,
    maxZoom: 22,
    tileLoadFunction: (tile, url) => {
      const vt = tile as VectorTile<any>;
      vt.setLoader((extent, _res, projection) => { void (async () => {
        try {
          const r = await fetch(url, { headers: await authHeaders() });
          if (r.status === 204 || !r.ok) {
            vt.setFeatures([]);
            return;
          }
          const buf = await r.arrayBuffer();
          const feats = vt.getFormat().readFeatures(buf, { extent, featureProjection: projection });
          vt.setFeatures(feats as any);
        } catch {
          vt.onError();
        }
      })(); });
    },
  });
}

/** Tiles raster (PNG) da API, com bandas, paleta e realce do estilo da camada. */
export function rasterTileSource(layer: Layer): XYZ {
  const st = layer.exibicao?.estilo ?? {};
  const q = new URLSearchParams({ v: String(layer.versao) });
  if (st.bandas?.length) q.set("bandas", st.bandas.join(","));
  if (st.paleta) q.set("paleta", st.paleta);
  if (st.realce) q.set("realce", st.realce);
  return new XYZ({
    url: `${api}/layers/${layer.id}/raster/{z}/{x}/{y}.png?${q}`,
    maxZoom: 22,
    tileLoadFunction: (tile, url) => {
      const img = (tile as ImageTile).getImage() as HTMLImageElement;
      authHeaders().then((h) => fetch(url, { headers: h })).then(async (r) => {
        if (r.status === 204 || !r.ok) {
          img.src = EMPTY_PNG;
          return;
        }
        const blobUrl = URL.createObjectURL(await r.blob());
        img.onload = () => URL.revokeObjectURL(blobUrl);
        img.src = blobUrl;
      }).catch(() => { img.src = EMPTY_PNG; });
    },
  });
}

export function wmsSource(s: ServiceLayer): TileWMS {
  return new TileWMS({ url: s.url, params: { LAYERS: s.camadas ?? "", TILED: true }, crossOrigin: "anonymous" });
}

export function xyzSource(s: ServiceLayer): XYZ {
  return new XYZ({ url: s.url, crossOrigin: "anonymous", maxZoom: 22 });
}

const capsCache = new Map<string, Promise<any>>();

/** WMTS a partir do GetCapabilities do serviço (o servidor precisa permitir CORS). */
export async function wmtsSource(s: ServiceLayer): Promise<WMTS> {
  if (!capsCache.has(s.url)) {
    capsCache.set(s.url, fetch(s.url).then(async (r) => {
      if (!r.ok) throw new Error(`GetCapabilities respondeu ${r.status}`);
      return new WMTSCapabilities().read(await r.text());
    }));
  }
  const caps = await capsCache.get(s.url)!;
  const opts = optionsFromCapabilities(caps, { layer: s.camadas ?? "", matrixSet: "EPSG:3857" })
    ?? optionsFromCapabilities(caps, { layer: s.camadas ?? "" });
  if (!opts) throw new Error(`Camada '${s.camadas}' não encontrada no serviço WMTS.`);
  return new WMTS({ ...opts, crossOrigin: "anonymous" });
}
