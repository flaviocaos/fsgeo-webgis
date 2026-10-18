"use client";
import { Map as MLMap, setWorkerUrl } from "maplibre-gl";

let workerSet = false;
import Layer from "ol/layer/Layer";
import type { FrameState } from "ol/Map";
import { toLonLat } from "ol/proj";

/**
 * Camada OpenLayers que desenha um mapa MapLibre GL JS (estilo vetorial) sincronizado com a vista.
 * O MapLibre não recebe interação: zoom e pan são do OpenLayers, que também faz a edição.
 */
export class MapLibreLayer extends Layer {
  private mlMap: MLMap | null = null;
  private container: HTMLDivElement;

  constructor(styleUrl: string, attribution: string) {
    const container = document.createElement("div");
    container.style.position = "absolute";
    container.style.inset = "0";
    container.style.pointerEvents = "none";
    super({
      source: undefined,
      render: (frame: FrameState) => this.renderFrame(frame),
      properties: { attributions: attribution },
    });
    this.container = container;
    if (!workerSet) {
      setWorkerUrl("/maplibre-gl-worker.mjs");
      workerSet = true;
    }
    this.mlMap = new MLMap({
      container,
      style: styleUrl,
      interactive: false,
      attributionControl: false,
      fadeDuration: 0,
      canvasContextAttributes: { preserveDrawingBuffer: false },
    });
    this.mlMap.on("render", () => this.changed());
    this.mlMap.on("error", (e: any) => console.warn("Mapa-base:", e?.error?.message ?? e));
  }

  private renderFrame(frame: FrameState): HTMLElement {
    const map = this.mlMap!;
    const vs = frame.viewState;
    const [w, h] = frame.size;
    if (this.container.clientWidth !== w || this.container.clientHeight !== h) {
      this.container.style.width = `${w}px`;
      this.container.style.height = `${h}px`;
      map.resize();
    }
    const canvas = map.getCanvas();
    canvas.style.position = "absolute";
    this.container.style.opacity = String(this.getOpacity());
    map.jumpTo({
      center: toLonLat(vs.center) as [number, number],
      zoom: vs.zoom - 1,
      bearing: (-vs.rotation * 180) / Math.PI,
    });
    if (map.isStyleLoaded()) map.redraw();
    return this.container;
  }

  disposeInternal(): void {
    this.mlMap?.remove();
    this.mlMap = null;
    super.disposeInternal();
  }
}
