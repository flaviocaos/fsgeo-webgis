import { describe, expect, it } from "vitest";
import { EditSession, fidKey } from "@/lib/edit/session";
import { planParts } from "@/lib/upload";

const pt = (x: number, y: number): GeoJSON.Point => ({ type: "Point", coordinates: [x, y] });

function session() {
  const s = new EditSession("camada", 3);
  s.load([
    { id: 1, geometry: pt(0, 0), properties: { nome: "a", n: 1 } },
    { id: 2, geometry: pt(1, 1), properties: { nome: "b", n: 2 } },
  ]);
  return s;
}

describe("EditSession", () => {
  it("começa sem alterações", () => {
    const s = session();
    expect(s.pendingCount()).toBe(0);
    expect(s.diff()).toEqual({ versao_base: 3, criar: [], atualizar: [], excluir: [] });
  });

  it("gera lote com criação, alteração e exclusão", () => {
    const s = session();
    const k = s.create(pt(5, 5), { nome: "nova" });
    s.setGeometries([{ key: fidKey(1), geometry: pt(9, 9) }]);
    s.setAttributes(fidKey(1), { n: 10 });
    s.remove([fidKey(2)]);
    const d = s.diff();
    expect(d.criar).toEqual([{ ref: k.slice(2), geometria: pt(5, 5), atributos: { nome: "nova" } }]);
    expect(d.atualizar).toEqual([{ fid: 1, geometria: pt(9, 9), atributos: { n: 10 } }]);
    expect(d.excluir).toEqual([2]);
  });

  it("desfazer tudo volta ao lote vazio; refazer restaura", () => {
    const s = session();
    s.setGeometries([{ key: fidKey(1), geometry: pt(9, 9) }]);
    s.remove([fidKey(2)]);
    s.create(pt(3, 3));
    expect(s.pendingCount()).toBe(3);
    expect(s.undoLabel()).toBe("Criar feição");
    s.undo(); s.undo(); s.undo();
    expect(s.canUndo()).toBe(false);
    expect(s.pendingCount()).toBe(0);
    expect(s.get(fidKey(2))?.attrs).toEqual({ nome: "b", n: 2 });
    s.redo(); s.redo();
    expect(s.diff().excluir).toEqual([2]);
    expect(s.diff().atualizar[0].geometria).toEqual(pt(9, 9));
  });

  it("nova ação descarta o refazer", () => {
    const s = session();
    s.setAttributes(fidKey(1), { n: 5 });
    s.undo();
    expect(s.canRedo()).toBe(true);
    s.setAttributes(fidKey(1), { n: 6 });
    expect(s.canRedo()).toBe(false);
  });

  it("voltar manualmente ao valor original não gera atualização", () => {
    const s = session();
    s.setAttributes(fidKey(1), { nome: "x" });
    s.setAttributes(fidKey(1), { nome: "a" });
    expect(s.pendingCount()).toBe(0);
  });

  it("alteração sem efeito não entra no histórico", () => {
    const s = session();
    expect(s.setAttributes(fidKey(1), { nome: "a" })).toEqual([]);
    expect(s.canUndo()).toBe(false);
  });

  it("carregamento posterior não ressuscita feições excluídas nem duplica", () => {
    const s = session();
    s.remove([fidKey(2)]);
    const added = s.load([{ id: 2, geometry: pt(1, 1), properties: {} }, { id: 3, geometry: pt(2, 2), properties: {} }]);
    expect(added).toEqual([fidKey(3)]);
    expect(s.get(fidKey(2))).toBeUndefined();
    expect(s.diff().excluir).toEqual([2]);
  });

  it("criar e excluir a mesma feição nova não envia nada", () => {
    const s = session();
    const k = s.create(pt(1, 2));
    s.remove([k]);
    expect(s.pendingCount()).toBe(0);
  });

  it("após salvar, novas feições recebem fid e o histórico zera", () => {
    const s = session();
    const k = s.create(pt(7, 7), { nome: "z" });
    s.setAttributes(fidKey(1), { n: 99 });
    const ref = k.slice(2);
    const renamed = s.markSaved({ [ref]: 50 }, 4);
    expect(renamed).toEqual({ [k]: fidKey(50) });
    expect(s.baseVersion).toBe(4);
    expect(s.pendingCount()).toBe(0);
    expect(s.canUndo()).toBe(false);
    s.setAttributes(fidKey(50), { nome: "w" });
    expect(s.diff().atualizar).toEqual([{ fid: 50, atributos: { nome: "w" } }]);
  });

  it("estados são cópias: mutar o retorno não altera a sessão", () => {
    const s = session();
    const f = s.get(fidKey(1))!;
    (f.attrs as any).nome = "mutado";
    expect(s.get(fidKey(1))!.attrs.nome).toBe("a");
  });
});

describe("planParts", () => {
  it("divide arquivos em partes contínuas", () => {
    expect(planParts(10, 4)).toEqual([{ n: 1, start: 0, end: 4 }, { n: 2, start: 4, end: 8 }, { n: 3, start: 8, end: 10 }]);
    expect(planParts(4, 4)).toEqual([{ n: 1, start: 0, end: 4 }]);
    expect(planParts(0, 4)).toEqual([{ n: 1, start: 0, end: 0 }]);
  });
});
