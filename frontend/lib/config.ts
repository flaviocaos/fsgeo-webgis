export const config = {
  apiUrl: (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, ""),
  authMode: (process.env.NEXT_PUBLIC_AUTH_MODE || "local") as "local" | "supabase",
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL || "",
  supabaseAnonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "",
  basemapStyleUrl: process.env.NEXT_PUBLIC_BASEMAP_STYLE_URL || "https://tiles.openfreemap.org/styles/liberty",
  satelliteUrl: process.env.NEXT_PUBLIC_SATELLITE_URL || "",
  satelliteAttribution: process.env.NEXT_PUBLIC_SATELLITE_ATTRIBUTION || "",
};
