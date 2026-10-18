/**
 * Textos da interface. pt-BR é o idioma completo; en e es têm os rótulos principais
 * e recorrem ao pt-BR para o restante (preparação para tradução completa).
 */
export type Locale = "pt-BR" | "en" | "es";

const ptBR = {
  "menu.projeto": "Projeto", "menu.arquivo": "Arquivo", "menu.editar": "Editar", "menu.visualizar": "Visualizar",
  "menu.camadas": "Camadas", "menu.vetor": "Vetor", "menu.raster": "Raster", "menu.geoprocessamento": "Geoprocessamento",
  "menu.analise": "Análise espacial", "menu.ferramentas": "Ferramentas", "menu.configuracoes": "Configurações",
  "menu.ajuda": "Ajuda",
  "painel.camadas": "Camadas", "painel.ferramentas": "Caixa de ferramentas", "painel.tabela": "Tabela de atributos",
  "acao.salvar": "Salvar", "acao.descartar": "Descartar", "acao.cancelar": "Cancelar", "acao.fechar": "Fechar",
  "acao.executar": "Executar", "acao.importar": "Importar dados", "acao.exportar": "Exportar",
  "editor.editando": "Editando", "editor.pendentes": "alterações pendentes",
  "indisponivel": "Indisponível",
} as const;

export type MessageKey = keyof typeof ptBR;

const en: Partial<Record<MessageKey, string>> = {
  "menu.projeto": "Project", "menu.arquivo": "File", "menu.editar": "Edit", "menu.visualizar": "View",
  "menu.camadas": "Layers", "menu.vetor": "Vector", "menu.raster": "Raster", "menu.geoprocessamento": "Geoprocessing",
  "menu.analise": "Spatial analysis", "menu.ferramentas": "Tools", "menu.configuracoes": "Settings", "menu.ajuda": "Help",
  "painel.camadas": "Layers", "painel.ferramentas": "Processing toolbox", "painel.tabela": "Attribute table",
  "acao.salvar": "Save", "acao.descartar": "Discard", "acao.cancelar": "Cancel", "acao.fechar": "Close",
  "acao.executar": "Run", "acao.importar": "Import data", "acao.exportar": "Export", "indisponivel": "Unavailable",
};

const es: Partial<Record<MessageKey, string>> = {
  "menu.projeto": "Proyecto", "menu.arquivo": "Archivo", "menu.editar": "Editar", "menu.visualizar": "Ver",
  "menu.camadas": "Capas", "menu.vetor": "Vectorial", "menu.raster": "Ráster", "menu.geoprocessamento": "Geoprocesamiento",
  "menu.analise": "Análisis espacial", "menu.ferramentas": "Herramientas", "menu.configuracoes": "Configuración",
  "menu.ajuda": "Ayuda", "painel.camadas": "Capas", "painel.ferramentas": "Caja de herramientas",
  "painel.tabela": "Tabla de atributos", "acao.salvar": "Guardar", "acao.descartar": "Descartar",
  "acao.cancelar": "Cancelar", "acao.fechar": "Cerrar", "acao.executar": "Ejecutar", "acao.importar": "Importar datos",
  "acao.exportar": "Exportar", "indisponivel": "No disponible",
};

const dicts: Record<Locale, Partial<Record<MessageKey, string>>> = { "pt-BR": ptBR, en, es };

export function translate(locale: Locale, key: MessageKey): string {
  return dicts[locale][key] ?? ptBR[key];
}
