"""Catálogo de ferramentas. Toda ferramenta do Prompt Mestre aparece aqui;
as que não têm implementação ficam com status "indisponivel" e não podem ser executadas."""
from __future__ import annotations

from typing import Any

POLY = ["Polygon", "MultiPolygon"]
ANY = ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]


def _layer(nome, rotulo, geometrias=ANY, obrigatorio=True):
    return {"nome": nome, "rotulo": rotulo, "tipo": "camada", "geometrias": geometrias, "obrigatorio": obrigatorio}


AVAILABLE: list[dict[str, Any]] = [
    {"id": "vector.buffer", "nome": "Buffer", "grupo": "Vetor · Geometria",
     "descricao": "Área de influência a uma distância fixa. Distâncias em metros são calculadas em "
                  "projeção métrica (UTM local quando a camada está em coordenadas geográficas).",
     "parametros": [
         _layer("camada", "Camada de entrada"),
         {"nome": "distancia", "rotulo": "Distância", "tipo": "numero", "obrigatorio": True, "padrao": 10},
         {"nome": "unidade", "rotulo": "Unidade", "tipo": "escolha", "opcoes": ["m", "km"], "padrao": "m"},
         {"nome": "segmentos", "rotulo": "Segmentos por quarto de círculo", "tipo": "inteiro", "padrao": 8,
          "minimo": 1, "maximo": 64},
         {"nome": "dissolver", "rotulo": "Dissolver resultado", "tipo": "booleano", "padrao": False},
     ]},
    {"id": "vector.clip", "nome": "Recortar (Clip)", "grupo": "Vetor · Sobreposição",
     "descricao": "Mantém as partes da camada de entrada que ficam dentro dos polígonos de recorte.",
     "parametros": [_layer("camada", "Camada de entrada"), _layer("recorte", "Camada de recorte", POLY)]},
    {"id": "vector.intersection", "nome": "Interseção", "grupo": "Vetor · Sobreposição",
     "descricao": "Áreas comuns entre as duas camadas, com atributos de ambas.",
     "parametros": [_layer("camada", "Camada de entrada"), _layer("sobreposicao", "Camada de sobreposição")]},
    {"id": "vector.difference", "nome": "Diferença", "grupo": "Vetor · Sobreposição",
     "descricao": "Partes da camada de entrada que não estão cobertas pela camada de sobreposição.",
     "parametros": [_layer("camada", "Camada de entrada"), _layer("sobreposicao", "Camada de sobreposição", POLY)]},
    {"id": "vector.dissolve", "nome": "Dissolver", "grupo": "Vetor · Geometria",
     "descricao": "Une feições, opcionalmente agrupando por campos.",
     "parametros": [_layer("camada", "Camada de entrada"),
                    {"nome": "campos", "rotulo": "Agrupar por campos", "tipo": "campos", "camada": "camada",
                     "obrigatorio": False, "padrao": []}]},
    {"id": "vector.centroid", "nome": "Centroides", "grupo": "Vetor · Geometria",
     "descricao": "Um ponto por feição: centroide geométrico ou ponto garantido dentro da feição.",
     "parametros": [_layer("camada", "Camada de entrada"),
                    {"nome": "dentro", "rotulo": "Garantir ponto dentro da feição", "tipo": "booleano", "padrao": False}]},
    {"id": "vector.simplify", "nome": "Simplificar", "grupo": "Vetor · Geometria",
     "descricao": "Reduz vértices preservando a topologia de cada feição (Douglas-Peucker).",
     "parametros": [_layer("camada", "Camada de entrada", ["LineString", "MultiLineString", "Polygon", "MultiPolygon"]),
                    {"nome": "tolerancia", "rotulo": "Tolerância (m)", "tipo": "numero", "obrigatorio": True, "padrao": 1}]},
    {"id": "vector.multipart_to_singlepart", "nome": "Multipartes para partes simples", "grupo": "Vetor · Geometria",
     "descricao": "Separa feições multipartes em uma feição por parte.",
     "parametros": [_layer("camada", "Camada de entrada")]},
    {"id": "vector.reproject", "nome": "Reprojetar camada", "grupo": "Vetor · Projeções",
     "descricao": "Cria uma cópia da camada em outro sistema de referência.",
     "parametros": [_layer("camada", "Camada de entrada"),
                    {"nome": "crs", "rotulo": "CRS de destino", "tipo": "crs", "obrigatorio": True, "padrao": "EPSG:4674"}]},
    {"id": "vector.fix_geometries", "nome": "Validar e corrigir geometrias", "grupo": "Vetor · Qualidade",
     "descricao": "Relata geometrias inválidas e gera uma camada corrigida (ST_MakeValid).",
     "parametros": [_layer("camada", "Camada de entrada")]},
]

