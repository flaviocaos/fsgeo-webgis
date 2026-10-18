import type { FeatureLike } from "ol/Feature";
import { MultiPoint } from "ol/geom";
import { Circle, Fill, RegularShape, Stroke, Style } from "ol/style";
import type { LayerStyle } from "../types";

export const PALETTE = ["#2f7fc1", "#c1442f", "#3f9a5b", "#8a55b5", "#c28a1d", "#1f9aa0", "#b5487a", "#6b7a2a"];

/** Cor padrão estável por camada (não muda ao reordenar). */
export function colorForId(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function hexA(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const cache = new Map<string, Style>();

function base(cor: string, largura: number, preenchimento: number, raio: number, kind: string): Style {
  const key = `${cor}|${largura}|${preenchimento}|${raio}|${kind}`;
  let s = cache.get(key);
  if (!s) {
    const stroke = new Stroke({ color: cor, width: largura });
    const fill = new Fill({ color: hexA(cor, preenchimento) });
    s = kind === "point"
      ? new Style({ image: new Circle({ radius: raio, fill: new Fill({ color: cor }), stroke: new Stroke({ color: "#fff", width: 1.2 }) }) })
      : new Style({ stroke, fill });
    cache.set(key, s);
  }
  return s;
}

function css(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Estilo de camada vetorial; feições selecionadas ganham contorno ciano. */
export function vectorStyle(style: LayerStyle, fallbackColor: string, selected: () => Set<number>) {
  const cor = style.cor || fallbackColor;
  const largura = style.largura ?? 1.6;
  const preenchimento = style.opacidade_preenchimento ?? 0.25;
  const raio = style.raio ?? 5;
  return (feature: FeatureLike) => {
    const t = feature.getGeometry()?.getType() ?? "";
    const kind = t.includes("Point") ? "point" : "other";
    const id = feature.getId();
    if (typeof id === "number" && selected().has(id)) {
      const sel = css("--select", "#3ccad3");
      return kind === "point"
        ? new Style({ image: new Circle({ radius: raio + 2, fill: new Fill({ color: sel }), stroke: new Stroke({ color: "#fff", width: 2 }) }), zIndex: 10 })
        : new Style({ stroke: new Stroke({ color: sel, width: largura + 2 }), fill: new Fill({ color: hexA(sel.startsWith("#") ? sel : "#3ccad3", 0.3) }), zIndex: 10 });
    }
    return base(cor, largura, preenchimento, raio, kind);
  };
}

/** Estilo das feições em edição: ocre, com vértices visíveis. */
export function editStyle(selectedKeys: () => Set<string>) {
  return (feature: FeatureLike) => {
    const edit = css("--edit", "#e2a93b");
    const sel = css("--select", "#3ccad3");
    const isSel = selectedKeys().has(String(feature.getId()));
    const color = isSel ? sel : edit;
    const t = feature.getGeometry()?.getType() ?? "";
    if (t.includes("Point")) {
      return new Style({ image: new Circle({ radius: isSel ? 7 : 6, fill: new Fill({ color }), stroke: new Stroke({ color: "#fff", width: 1.5 }) }) });
    }
    const styles = [new Style({ stroke: new Stroke({ color, width: isSel ? 3 : 2 }), fill: new Fill({ color: hexA(edit.startsWith("#") ? edit : "#e2a93b", 0.18) }) })];
    styles.push(new Style({
      image: new RegularShape({ points: 4, radius: 4, angle: Math.PI / 4, fill: new Fill({ color: "#fff" }), stroke: new Stroke({ color, width: 1.5 }) }),
      geometry: (f) => {
        const g = (f as any).getGeometry();
        if (!g) return undefined;
        const coords: number[][] = [];
        const walk = (c: any) => (typeof c[0] === "number" ? coords.push(c) : c.forEach(walk));
        walk(g.getCoordinates());
        return new MultiPoint(coords);
      },
    }));
    return styles;
  };
}

export const measureStyle = new Style({
  stroke: new Stroke({ color: "#e2a93b", width: 2, lineDash: [6, 4] }),
  fill: new Fill({ color: "rgba(226,169,59,0.12)" }),
  image: new Circle({ radius: 4, fill: new Fill({ color: "#e2a93b" }) }),
});
