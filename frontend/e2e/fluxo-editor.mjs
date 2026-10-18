/**
 * Teste ponta a ponta no navegador: login → projeto → importação → edição com snapping →
 * desfazer/refazer → salvar → tabela → Buffer → identificar → exportar.
 *
 * Requer a API, o worker e o frontend em execução, e um Chrome/Chromium:
 *   CHROME_PATH=/caminho/chrome BASE_URL=http://localhost:3000 API_URL=http://localhost:8000 \
 *   EMAIL=dev@fsgeo.com.br SENHA=... node e2e/fluxo-editor.mjs
 * Capturas de tela ficam em e2e/capturas/.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL || "http://localhost:3000";
const API = (process.env.API_URL || "http://localhost:8000") + "/api/v1";
const FIX = process.env.FIXTURES || path.resolve(here, "../../backend/tests/fixtures");
const SHOTS = path.join(here, "capturas");
mkdirSync(SHOTS, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH,
  headless: "shell",
  args: (process.env.CHROME_ARGS || "--no-sandbox").split(" "),
  defaultViewport: { width: 1440, height: 900 },
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = (n) => page.screenshot({ path: path.join(SHOTS, `${n}.png`) });
const step = (t) => console.log(`✓ ${t}`);
function assert(cond, msg) { if (!cond) { console.error(`✗ ${msg}`); process.exitCode = 1; throw new Error(msg); } }
const clickText = async (text, sel = "button") => {
  const ok = await page.evaluate((text, sel) => {
    const el = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().includes(text) && !e.disabled);
    if (el) el.click();
    return !!el;
  }, text, sel);
  assert(ok, `elemento não encontrado: ${text}`);
};
const keys = async (...combo) => {
  for (const k of combo.slice(0, -1)) await page.keyboard.down(k);
  await page.keyboard.press(combo.at(-1));
  for (const k of combo.slice(0, -1).reverse()) await page.keyboard.up(k);
};
const api = (p, opts = {}) => page.evaluate(async (url, opts) => {
  const r = await fetch(url, { ...opts, headers: { Authorization: "Bearer " + localStorage.getItem("webgis.token") } });
  return r.json();
}, API + p, opts);
const px = (lon, lat) => page.evaluate((lon, lat) => {
  const R = 6378137, x = (R * lon * Math.PI) / 180, y = R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const m = window.__webgisMap, p = m.getPixelFromCoordinate([x, y]), r = m.getViewport().getBoundingClientRect();
  return [r.left + p[0], r.top + p[1]];
}, lon, lat);
const layerMenu = (nome) => page.evaluate((n) =>
  [...document.querySelectorAll("button")].find((b) => b.getAttribute("aria-label") === `Ações da camada ${n}`).click(), nome);

try {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await page.type("input[type=email]", process.env.EMAIL || "dev@fsgeo.com.br");
  await page.type("input[type=password]", process.env.SENHA || "");
  await clickText("Entrar", "button[type=submit]");
  await page.waitForFunction(() => location.pathname === "/projetos");
  step("login");

  await clickText("Novo projeto");
  await sleep(200);
  const nome = `E2E ${new Date().toISOString().slice(0, 19)}`;
  await page.type("[role=dialog] input", nome);
  await clickText("Criar projeto");
  await page.waitForSelector("[data-testid=mapa]", { timeout: 30000 });
  const pid = await page.evaluate(() => location.pathname.split("/").pop());
  step(`projeto criado (${nome})`);

  await keys("Control", "i");
  const input = await page.waitForSelector("[role=dialog] input[type=file]");
  await input.uploadFile(path.join(FIX, "lotes.geojson"));
  await clickText("Enviar e importar");
  await page.waitForFunction(() => document.querySelectorAll("[role=treeitem]").length >= 1, { timeout: 30000 });
  const lotes = (await api(`/projects/${pid}`)).camadas.find((l) => l.nome === "lotes");
  assert(lotes?.feicoes === 4, "importação deveria criar 4 feições");
  step("importação de GeoJSON (4 feições)");

  await page.evaluate(() => document.querySelector("[role=treeitem]").click());
  await layerMenu("lotes");
  await clickText("Enquadrar camada", "[role=menu] button");
  await sleep(1500);
  await keys("Control", "e");
  await sleep(1200);
  await page.keyboard.press("a");
  const fA = (await api(`/layers/${lotes.id}/features?ordenar=fid&limite=1`)).features[0].geometry.coordinates[0];
  // Polígono abaixo do Lote A, começando perto de dois cantos reais (o snapping deve encaixar).
  const [p0, p1] = [fA[3], fA[0]];
  const dy = (p0[1] - fA[2][1]);
  const pts = [p0, p1, [p1[0], p1[1] + dy], [p0[0], p0[1] + dy]];
  for (const [i, p] of pts.entries()) {
    const [x, y] = await px(...p);
    await page.mouse.click(x + (i < 2 ? 3 : 0), y + (i < 2 ? 3 : 0));
    await sleep(120);
  }
  const [x0, y0] = await px(...pts[0]);
  await page.mouse.click(x0 + 3, y0 + 3);
  await page.waitForSelector("[role=dialog]");
  await page.type("[role=dialog] input", "Área verde");
  await clickText("Adicionar feição");
  await sleep(300);
  await keys("Control", "z");
  await sleep(200);
  const afterUndo = await page.evaluate(() => document.querySelector("[aria-live=polite]").textContent);
  await keys("Control", "Shift", "z");
  await sleep(200);
  assert(afterUndo.startsWith("0 "), "desfazer deveria zerar as pendências");
  await shot("01-desenho");
  await keys("Control", "s");
  await sleep(1500);
  const novo = (await api(`/layers/${lotes.id}/features?ordenar=fid&direcao=desc&limite=1`)).features[0];
  assert(novo.properties.nome === "Área verde", "feição desenhada deveria estar salva");
  const snapped = novo.geometry.coordinates[0].slice(0, 2);
  const dist = Math.hypot(snapped[0][0] - p0[0], snapped[0][1] - p0[1]) + Math.hypot(snapped[1][0] - p1[0], snapped[1][1] - p1[1]);
  assert(dist < 1e-6, `snapping deveria encaixar nos cantos do Lote A (diferença ${dist})`);
  step("desenho de polígono com snapping, desfazer/refazer e salvar");

  await keys("Control", "t");
  await sleep(1200);
  await page.evaluate(() => [...document.querySelectorAll("tbody td")].find((t) => t.textContent === "Lote B").click());
  await sleep(100);
  await keys("Control", "a");
  await page.keyboard.type("Lote B editado");
  await page.keyboard.press("Enter");
  await keys("Control", "s");
  await sleep(1500);
  const nomes = (await api(`/layers/${lotes.id}/features?ordenar=fid&limite=10`)).features.map((f) => f.properties.nome);
  assert(nomes.includes("Lote B editado"), "edição pela tabela deveria ser salva");
  await shot("02-tabela");
  await keys("Control", "e");
  step("edição de atributo pela tabela");

  await clickText("Ferramentas", 'aside[aria-label="Caixa de ferramentas"] button');
  await clickText("Buffer", 'aside[aria-label="Caixa de ferramentas"] button');
  await sleep(300);
  await clickText("Executar");
  await page.waitForFunction(() => document.body.textContent.includes("Camada criada"), { timeout: 30000 });
  const camadas = (await api(`/projects/${pid}`)).camadas;
  assert(camadas.some((l) => l.nome.includes("buffer")), "Buffer deveria criar camada");
  await shot("03-buffer");
  step("Buffer executado pela caixa de ferramentas");

  await page.keyboard.press("i");
  const [cx, cy] = await px((fA[0][0] + fA[2][0]) / 2, (fA[0][1] + fA[2][1]) / 2);
  await page.mouse.click(cx, cy);
  await page.waitForSelector('[aria-label="Resultado da identificação"]');
  await sleep(800);
  const idt = await page.evaluate(() => document.querySelector('[aria-label="Resultado da identificação"]').innerText);
  assert(idt.includes("Lote A"), "identificar deveria mostrar o Lote A");
  step("identificar feição");

  await page.keyboard.press("h");
  await layerMenu("lotes");
  await clickText("Exportar", "[role=menu] button");
  await clickText("Exportar", "[role=dialog] button");
  let job;
  for (let i = 0; i < 60; i++) {
    job = (await api(`/projects/${pid}/jobs`)).find((j) => j.tipo === "export");
    if (job?.status === "succeeded") break;
    await sleep(500);
  }
  assert(job?.status === "succeeded", "exportação deveria concluir");
  const url = (await api(`/exports/${job.resultado.exportacao_id}/url`)).url;
  const bytes = await page.evaluate(async (u) => (await (await fetch(u)).arrayBuffer()).byteLength, url);
  assert(bytes > 1000, "arquivo exportado deveria ter conteúdo");
  step(`exportação GeoPackage (${bytes} bytes)`);
  await shot("04-final");
  assert(errors.length === 0, `erros de JavaScript na página: ${errors.join(" | ")}`);
  console.log("\nTodos os passos passaram.");
} finally {
  await browser.close();
}
