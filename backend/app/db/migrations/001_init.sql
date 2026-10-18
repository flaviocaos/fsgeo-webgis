-- Esquema inicial da plataforma WebGIS (Fase 1)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS layerdata;

-- Usuários vêm do Supabase Auth (external_id = claim "sub") ou do modo local.
CREATE TABLE app.users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id  text NOT NULL UNIQUE,
    email        text,
    display_name text,
    locale       text NOT NULL DEFAULT 'pt-BR',
    theme        text NOT NULL DEFAULT 'dark',
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX users_email_idx ON app.users (lower(email));

-- Organizações: estrutura pronta para multiusuário/multiempresa (uso pleno na Fase 3).
CREATE TABLE app.organizations (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.organization_members (
    organization_id uuid NOT NULL REFERENCES app.organizations(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    role            text NOT NULL CHECK (role IN ('admin','member')),
    PRIMARY KEY (organization_id, user_id)
);

CREATE TABLE app.projects (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        uuid NOT NULL REFERENCES app.users(id),
    organization_id uuid REFERENCES app.organizations(id),
    name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    description     text NOT NULL DEFAULT '',
    crs             text NOT NULL DEFAULT 'EPSG:4326',
    state           jsonb NOT NULL DEFAULT '{}'::jsonb,   -- vista, mapa-base, serviços, grupos
    version         integer NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.project_members (
    project_id uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    role       text NOT NULL CHECK (role IN ('owner','editor','viewer')),
    PRIMARY KEY (project_id, user_id)
);

-- Sessões de upload em partes
CREATE TABLE app.uploads (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES app.users(id),
    filename    text NOT NULL,
    total_size  bigint NOT NULL,
    part_count  integer NOT NULL,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open','complete','aborted')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.datasets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    uploaded_by     uuid NOT NULL REFERENCES app.users(id),
    original_name   text NOT NULL,
    storage_key     text NOT NULL,
    size_bytes      bigint NOT NULL,
    sha256          text NOT NULL,
    detected_format text,
    status          text NOT NULL DEFAULT 'stored' CHECK (status IN ('stored','imported','failed')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES app.users(id),
    kind        text NOT NULL CHECK (kind IN ('import','tool','export')),
    tool_id     text,
    params      jsonb NOT NULL DEFAULT '{}'::jsonb,
    status      text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','succeeded','failed','cancelling','cancelled')),
    progress    integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    messages    jsonb NOT NULL DEFAULT '[]'::jsonb,
    result      jsonb,
    error       text,
    celery_id   text,
    pg_pid      integer,
    created_at  timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz,
    finished_at timestamptz
);
CREATE INDEX jobs_project_idx ON app.jobs (project_id, created_at DESC);

CREATE TABLE app.layers (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    dataset_id    uuid REFERENCES app.datasets(id) ON DELETE SET NULL,
    source_job_id uuid REFERENCES app.jobs(id) ON DELETE SET NULL,
    kind          text NOT NULL CHECK (kind IN ('vector','raster')),
    name          text NOT NULL,
    srid          integer NOT NULL DEFAULT 0,          -- 0 = CRS indefinido
    geom_type     text,
    table_name    text UNIQUE,
    cog_key       text,
    band_count    integer,
    band_dtype    text,
    nodata        double precision,
    raster_stats  jsonb,
    bbox_4326     geometry(Polygon, 4326),
    feature_count bigint NOT NULL DEFAULT 0,
    next_field    integer NOT NULL DEFAULT 1,           -- gerador de nomes de coluna f_<n>
    version       integer NOT NULL DEFAULT 1,
    editable      boolean NOT NULL DEFAULT true,
    created_by    uuid REFERENCES app.users(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'vector' AND table_name IS NOT NULL) OR (kind = 'raster' AND cog_key IS NOT NULL))
);
CREATE INDEX layers_project_idx ON app.layers (project_id);

-- Nomes exibidos dos campos. A coluna física é gerada pelo servidor (f_1, f_2...).
CREATE TABLE app.layer_fields (
    layer_id    uuid NOT NULL REFERENCES app.layers(id) ON DELETE CASCADE,
    name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    column_name text NOT NULL,
    type        text NOT NULL CHECK (type IN ('text','integer','real','boolean','date','datetime')),
    position    integer NOT NULL,
    PRIMARY KEY (layer_id, column_name),
    UNIQUE (layer_id, name)
);

-- Exibição da camada no projeto
CREATE TABLE app.project_layers (
    project_id uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    layer_id   uuid NOT NULL REFERENCES app.layers(id) ON DELETE CASCADE,
    position   integer NOT NULL DEFAULT 0,
    group_name text,
    visible    boolean NOT NULL DEFAULT true,
    opacity    real NOT NULL DEFAULT 1 CHECK (opacity BETWEEN 0 AND 1),
    style      jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (project_id, layer_id)
);

-- Histórico de edições por feição (antes/depois), base para auditoria e versionamento.
CREATE TABLE app.edit_log (
    id            bigserial PRIMARY KEY,
    layer_id      uuid NOT NULL REFERENCES app.layers(id) ON DELETE CASCADE,
    batch_id      uuid NOT NULL,
    fid           bigint NOT NULL,
    op            text NOT NULL CHECK (op IN ('insert','update','delete')),
    before        jsonb,
    after         jsonb,
    user_id       uuid NOT NULL REFERENCES app.users(id),
    layer_version integer NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX edit_log_layer_idx ON app.edit_log (layer_id, created_at DESC);

CREATE TABLE app.exports (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES app.projects(id) ON DELETE CASCADE,
    layer_id    uuid REFERENCES app.layers(id) ON DELETE SET NULL,
    job_id      uuid REFERENCES app.jobs(id) ON DELETE SET NULL,
    format      text NOT NULL,
    storage_key text NOT NULL,
    filename    text NOT NULL,
    size_bytes  bigint,
    user_id     uuid NOT NULL REFERENCES app.users(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.audit_log (
    id            bigserial PRIMARY KEY,
    user_id       uuid REFERENCES app.users(id) ON DELETE SET NULL,
    action        text NOT NULL,
    resource_type text NOT NULL,
    resource_id   text,
    detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_time_idx ON app.audit_log (created_at DESC);
