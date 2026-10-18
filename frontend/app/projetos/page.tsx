"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, LogOut, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CrsPicker } from "@/components/CrsPicker";
import { Badge, Button, Dialog, Empty, Field, IconButton } from "@/components/ui";
import { Api } from "@/lib/api";
import { getToken, signOut } from "@/lib/auth";
import type { Project } from "@/lib/types";
import { useWorkspace } from "@/stores/workspace";

const ROLE = { owner: "Dono", editor: "Editor", viewer: "Leitura" } as const;

export default function ProjectsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useWorkspace((s) => s.toast);
  const [ready, setReady] = useState(false);
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Project | null>(null);

  useEffect(() => { getToken().then((t) => (t ? setReady(true) : router.replace("/login"))); }, [router]);
  const { data, isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: Api.projects, enabled: ready });

  const dup = useMutation({
    mutationFn: (id: string) => Api.duplicateProject(id),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); toast(`Cópia criada: ${p.nome}`, "ok"); },
    onError: (e) => toast((e as Error).message, "erro"),
  });
  const del = useMutation({
    mutationFn: (id: string) => Api.deleteProject(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); setConfirmDelete(null); toast("Projeto excluído.", "ok"); },
    onError: (e) => toast((e as Error).message, "erro"),
  });

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <p className="text-[15px] font-semibold">FS Geotecnologias <span className="font-normal text-muted">WebGIS</span></p>
        <Button variant="ghost" onClick={async () => { await signOut(); router.replace("/login"); }}><LogOut size={14} />Sair</Button>
      </header>
      <div className="mb-4 flex items-end justify-between">
        <h1 className="text-[22px] font-semibold">Projetos</h1>
        <Button variant="primary" onClick={() => setCreating(true)}><Plus size={14} />Novo projeto</Button>
      </div>
      {error && <p role="alert" className="text-danger">{(error as Error).message}</p>}
      {isLoading && <p className="text-muted">Carregando projetos…</p>}
      {data && data.length === 0 && (
        <div className="rounded border border-dashed border-line"><Empty>Nenhum projeto ainda. Crie o primeiro para importar camadas e começar a editar.</Empty></div>
      )}
      {data && data.length > 0 && (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-line text-left text-[12px] text-muted">
              <th className="py-2 font-normal">Nome</th><th className="font-normal">CRS</th><th className="font-normal">Camadas</th>
              <th className="font-normal">Seu papel</th><th className="font-normal">Atualizado</th><th />
            </tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.id} className="border-b border-line/60 hover:bg-panel">
                <td className="py-2.5"><Link href={`/projetos/${p.id}`} className="font-medium hover:text-select">{p.nome}</Link>
                  {p.descricao && <div className="text-[12px] text-muted">{p.descricao}</div>}</td>
                <td className="tabular">{p.crs}</td>
                <td className="tabular">{typeof p.camadas === "number" ? p.camadas : "—"}</td>
                <td><Badge>{ROLE[p.papel]}</Badge></td>
                <td className="tabular text-muted">{new Date(p.atualizado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</td>
                <td className="text-right">
                  <IconButton label="Duplicar projeto" onClick={() => dup.mutate(p.id)}><Copy size={14} /></IconButton>
                  {p.papel === "owner" && <IconButton label="Excluir projeto" onClick={() => setConfirmDelete(p)}><Trash2 size={14} /></IconButton>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {creating && <NewProjectDialog onClose={() => setCreating(false)} onCreated={(p) => router.push(`/projetos/${p.id}`)} />}
      {confirmDelete && (
        <Dialog title="Excluir projeto" onClose={() => setConfirmDelete(null)} footer={<>
          <Button onClick={() => setConfirmDelete(null)}>Cancelar</Button>
          <Button variant="danger" disabled={del.isPending} onClick={() => del.mutate(confirmDelete.id)}>Excluir projeto</Button>
        </>}>
          <p>O projeto <strong>{confirmDelete.nome}</strong> e todas as suas camadas serão excluídos. Esta ação não pode ser desfeita.</p>
        </Dialog>
      )}
    </main>
  );
}

function NewProjectDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (p: Project) => void }) {
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [crs, setCrs] = useState("EPSG:4326");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({ mutationFn: () => Api.createProject(nome, crs, descricao), onSuccess: onCreated, onError: (e) => setErr((e as Error).message) });
  return (
    <Dialog title="Novo projeto" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" disabled={!nome.trim() || m.isPending} onClick={() => m.mutate()}>Criar projeto</Button>
    </>}>
      <Field label="Nome"><input className="w-full h-8" value={nome} onChange={(e) => setNome(e.target.value)} maxLength={200} /></Field>
      <Field label="Descrição (opcional)"><input className="w-full h-8" value={descricao} onChange={(e) => setDescricao(e.target.value)} /></Field>
      <Field label="Sistema de referência do projeto" hint="Usado em novas camadas e na leitura de coordenadas. Pode ser alterado depois.">
        <CrsPicker value={crs} onChange={setCrs} />
      </Field>
      {err && <p role="alert" className="text-danger">{err}</p>}
    </Dialog>
  );
}
