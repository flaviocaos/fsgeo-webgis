"use client";
import { useRouter } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button, Field } from "@/components/ui";
import { signIn, signUp } from "@/lib/auth";
import { config } from "@/lib/config";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"entrar" | "cadastrar">("entrar");
  const [error, setError] = useState<string | null>(params.get("expirada") ? "Sua sessão expirou. Entre novamente." : null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setInfo(null);
    try {
      if (mode === "cadastrar") {
        const r = await signUp(email, password);
        if (r === "confirmar") { setInfo("Conta criada. Confirme pelo link enviado ao seu e-mail e depois entre."); setMode("entrar"); return; }
      } else {
        await signIn(email, password);
      }
      router.replace("/projetos");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen grid-cols-1 md:grid-cols-[1fr_420px]">
      <section className="relative hidden overflow-hidden md:block" aria-hidden>
        {/* Curvas de nível desenhadas em SVG: referência direta ao ofício cartográfico */}
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 800 800" preserveAspectRatio="xMidYMid slice">
          <rect width="800" height="800" fill="var(--bg)" />
          {Array.from({ length: 16 }).map((_, i) => (
            <ellipse key={i} cx={420 + i * 6} cy={380 - i * 4} rx={60 + i * 34} ry={40 + i * 26}
              transform={`rotate(${-18 + i * 2} 420 380)`} fill="none"
              stroke={i % 5 === 0 ? "var(--edit)" : "var(--line)"} strokeWidth={i % 5 === 0 ? 1.4 : 1} />
          ))}
        </svg>
        <div className="absolute bottom-10 left-10 max-w-md">
          <p className="text-[28px] font-semibold leading-tight" style={{ fontStretch: "85%" }}>
            Edite, analise e entregue dados geoespaciais direto no navegador.
          </p>
          <p className="mt-3 text-muted">Shapefile, GeoPackage, GeoJSON e GeoTIFF, com processamento em servidor PostGIS.</p>
        </div>
      </section>
      <section className="flex flex-col justify-center border-l border-line bg-panel px-10">
        <p className="mb-8 text-[15px] font-semibold">FS Geotecnologias <span className="font-normal text-muted">WebGIS</span></p>
        <h1 className="mb-6 text-[22px] font-semibold">{mode === "entrar" ? "Entrar" : "Criar conta"}</h1>
        <form onSubmit={submit}>
          <Field label="E-mail"><input type="email" required autoComplete="email" className="w-full h-8" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Senha"><input type="password" required minLength={6} autoComplete={mode === "entrar" ? "current-password" : "new-password"} className="w-full h-8" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          {error && <p role="alert" className="mb-3 text-danger">{error}</p>}
          {info && <p role="status" className="mb-3 text-ok">{info}</p>}
          <Button variant="primary" type="submit" disabled={busy} className="h-8 w-full">{busy ? "Aguarde…" : mode === "entrar" ? "Entrar" : "Criar conta"}</Button>
        </form>
        {config.authMode === "supabase" ? (
          <button className="mt-4 text-left text-muted hover:text-text" onClick={() => setMode(mode === "entrar" ? "cadastrar" : "entrar")}>
            {mode === "entrar" ? "Não tem conta? Criar conta" : "Já tem conta? Entrar"}
          </button>
        ) : (
          <p className="mt-4 text-[12px] text-muted">Modo de desenvolvimento: use o usuário definido em DEV_USER_EMAIL no backend.</p>
        )}
      </section>
    </main>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
