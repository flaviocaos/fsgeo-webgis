export type FieldType = "text" | "integer" | "real" | "boolean" | "date" | "datetime";
export type GeomType = "Point" | "LineString" | "Polygon" | "MultiPoint" | "MultiLineString" | "MultiPolygon";

export interface LayerStyle {
  cor?: string;
  largura?: number;
  opacidade_preenchimento?: number;
  raio?: number;
  bandas?: number[];
  paleta?: string;
  realce?: "percentil" | "minmax";
}

export interface Layer {
  id: string;
  projeto_id: string;
  nome: string;
  tipo: "vetorial" | "raster";
  geometria: GeomType | null;
  srid: number;
  crs: string | null;
  feicoes: number;
  versao: number;
  editavel: boolean;
  bbox: [number, number, number, number] | null;
  campos: { nome: string; tipo: FieldType }[];
  raster?: {
    bandas: number; tipo_dado: string; nodata: number | null; largura: number; altura: number;
    resolucao: [number, number];
    estatisticas: { banda: number; min: number; max: number; media: number; descricao?: string | null }[];
  };
  exibicao?: { posicao: number; grupo: string | null; visivel: boolean; opacidade: number; estilo: LayerStyle };
  crs_info?: { codigo: string | null; nome: string; unidade: string | null; geografico: boolean; datum: string | null };
}

export interface ServiceLayer {
  id: string;
  tipo: "wms" | "wmts" | "xyz";
  nome: string;
  url: string;
  camadas?: string;
  visivel: boolean;
  opacidade: number;
}

export interface ProjectState {
  vista?: { centro: [number, number]; zoom: number };
  mapa_base?: string;
  servicos?: ServiceLayer[];
}

export interface Project {
  id: string;
  nome: string;
  descricao: string;
  crs: string;
  estado: ProjectState;
  versao: number;
  papel: "owner" | "editor" | "viewer";
  criado_em: string;
  atualizado_em: string;
  camadas: Layer[] | number | null;
}

export interface ToolParam {
  nome: string;
  rotulo: string;
  tipo: "camada" | "numero" | "inteiro" | "texto" | "escolha" | "booleano" | "campos" | "crs";
  obrigatorio?: boolean;
  padrao?: unknown;
  opcoes?: string[];
  geometrias?: GeomType[];
  camada?: string;
  minimo?: number;
  maximo?: number;
}

export interface Tool {
  id: string;
  nome: string;
  grupo: string;
  status: "disponivel" | "indisponivel";
  fase: number;
  descricao: string;
  parametros: ToolParam[];
}

export interface Job {
  id: string;
  projeto_id: string;
  tipo: "import" | "tool" | "export";
  ferramenta: string | null;
  parametros: Record<string, unknown>;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelling" | "cancelled";
  progresso: number;
  mensagens: { nivel: string; texto: string }[];
  resultado: Record<string, any> | null;
  erro: string | null;
  criado_em: string;
}

export interface FeatureOut {
  type: "Feature";
  id: number;
  geometry: GeoJSON.Geometry | null;
  properties: Record<string, unknown>;
  distancia_m?: number;
}

export interface FeatureCollectionOut {
  type: "FeatureCollection";
  features: FeatureOut[];
  total: number | null;
  limite: number;
  deslocamento: number;
  versao: number;
}

export interface FilterCondition {
  campo: string;
  operador: "=" | "!=" | ">" | ">=" | "<" | "<=" | "contem" | "comeca" | "nulo" | "nao_nulo" | "em";
  valor?: unknown;
}

export const TERMINAL: Job["status"][] = ["succeeded", "failed", "cancelled"];
