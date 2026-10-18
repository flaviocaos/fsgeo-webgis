"use client";
import clsx from "clsx";
import { X } from "lucide-react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef } from "react";
import { useWorkspace } from "@/stores/workspace";

type Variant = "default" | "primary" | "edit" | "ghost" | "danger";

export function Button({ variant = "default", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...p}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded px-2.5 h-7 text-[12.5px] font-medium whitespace-nowrap",
        "disabled:opacity-45 disabled:cursor-not-allowed transition-colors",
        variant === "default" && "border border-line bg-panel-2 hover:border-muted",
        variant === "primary" && "bg-select text-[#06262a] hover:brightness-110",
        variant === "edit" && "bg-edit text-[#2a1c03] hover:brightness-110",
        variant === "ghost" && "hover:bg-panel-2",
        variant === "danger" && "border border-danger/60 text-danger hover:bg-danger/10",
        className,
      )}
    />
  );
}

/** Botão só com ícone. O rótulo vira dica (title) e nome acessível. */
export function IconButton({ label, active, tone, className, children, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean; tone?: "edit" | "select" }) {
  return (
    <button
      {...p}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={clsx(
        "inline-flex items-center justify-center size-7 rounded text-text/85 hover:bg-panel-2 hover:text-text",
        "disabled:opacity-35 disabled:cursor-not-allowed",
        active && tone !== "edit" && "bg-select/18 text-select ring-1 ring-select/50",
        active && tone === "edit" && "bg-edit/20 text-edit ring-1 ring-edit/60",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Dialog({ title, onClose, children, footer, width = 460 }:
  { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not([data-close])");
    el?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); prev?.focus?.(); };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className="max-h-[88vh] flex flex-col rounded-md border border-line bg-panel shadow-2xl" style={{ width, maxWidth: "100%" }}>
        <div className="flex items-center justify-between border-b border-line px-4 h-10 shrink-0">
          <h2 className="text-[14px] font-semibold">{title}</h2>
          <IconButton label="Fechar" data-close onClick={onClose}><X size={16} /></IconButton>
        </div>
        <div className="overflow-auto px-4 py-3">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-2.5 shrink-0">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-[12px] text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11.5px] text-muted">{hint}</span>}
    </label>
  );
}

export function Badge({ tone = "muted", children }: { tone?: "muted" | "edit" | "select" | "danger" | "ok"; children: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center rounded px-1.5 py-px text-[10.5px] font-medium",
      tone === "muted" && "bg-panel-2 text-muted border border-line",
      tone === "edit" && "bg-edit/15 text-edit", tone === "select" && "bg-select/15 text-select",
      tone === "danger" && "bg-danger/15 text-danger", tone === "ok" && "bg-ok/15 text-ok")}>
      {children}
    </span>
  );
}

export function Progress({ value, tone = "select" }: { value: number; tone?: "select" | "edit" }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded bg-panel-2" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className={clsx("h-full transition-[width]", tone === "select" ? "bg-select" : "bg-edit")} style={{ width: `${value}%` }} />
    </div>
  );
}

export function Toasts() {
  const toasts = useWorkspace((s) => s.toasts);
  const dismiss = useWorkspace((s) => s.dismiss);
  return (
    <div className="pointer-events-none fixed bottom-9 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} role={t.tipo === "erro" ? "alert" : "status"}
          className={clsx("pointer-events-auto flex max-w-[560px] items-start gap-3 rounded border bg-panel px-3 py-2 shadow-lg",
            t.tipo === "erro" ? "border-danger/70" : t.tipo === "ok" ? "border-ok/60" : "border-line")}>
          <span className="text-[12.5px]">{t.texto}</span>
          <button className="text-muted hover:text-text" onClick={() => dismiss(t.id)} aria-label="Fechar aviso"><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-center text-[12.5px] text-muted">{children}</div>;
}
