"use client";
import { useEffect, useState } from "react";
import { Api } from "@/lib/api";
import { ensureProjection, formatCoord, fromLonLat4326 } from "@/lib/map/proj";
import { useWorkspace } from "@/stores/workspace";

export function StatusBar({ running }: { running: number }) {
  const cursor = useWorkspace((s) => s.cursor);
  const scale = useWorkspace((s) => s.scale);
  const crs = useWorkspace((s) => s.project?.crs ?? "EPSG:4326");
  const editing = useWorkspace((s) => s.editLayerId);
  const [projOk, setProjOk] = useState(false);
  const [info, setInfo] = useState<{ geografico: boolean; unidade: string } | null>(null);

  useEffect(() => {
    setProjOk(false);
    ensureProjection(crs).then(setProjOk);
    Api.crsInfo(crs).then((i) => setInfo({ geografico: i.geografico, unidade: i.unidade })).catch(() => {});
  }, [crs]);

  const projected = cursor && projOk && crs !== "EPSG:4326" ? fromLonLat4326(crs, cursor.lon, cursor.lat) : null;
  const geo = info?.geografico ?? true;
  return (
    <footer className="flex h-6 items-center gap-4 border-t border-line bg-panel px-3 text-[11.5px] text-muted tabular" aria-label="Barra de status">
      <span title="Coordenadas do cursor em WGS 84">
        Lat/Lon {cursor ? `${formatCoord(cursor.lat, true)}, ${formatCoord(cursor.lon, true)}` : "—"}
      </span>
      {crs !== "EPSG:4326" && (
        <span title={`Coordenadas no CRS do projeto (${crs})`}>
          {geo ? "Lat/Lon" : "E/N"} {projected ? (geo ? `${formatCoord(projected[1], true)}, ${formatCoord(projected[0], true)}`
            : `${formatCoord(projected[0], false)} ; ${formatCoord(projected[1], false)}`) : "—"}
        </span>
      )}
      <span>Escala 1:{scale ? Math.round(scale).toLocaleString("pt-BR") : "—"}</span>
      <span>{crs}</span>
      <span>Unidade {info?.unidade === "metre" ? "metro" : info?.unidade === "degree" ? "grau" : info?.unidade ?? "—"}</span>
      <div className="flex-1" />
      {editing && <span className="text-edit">Modo de edição</span>}
      <span className={running ? "text-select" : ""}>{running ? `${running} processamento(s) em andamento` : "Pronto"}</span>
    </footer>
  );
}
