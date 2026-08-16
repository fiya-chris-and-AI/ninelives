# Ninelives

An AI agent whose mind lives entirely in CockroachDB. Kill the process, the
container, or the region, and it resumes the same sentence seconds later,
having forgotten nothing.

The process is disposable; the database is the mind. Every reasoning step is
one transaction: read state, think, write state and output chunks and a
memory event, atomically. A crash between any two transactions loses at most
the in-flight step, never completed work.

Built for the CockroachDB × AWS Hackathon — "Build with Agentic Memory"
(https://cockroachdb-ai.devpost.com/).

## Status

**M0 (spike) complete.** Verified against the live CockroachDB Cloud cluster:
`VECTOR` column + vector index, `CHANGEFEED` support, and a full transactional
write/read loop (LLM step streamed and persisted chunk-by-chunk, embedded,
read back and asserted).

**M1 (the kill and the resume) complete.** `worker.py` implements the
transactional step-loop, lease + standby failover, and ephemeral (amnesia)
mode; `research.py` and `corpus/` implement the 20-step research pipeline;
`scripts/seed_memories.py` seeds curated episodic memories for Beat 4. All
verified against the live cluster with real `kill -9` on real processes,
not simulated — see `deployments.md` for what was tested, two real
concurrency bugs found and fixed along the way, and a full unattended
20-step run (5.64 min, slightly over the 3-5 min target). Failover latency
needs re-measurement during the actual demo rehearsal rather than trusting
a single dev-machine sample.

**M2 (the mind visible) complete.** `arena.py` serves the brain monitor
(`monitor.py`, F7) and the recall endpoint (`recall.py`, F8); the
CockroachDB Cloud Managed MCP Server is connected (F9). All verified
against the live cluster — see `deployments.md` for the changefeed vs.
polling decision, the recall-latency finding that changed the answer
design, and the recorded MCP query. M3 (arena UI + ECS/ALB deployment) is
next, pending explicit go-ahead on the AWS spend.

## Disclosures

- **AI coding assistants:** this project was built with AI coding assistance
  (Claude Code, via the Antigravity Academy process). The Academy's own
  tooling (`directives/`, `project_brief.md`, examiner/creative reports,
  `DECISION_LOG.md`) is process scaffolding and lives outside this repository
  — it is not project code.
- **Curated demo corpus:** the research corpus the agent works over is
  bundled in `corpus/` and is curated, not live-fetched. Listed and disclosed
  here and in the submission writeup.
- **Interim provider substitution (transparent, swap-only-config):** Bedrock
  model access (Claude Opus 5 and Titan Embeddings) is pending an AWS support
  case (marketplace/agreement gate at the account level). Until it clears,
  the LLM step calls the Anthropic API directly and embeddings use a local
  `sentence-transformers` model. Both are real, working calls — nothing is
  mocked — and both are a one-line config change away from Bedrock
  (`LLM_PROVIDER=bedrock`, `EMBEDDING_PROVIDER=bedrock` in `.env`). See
  `llm.py` and `embeddings.py`. The demo's mandatory-AWS-service requirement
  is independently satisfied by ECS Fargate (M3), regardless of this
  substitution.
- **Resilience, persistence, and failover are never simulated.** What the
  demo shows is what the database did.

## Architecture

Two thin processes:

- `worker.py` — the agent loop. One transaction per step against
  CockroachDB; renews/claims a lease, streams a reasoning step, persists
  output chunks as they arrive, and on step completion writes the step
  result, an embedded memory event, and advances `job_state`.
- `arena.py` — FastAPI orchestration only: the brain monitor SSE endpoint
  and the recall endpoint, routed to `monitor.py` and `recall.py`. Worker
  panes + the KILL AGENT endpoint are M3, not built yet.
- `monitor.py` (F7) — one background thread reads `memory_events` writes
  live (CockroachDB core changefeed, no sink; falls back to 1s polling if
  the changefeed can't be opened) and fans them out to every connected SSE
  client.
- `recall.py` (F8) — vector-searches `memory_events` for a question; the
  answer is the top-ranked row's content, not an LLM re-synthesis (see
  `deployments.md` for why — a synthesized answer missed the <3s bar).

Run the arena locally: `make arena`, then open `http://localhost:8000`.

Schema (see `schema/schema.sql`):

```
jobs(id, goal, status, memory_mode, created_at)
job_state(job_id PK, step, total_steps, plan, partial_output, updated_at)
lease(job_id PK, owner, region, expires_at)
output_chunks(job_id, seq, step, text, region, created_at)
memory_events(id, job_id, ts, region, step, kind, content, embedding VECTOR, source, curated)
```

## Setup

Requires Python 3.12, [`uv`](https://docs.astral.sh/uv/), and a CockroachDB
Cloud cluster with `DATABASE_URL` available in the environment (never
committed — see `.gitignore`).

```bash
uv sync
uv run python scripts/setup_db.py     # applies schema.sql to DATABASE_URL
uv run python scripts/spike_m0.py     # M0 spike: one real transactional step end-to-end
```

## License

MIT — see `LICENSE`.
