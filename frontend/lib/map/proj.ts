"use client";
import proj4 from "proj4";
import { register } from "ol/proj/proj4";
import { get as getProjection, transform } from "ol/proj";
import { Api } from "../api";

const pending = new Map<string, Promise<boolean>>();

/** Registra no OpenLayers a projeção do código EPSG (definição PROJ vinda da API). */
export function ensureProjection(code: string): Promise<boolean> {
  if (getProjection(code)) return Promise.resolve(true);
  if (!pending.has(code)) {
    pending.set(code, Api.crsInfo(code).then((info) => {
      proj4.defs(code, info.proj4);
      register(proj4);
      return true;
    }).catch(() => false));
  }
  return pending.get(code)!;
}

export function fromLonLat4326(code: string, lon: number, lat: number): [number, number] | null {
  if (!getProjection(code)) return null;
  const [x, y] = transform([lon, lat], "EPSG:4326", code);
  return Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null;
}

export function formatCoord(v: number, geographic: boolean): string {
  return geographic
    ? v.toLocaleString("pt-BR", { minimumFractionDigits: 6, maximumFractionDigits: 6 })
    : v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Graus decimais para graus, minutos e segundos (ex.: 15°48'12,3" S). */
export function toDMS(value: number, axis: "lat" | "lon"): string {
  const hemi = axis === "lat" ? (value < 0 ? "S" : "N") : value < 0 ? "O" : "L";
  const a = Math.abs(value);
  const d = Math.floor(a);
  const mFloat = (a - d) * 60;
  const m = Math.floor(mFloat);
  const s = (mFloat - m) * 60;
  return `${d}°${String(m).padStart(2, "0")}'${s.toFixed(1).replace(".", ",").padStart(4, "0")}" ${hemi}`;
}
