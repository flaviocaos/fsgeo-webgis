// Copia o worker do MapLibre para /public: o bundler não resolve o worker pelo import.meta.url.
import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("public", { recursive: true });
copyFileSync("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", "public/maplibre-gl-worker.mjs");
console.log("maplibre-gl-worker.mjs copiado para public/");
