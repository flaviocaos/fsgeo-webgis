"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Toasts } from "@/components/ui";
import type { Locale } from "@/lib/i18n";
import { useWorkspace } from "@/stores/workspace";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 } },
  }));
  useEffect(() => {
    const t = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    useWorkspace.setState({ theme: t });
    try {
      const l = localStorage.getItem("webgis.idioma") as Locale | null;
      if (l) useWorkspace.setState({ locale: l });
    } catch {}
  }, []);
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toasts />
    </QueryClientProvider>
  );
}
