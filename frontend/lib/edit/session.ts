/**
 * Sessão de edição de uma camada.
 *
 * Guarda o estado original (como veio do servidor) e o estado atual de cada feição.
 * Toda alteração vira um comando reversível (antes/depois por feição), o que dá
 * desfazer/refazer ilimitado. O lote enviado ao servidor é a diferença entre atual e original,
 * então editar e depois desfazer não gera alteração nenhuma.
 */

export type Geometry = GeoJSON.Geometry | null;
export type Attrs = Record<string, unknown>;

export interface EditFeature {
  key: string;            // "f:<fid>" para feições existentes, "n:<ref>" para novas
  fid: number | null;
  geometry: Geometry;
  attrs: Attrs;
}

interface Step {
  key: string;
  before: EditFeature | null;
  after: EditFeature | null;
}

export interface Command {
  label: string;
  steps: Step[];
}

export interface EditBatch {
  versao_base: number;
  criar: { ref: string; geometria: Geometry; atributos: Attrs }[];
  atualizar: { fid: number; geometria?: Geometry; atributos?: Attrs; remover_geometria?: boolean }[];
  excluir: number[];
  corrigir_invalidas?: boolean;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const clone = <T>(v: T): T => (v === null || v === undefined ? v : JSON.parse(JSON.stringify(v)));

export const fidKey = (fid: number) => `f:${fid}`;

export class EditSession {
  readonly layerId: string;
  baseVersion: number;
  private original = new Map<number, { geometry: Geometry; attrs: Attrs }>();
  private current = new Map<string, EditFeature>();
  private undoStack: Command[] = [];
  private redoStack: Command[] = [];
  private seq = 0;

  constructor(layerId: string, baseVersion: number) {
    this.layerId = layerId;
    this.baseVersion = baseVersion;
  }

  /** Recebe feições do servidor (carregamento por extensão). Ignora as já conhecidas,
   *  inclusive as que o usuário excluiu nesta sessão. Devolve as chaves novas. */
  load(features: { id: number; geometry: Geometry; properties: Attrs }[]): string[] {
    const added: string[] = [];
    for (const f of features) {
      if (this.original.has(f.id)) continue;
      this.original.set(f.id, { geometry: clone(f.geometry), attrs: clone(f.properties) });
      const key = fidKey(f.id);
      this.current.set(key, { key, fid: f.id, geometry: clone(f.geometry), attrs: clone(f.properties) });
      added.push(key);
    }
    return added;
  }

  get(key: string): EditFeature | undefined {
    const f = this.current.get(key);
    return f ? clone(f) : undefined;
  }

  all(): EditFeature[] {
    return [...this.current.values()].map(clone);
  }

  private apply(cmd: Command, direction: "do" | "undo"): string[] {
    const keys: string[] = [];
    const steps = direction === "do" ? cmd.steps : [...cmd.steps].reverse();
    for (const s of steps) {
      const target = direction === "do" ? s.after : s.before;
      if (target) this.current.set(s.key, clone(target));
      else this.current.delete(s.key);
      keys.push(s.key);
    }
    return keys;
  }

  private commit(label: string, steps: Step[]): string[] {
    const real = steps.filter((s) => !same(s.before, s.after));
    if (!real.length) return [];
    const cmd = { label, steps: real };
    this.undoStack.push(cmd);
    this.redoStack = [];
    return this.apply(cmd, "do");
  }

  create(geometry: Geometry, attrs: Attrs = {}): string {
    const ref = `t${Date.now().toString(36)}${(this.seq++).toString(36)}`;
    const key = `n:${ref}`;
    this.commit("Criar feição", [{ key, before: null, after: { key, fid: null, geometry: clone(geometry), attrs: clone(attrs) } }]);
    return key;
  }

  setGeometries(changes: { key: string; geometry: Geometry }[], label = "Alterar geometria"): string[] {
    const steps: Step[] = [];
    for (const c of changes) {
      const before = this.current.get(c.key);
      if (!before) continue;
      steps.push({ key: c.key, before: clone(before), after: { ...clone(before), geometry: clone(c.geometry) } });
    }
    return this.commit(label, steps);
  }

  setAttributes(key: string, attrs: Attrs, label = "Alterar atributos"): string[] {
    const before = this.current.get(key);
    if (!before) return [];
    return this.commit(label, [{ key, before: clone(before), after: { ...clone(before), attrs: { ...before.attrs, ...clone(attrs) } } }]);
  }

  remove(keys: string[], label = "Excluir feições"): string[] {
    const steps: Step[] = [];
    for (const key of keys) {
      const before = this.current.get(key);
      if (before) steps.push({ key, before: clone(before), after: null });
    }
    return this.commit(label, steps);
  }

  canUndo() { return this.undoStack.length > 0; }
  canRedo() { return this.redoStack.length > 0; }
  undoLabel() { return this.undoStack.at(-1)?.label; }
  redoLabel() { return this.redoStack.at(-1)?.label; }

  undo(): string[] {
    const cmd = this.undoStack.pop();
    if (!cmd) return [];
    this.redoStack.push(cmd);
    return this.apply(cmd, "undo");
  }

  redo(): string[] {
    const cmd = this.redoStack.pop();
    if (!cmd) return [];
    this.undoStack.push(cmd);
    return this.apply(cmd, "do");
  }

  /** Diferença entre o estado atual e o original, no formato do endpoint /edits. */
  diff(): EditBatch {
    const batch: EditBatch = { versao_base: this.baseVersion, criar: [], atualizar: [], excluir: [] };
    for (const f of this.current.values()) {
      if (f.fid === null) {
        batch.criar.push({ ref: f.key.slice(2), geometria: clone(f.geometry), atributos: clone(f.attrs) });
        continue;
      }
      const o = this.original.get(f.fid)!;
      const upd: EditBatch["atualizar"][number] = { fid: f.fid };
      if (!same(o.geometry, f.geometry)) {
        if (f.geometry === null) upd.remover_geometria = true;
        else upd.geometria = clone(f.geometry);
      }
      const changed: Attrs = {};
      for (const [k, v] of Object.entries(f.attrs)) if (!same(o.attrs[k], v)) changed[k] = v;
      if (Object.keys(changed).length) upd.atributos = changed;
      if (upd.geometria !== undefined || upd.atributos || upd.remover_geometria) batch.atualizar.push(upd);
    }
    for (const fid of this.original.keys()) if (!this.current.has(fidKey(fid))) batch.excluir.push(fid);
    return batch;
  }

  pendingCount(): number {
    const d = this.diff();
    return d.criar.length + d.atualizar.length + d.excluir.length;
  }

  /** Após salvar: o estado atual vira o novo original, com os fid definitivos das feições criadas.
   *  Devolve o mapa de chave temporária → chave definitiva para atualizar o mapa. */
  markSaved(created: Record<string, number>, newVersion: number): Record<string, string> {
    const renamed: Record<string, string> = {};
    const next = new Map<string, EditFeature>();
    this.original.clear();
    for (const f of this.current.values()) {
      let fid = f.fid;
      let key = f.key;
      if (fid === null) {
        fid = created[f.key.slice(2)];
        if (fid === undefined) continue;
        key = fidKey(fid);
        renamed[f.key] = key;
      }
      next.set(key, { key, fid, geometry: clone(f.geometry), attrs: clone(f.attrs) });
      this.original.set(fid, { geometry: clone(f.geometry), attrs: clone(f.attrs) });
    }
    this.current = next;
    this.undoStack = [];
    this.redoStack = [];
    this.baseVersion = newVersion;
    return renamed;
  }
}
