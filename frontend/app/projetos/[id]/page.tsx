"use client";
import dynamic from "next/dynamic";
import { use } from "react";

// O mapa usa APIs do navegador (canvas, WebGL): carrega somente no cliente.
const Workspace = dynamic(() => import("@/components/Workspace"), {
  ssr: false,
  loading: () => <main className="grid h-screen place-items-center text-muted">Abrindo projeto…</main>,
});

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Workspace projectId={id} />;
}
