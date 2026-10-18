# FS Geotecnologias · WebGIS (Fase 1 — MVP)

Plataforma WebGIS para editar, visualizar, analisar e exportar dados geoespaciais no navegador.
O editor vetorial é o núcleo: criação e edição de pontos, linhas e polígonos com snapping,
desfazer/refazer e salvamento transacional no PostGIS.

| Camada | Tecnologia |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, OpenLayers 10, MapLibre GL JS 6 (mapa-base), Zustand, TanStack Query |
| API | Python 3.12+, FastAPI, psycopg 3 |
| Processamento | Celery + Redis, PostGIS 3.4, GDAL (pyogrio, rasterio), Shapely, GeoPandas, PyProj, rio-cogeo, rio-tiler |
| Dados | PostgreSQL 16 + PostGIS, armazenamento compatível com S3 (MinIO, AWS S3, R2) |
| Autenticação | Supabase Auth (produção) ou modo local de desenvolvimento |

## O que funciona nesta versão

- **Projetos**: criar, abrir, salvar estado (ordem, grupos, visibilidade, opacidade, estilo, vista, mapa-base, serviços), duplicar (copia os dados), compartilhar com papéis dono/editor/leitura, excluir.
- **Importação**: GeoJSON, Shapefile (zip ou arquivos soltos), GeoPackage (todas as camadas), GeoTIFF (convertido para COG). Upload em partes de 8 MB, detecção pelo GDAL, mensagens claras para formato corrompido, sem `.prj`, geometria inválida, GeoTIFF sem georreferência e formatos previstos para a Fase 2.
- **Mapa**: tiles vetoriais (MVT do PostGIS) e raster (PNG do COG), mapa-base OpenStreetMap vetorial (MapLibre) ou raster, satélite configurável, serviços WMS/WMTS/XYZ, escala, grade de coordenadas, tema claro/escuro.
- **Editor vetorial**: criar camada vazia; adicionar ponto/linha/polígono (e multi); editar vértices (arrastar, inserir na aresta, Alt+clique remove); mover feições; selecionar; excluir; snapping em vértices e segmentos com tolerância configurável, inclusive em outras camadas visíveis; vértices compartilhados movem juntos; desfazer/refazer ilimitado; salvar em transação única (tudo ou nada); detecção de conflito quando outra pessoa salvou antes; geometria inválida bloqueia o salvamento com opção de correção automática; histórico de edições por feição.
- **Tabela de atributos**: paginação no servidor, ordenação, filtros por condições, seleção sincronizada com o mapa, edição de células durante a edição, adicionar/renomear/excluir campos, estatísticas por campo, enquadrar feição.
- **Ferramentas** (executadas no PostGIS, sempre gerando camada nova): Buffer, Recortar, Interseção, Diferença, Dissolver, Centroides, Simplificar, Multipartes para partes simples, Reprojetar camada, Validar e corrigir geometrias. Progresso, cancelamento real (interrompe a consulta no banco) e histórico.
- **Consulta e medição**: identificar feições e valores de pixel, selecionar por clique e retângulo, medir distância e área (geodésicas), consultar coordenadas em WGS 84 (decimal e GMS), CRS do projeto e SIRGAS 2000 / UTM.
- **Exportação**: GeoPackage, Shapefile (zip, com nomes de campo ajustados a 10 caracteres), GeoJSON (WGS 84), CSV com WKT, GeoTIFF; download por link assinado válido por 15 minutos.
- **Sistemas de referência**: qualquer EPSG ou WKT/PROJ personalizado; CRS padrão de projeto EPSG:4326; definir CRS de camada; reprojeção na visualização; distâncias em metros calculadas em UTM local quando a camada está em graus; aviso de datum diferente.

Tudo que ainda não existe aparece na interface como **Indisponível · Fase N** e não executa nada (ex.: União, rotacionar, dividir, ferramentas raster e de terreno, layout de impressão).

## Rodar com Docker Compose

```bash
cp .env.example .env        # ajuste senhas e segredos
docker compose up --build
```

- Frontend: http://localhost:3000 — entre com `DEV_USER_EMAIL` / `DEV_USER_PASSWORD` do `.env`
- API e documentação OpenAPI: http://localhost:8000/docs
- Console do MinIO: http://localhost:9001

As migrações do banco rodam automaticamente quando a API sobe.

## Rodar sem Docker (desenvolvimento)

