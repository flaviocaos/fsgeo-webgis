"use client";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { config } from "./config";

const LOCAL_KEY = "webgis.token";
let supabase: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (!supabase) {
    if (!config.supabaseUrl || !config.supabaseAnonKey) {
      throw new Error("Configure NEXT_PUBLIC_SUPABASE_URL e NEXT_PUBLIC_SUPABASE_ANON_KEY.");
    }
    supabase = createClient(config.supabaseUrl, config.supabaseAnonKey);
  }
  return supabase;
}

/** Token de acesso atual (Supabase renova sozinho; no modo local vale 12 h). */
export async function getToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  if (config.authMode === "supabase") {
    const { data } = await getSupabase().auth.getSession();
    return data.session?.access_token ?? null;
  }
  try {
    const t = localStorage.getItem(LOCAL_KEY);
    if (!t) return null;
    const payload = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (payload.exp * 1000 < Date.now()) {
      localStorage.removeItem(LOCAL_KEY);
      return null;
    }
    return t;
  } catch {
    return null;
  }
}

export async function signIn(email: string, password: string): Promise<void> {
  if (config.authMode === "supabase") {
    const { error } = await getSupabase().auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message === "Invalid login credentials" ? "E-mail ou senha incorretos." : error.message);
    return;
  }
  const r = await fetch(`${config.apiUrl}/api/v1/auth/local/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, senha: password }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body?.erro?.mensagem || "Não foi possível entrar.");
  localStorage.setItem(LOCAL_KEY, body.access_token);
}

export async function signUp(email: string, password: string): Promise<string> {
  if (config.authMode !== "supabase") throw new Error("Cadastro disponível apenas com Supabase Auth.");
  const { data, error } = await getSupabase().auth.signUp({ email, password });
  if (error) throw new Error(error.message);
  return data.session ? "ok" : "confirmar";
}

export async function signOut(): Promise<void> {
  if (config.authMode === "supabase") await getSupabase().auth.signOut();
  else localStorage.removeItem(LOCAL_KEY);
}