# (id, nome, grupo, fase prevista)
UNAVAILABLE = [
    ("vector.union", "União", "Vetor · Sobreposição", 2),
    ("vector.sym_difference", "Diferença simétrica", "Vetor · Sobreposição", 2),
    ("vector.merge", "Mesclar camadas", "Vetor · Geometria", 2),
    ("vector.singlepart_to_multipart", "Partes simples para multipartes", "Vetor · Geometria", 2),
    ("vector.convex_hull", "Envoltória convexa", "Vetor · Geometria", 2),
    ("vector.smooth", "Suavizar", "Vetor · Geometria", 2),
    ("vector.polygonize", "Poligonizar", "Vetor · Geometria", 2),
    ("vector.points_along", "Pontos ao longo da geometria", "Vetor · Geometria", 2),
    ("analysis.spatial_join", "Junção espacial", "Análise espacial", 2),
    ("analysis.select_by_location", "Selecionar por localização", "Análise espacial", 2),
    ("analysis.nearest", "Vizinho mais próximo", "Análise espacial", 2),
    ("analysis.distance_matrix", "Matriz de distâncias", "Análise espacial", 2),
    ("analysis.point_in_polygon", "Ponto em polígono", "Análise espacial", 2),
    ("analysis.count_points", "Contar pontos em polígonos", "Análise espacial", 2),
    ("analysis.voronoi", "Polígonos de Voronoi", "Análise espacial", 2),
    ("analysis.delaunay", "Triangulação de Delaunay", "Análise espacial", 2),
    ("analysis.kernel_density", "Densidade de kernel", "Análise espacial", 2),
    ("analysis.aggregation", "Agregação espacial", "Análise espacial", 2),
    ("analysis.statistics", "Estatística espacial", "Análise espacial", 3),
    ("network.shortest_path", "Caminho mais curto", "Redes", 3),
    ("network.service_area", "Área de serviço", "Redes", 3),
    ("network.route_optimization", "Otimização de rotas", "Redes", 3),
    ("network.connectivity", "Conectividade de rede", "Redes", 3),
    ("raster.clip", "Recortar raster", "Raster · Processamento", 2),
    ("raster.merge", "Mosaico de rasters", "Raster · Processamento", 2),
    ("raster.reproject", "Reprojetar raster", "Raster · Processamento", 2),
    ("raster.resample", "Reamostrar", "Raster · Processamento", 2),
    ("raster.calculator", "Calculadora raster", "Raster · Processamento", 2),
    ("raster.rasterize", "Rasterizar vetor", "Raster · Processamento", 2),
    ("raster.polygonize", "Poligonizar raster", "Raster · Processamento", 2),
    ("raster.reclassify", "Reclassificar", "Raster · Processamento", 2),
    ("raster.nodata", "Gerenciar NoData", "Raster · Processamento", 2),
    ("raster.band_combination", "Combinação de bandas", "Raster · Processamento", 2),
    ("terrain.hillshade", "Sombreamento", "Raster · Terreno", 2),
    ("terrain.slope", "Declividade", "Raster · Terreno", 2),
    ("terrain.aspect", "Orientação de vertentes", "Raster · Terreno", 2),
    ("terrain.contours", "Curvas de nível", "Raster · Terreno", 2),
    ("terrain.ruggedness", "Rugosidade do terreno", "Raster · Terreno", 2),
    ("terrain.profile", "Perfil de elevação", "Raster · Terreno", 2),
    ("spectral.ndvi", "NDVI", "Raster · Espectral", 2),
    ("spectral.ndwi", "NDWI", "Raster · Espectral", 2),
    ("spectral.ndbi", "NDBI", "Raster · Espectral", 2),
    ("zonal.statistics", "Estatística zonal", "Raster · Zonal", 2),
    ("zonal.sampling", "Amostrar raster em pontos", "Raster · Zonal", 2),
]


def catalog() -> list[dict[str, Any]]:
    out = [dict(t, status="disponivel", fase=1) for t in AVAILABLE]
    out += [{"id": i, "nome": n, "grupo": g, "status": "indisponivel", "fase": f,
             "descricao": f"Ainda não implementada (prevista para a Fase {f}).", "parametros": []}
            for i, n, g, f in UNAVAILABLE]
    return out


def get_tool(tool_id: str) -> dict[str, Any] | None:
    return next((t for t in catalog() if t["id"] == tool_id), None)
