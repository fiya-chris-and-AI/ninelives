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
    partial_output TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The step-1 "plan" step's own output is stored as a memory_events row
-- (kind='plan'), not duplicated in a separate JSONB column here.

CREATE TABLE IF NOT EXISTS lease (
    job_id UUID PRIMARY KEY REFERENCES jobs(id),
    owner TEXT NOT NULL,
    region TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    control_addr TEXT -- F10: this worker's kill-control endpoint, e.g. http://host:port
);

-- F10/F11: single shared row pointing at "the" demo job, so both
-- independently-deployed worker services (different AWS regions, no
-- other coordination) converge on the same job to contend a lease over,
-- instead of each silently creating its own. Claimed the same way as
-- `lease` itself: SELECT ... FOR UPDATE under CockroachDB SERIALIZABLE.
CREATE TABLE IF NOT EXISTS demo_pointer (
    id INT PRIMARY KEY DEFAULT 1,
    job_id UUID REFERENCES jobs(id),
    resting_until TIMESTAMPTZ -- burn-rate throttle (round 2, 2026-08-16): set
        -- when a job finishes, NULL while a job is running/being created.
        -- Non-null + in the future = the shared idle pause between --auto
        -- jobs (state.py's get_or_create_demo_job); both worker regions
        -- and the arena read this same row so the pause is honest across
        -- both /api/status and /api/kill, not per-process local state.
);
-- Additive migration for the already-deployed table (CREATE TABLE IF NOT
-- EXISTS above is a no-op against it): safe to re-run, safe on a fresh table.
ALTER TABLE demo_pointer ADD COLUMN IF NOT EXISTS resting_until TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS output_chunks (
    job_id UUID NOT NULL REFERENCES jobs(id),
    step INT NOT NULL,
    seq INT NOT NULL, -- sequence within the step; resets to 0 each step
    text TEXT NOT NULL,
    region TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, step, seq)
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