Requisitos: Python 3.12+, Node 22, PostgreSQL 16 com PostGIS 3.4, Redis.

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                       # aponte DATABASE_URL e REDIS_URL
python -m app.db.migrate
uvicorn app.main:app --reload --port 8000  # terminal 1
celery -A app.workers.celery_app worker -l info   # terminal 2

# Frontend
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Dados de exemplo para testar a importação estão em `backend/tests/fixtures/` (gerados por
`python scripts/gerar_dados_teste.py`): lotes (GeoJSON), vias (Shapefile zip), nascentes (GeoPackage em SIRGAS 2000),
imagem de 4 bandas (GeoTIFF), além de arquivos propositalmente inválidos.

## Supabase Auth

1. Crie um projeto no Supabase e ative o login por e-mail e senha.
2. Backend: `AUTH_MODE=supabase` e `SUPABASE_URL=https://<projeto>.supabase.co`. Projetos com chaves de assinatura
   assimétricas (padrão atual) são validados pelo JWKS público, sem segredo. Projetos antigos com segredo HS256:
   preencha também `SUPABASE_JWT_SECRET`.
3. Frontend: `NEXT_PUBLIC_AUTH_MODE=supabase`, `NEXT_PUBLIC_SUPABASE_URL` e `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

O usuário é criado na base da plataforma no primeiro acesso. As tabelas `organizations` e `organization_members`
já existem para o suporte multiempresa da Fase 3.

## Produção: Vercel + API em Docker

- **Frontend na Vercel**: importe a pasta `frontend` como projeto; configure as variáveis `NEXT_PUBLIC_*`
  (veja `frontend/.env.example`), com `NEXT_PUBLIC_API_URL` apontando para a API pública.
- **API e worker**: a imagem `backend/Dockerfile` roda a API (`api`) ou o worker (`worker`). Precisa de PostgreSQL
  com PostGIS, Redis e um bucket S3. Configure `STORAGE_BACKEND=s3`, as credenciais `S3_*`,
  `CORS_ORIGINS=https://<seu-domínio-vercel>`, `PUBLIC_API_URL` e `ENVIRONMENT=production`
  (o modo de login local é recusado em produção).
- **Mapa-base**: o padrão é o OpenFreeMap (dados OpenStreetMap, gratuito, sem chave). Para outro provedor
  vetorial, defina `NEXT_PUBLIC_BASEMAP_STYLE_URL` com um estilo MapLibre; para satélite, `NEXT_PUBLIC_SATELLITE_URL`
  com o modelo XYZ do provedor e sua chave.

## Testes

```bash
cd backend && pytest                 # 102 testes: unidade + integração com PostGIS real
cd frontend && npm test              # sessão de edição (desfazer/refazer, lote de salvamento), upload em partes
cd frontend && npm run typecheck && npm run build
cd frontend && CHROME_PATH=... SENHA=... npm run e2e   # fluxo completo no navegador
```

Os testes de integração precisam de um banco PostGIS vazio em `TEST_DATABASE_URL`
(padrão `postgresql://postgres@/webgis_test?host=/tmp`). As ferramentas são conferidas contra valores analíticos
(ex.: buffer de 10 m num quadrado de 100 m = 14.312,15 m² com 8 segmentos por quarto de círculo).

## Estrutura

```text
backend/
  app/            API FastAPI (rotas em app/api/v1), autenticação, jobs, armazenamento, migrações SQL
  geo/            núcleo geoespacial sem HTTP: importação, exportação, CRS, ferramentas, raster, catálogo
  tests/          unidade, integração e dados de teste
frontend/
  app/            páginas (login, projetos, área de trabalho)
  components/     mapa, editor, painéis, tabela, caixa de ferramentas, diálogos
  lib/            cliente da API, sessão de edição, fontes e estilos do mapa, CRS
  stores/         estado da área de trabalho (Zustand)
  e2e/            teste ponta a ponta no navegador
docker-compose.yml
```

## Limitações conhecidas desta fase

- Exportações vetoriais montam o arquivo em memória no worker; camadas muito grandes (milhões de feições) precisam da exportação em fluxo prevista para a Fase 2.
- A edição carrega até 5.000 feições da área visível por vez; aproxime o mapa para editar regiões densas.
- Idiomas inglês e espanhol cobrem apenas menus e rótulos principais (o restante aparece em português).
- Simbologia categorizada/graduada, rótulos e layout de impressão ficam para a Fase 2.
