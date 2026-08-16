-- Ninelives schema. The process is disposable; this is the mind.
-- {{VECTOR_DIM}} is substituted by scripts/setup_db.py from config.EMBEDDING_DIM.

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running', -- running | done
    memory_mode TEXT NOT NULL DEFAULT 'persistent', -- persistent | ephemeral
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_state (
    job_id UUID PRIMARY KEY REFERENCES jobs(id),
    step INT NOT NULL DEFAULT 0,
    total_steps INT NOT NULL,
    plan JSONB,
    partial_output TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lease (
    job_id UUID PRIMARY KEY REFERENCES jobs(id),
    owner TEXT NOT NULL,
    region TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS output_chunks (
    job_id UUID NOT NULL REFERENCES jobs(id),
    seq INT NOT NULL,
    step INT NOT NULL,
    text TEXT NOT NULL,
    region TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, seq)
);

CREATE TABLE IF NOT EXISTS memory_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES jobs(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    region TEXT NOT NULL,
    step INT NOT NULL,
    kind TEXT NOT NULL, -- finding | synthesis | seed
    content TEXT NOT NULL,
    embedding VECTOR({{VECTOR_DIM}}),
    source TEXT,
    curated BOOLEAN NOT NULL DEFAULT false
);

CREATE VECTOR INDEX IF NOT EXISTS memory_events_embedding_idx
    ON memory_events (embedding);
