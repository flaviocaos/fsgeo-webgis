"use client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Api } from "@/lib/api";

/** Escolha de CRS por código ou nome, com atalhos dos sistemas mais usados no Brasil. */
export function CrsPicker({ value, onChange, id }: { value: string; onChange: (v: string) => void; id?: string }) {
  const [q, setQ] = useState(value);
  const [open, setOpen] = useState(false);
  const [debounced, setDebounced] = useState(q);
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => setQ(value), [value]);
  const search = debounced.trim() === value ? "" : debounced.trim();
  const { data, isFetching } = useQuery({ queryKey: ["crs", search], queryFn: () => Api.crsSearch(search), enabled: open });
  return (
    <div className="relative">
      <input id={id} className="w-full h-8" value={q} role="combobox" aria-expanded={open}
        placeholder="EPSG:4326, 31983, SIRGAS 2000…"
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} />
      {open && (
        <ul role="listbox" className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded border border-line bg-panel shadow-xl">
          {isFetching && !data && <li className="px-2 py-1.5 text-muted">Buscando…</li>}
          {data?.length === 0 && <li className="px-2 py-1.5 text-muted">Nenhum sistema encontrado.</li>}
          {data?.map((c) => (
            <li key={c.codigo} role="option" aria-selected={c.codigo === value}
              className="cursor-pointer px-2 py-1.5 hover:bg-panel-2"
              onMouseDown={(e) => { e.preventDefault(); onChange(c.codigo); setQ(c.codigo); setOpen(false); }}>
              <span className="tabular font-medium">{c.codigo}</span>
              <span className="ml-2 text-muted">{c.nome}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
