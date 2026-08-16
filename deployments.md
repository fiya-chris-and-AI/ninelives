# Deployments (working doc, maintained from M1)

## CockroachDB Cloud

- Tier: Basic
- Cloud/region: AWS us-east-1
- Cluster name: `ninelives`
- Cluster ID: `23cd98bf-ac92-4131-9de4-cb182650fb93`
- SQL user: `ninelives`
- Connection: `DATABASE_URL` in `.env.ninelives` (workspace root, gitignored, never committed) — loaded via environment at runtime only
- CA cert: `~/.postgresql/root.crt` (downloaded from cluster console)
- Verified 2026-08-16 (M0 spike): `VECTOR` column + `CREATE VECTOR INDEX` supported; `CREATE CHANGEFEED ... INTO 'null://' WITH resolved` supported (Enterprise feature available on this cluster/tier) — primary path for the brain monitor (F7) does not need the polling fallback, though it stays in code as documented insurance.
- Managed MCP Server: confirmed available on this cluster per user; not yet connected to this session (read-only, pending `claude mcp add` + OAuth).

## AWS

- Account: `540646170532` (already authenticated locally, IAM AdministratorAccess, standalone account, no Organization)
- Bedrock model access: **blocked** as of 2026-08-16. `anthropic.claude-opus-5` and `amazon.titan-embed-text-v2` both return `authorizationStatus: NOT_AUTHORIZED` via `aws bedrock get-foundation-model-availability`. The Anthropic use-case form in the console fails at the account level ("account is not authorized" — marketplace/agreement gate). AWS support case `178690525700030` filed, ~24h response expected.
  - Interim while blocked: LLM step calls the Anthropic API directly (`ANTHROPIC_API_KEY` in `.env.ninelives`); embeddings use a local `sentence-transformers` model (`all-MiniLM-L6-v2`, 384 dims). Both verified working end-to-end in the M0 spike (2026-08-16).
  - Swap back to Bedrock once the support case clears: set `LLM_PROVIDER=bedrock` and `EMBEDDING_PROVIDER=bedrock` in `.env`. No other code changes (see `llm.py`, `embeddings.py`, `config.py`).
- ECS Fargate (M3, deferred): not yet provisioned. Two regions planned — us-east-1 (primary worker) and eu-central-1 (standby worker) — plus the arena service behind an ALB on us-east-1. Explicit go-ahead required before provisioning (cost-incurring, confirmed with user 2026-08-16).
- Bedrock region check: `eu-central-1` lists `anthropic.claude-opus-5` and inference profile `eu.anthropic.claude-opus-5` as available, same authorization-gate status as us-east-1 (account-level, not region-specific).

## GitHub

- Repo: `fiya-chris-and-AI/ninelives` — **private** (per explicit user instruction 2026-08-16, overriding the brief's "public repo from day one" default — see `DECISION_LOG.md` in the workspace root for the flagged conflict). Must go public before the T-2h submission deadline (2026-08-18 21:00 CEST) — private repo at submission time is a listed dealbreaker in `project_brief.md` Section 8.
- MIT `LICENSE` committed in the initial commit (M0), not deferred.

## M1 — worker.py (F1, F2, F6) verified live, 2026-08-16

Tested with real primary + standby processes against the live cluster, real `kill -9`, no mocking:

- **F1 (transactional step-loop):** verified. Killed a worker mid-word during real Claude Opus 5 streaming; `job_state.step` stayed put, `partial_output` held exactly the flushed prefix (nothing beyond the last completed ~1s chunk), and a fresh process resumed and continued the sentence with no repeated or dropped text (`"...the th"` + `"undering-herd..."` → coherent, zero loss observed in that run).
- **F2 (lease + standby failover):** verified with a live standby process, not a manual restart. Found and fixed two real bugs in the process, not simulated:
  1. **Unhandled `SerializationFailure`** — concurrent primary/standby access to the same `lease` row under CockroachDB's SERIALIZABLE isolation threw `WriteTooOldError` and crashed the primary outright. Fixed with `db.run_txn()`, a retry-with-backoff wrapper (SQLSTATE 40001 is CockroachDB's documented client-retry contract, not an error condition) — now used by every write path in `worker.py`.
  2. **False eviction risk** — the lease was only renewed once per loop iteration plus on each chunk flush; a step with long "thinking" latency before its first token (observed: several seconds) could outlast `LEASE_TTL_SECONDS` before any flush happened, letting a live standby steal the lease from a healthy primary. Fixed with a background heartbeat thread (`_lease_heartbeat`, daemon, renews every `LEASE_HEARTBEAT_SECONDS` independent of streaming) — a `SIGKILL` takes the whole process down including the thread, so a real death still expires the lease normally; a live process never gets falsely evicted (confirmed: 10s+ of normal operation with no false claim).
  - **Measured failover timing** (single dev-machine sample, not a rehearsal): lease claim at +2.1s after kill, first standby token at +5.0s — right at the F2 acceptance bar. Tightened `LEASE_TTL_SECONDS=2`, `LEASE_HEARTBEAT_SECONDS=0.5`, `STANDBY_POLL_SECONDS=0.25` (brief's own prescribed first remedy for "failover exceeds 5s"). The remaining latency is mostly the model's own thinking/first-token time even with `output_config={"effort":"low"}` wired in — this needs re-measurement during the real Feature-Freeze demo rehearsal (3x cold, per Section 1.6), not just this dev sample, before trusting it live. Pre-approved fallback if it stays flaky: node-kill/single-region variant (2h cost, already in the brief's pivot triggers).
- **F6 (ephemeral/amnesia mode):** verified. `--no-memory` writes nothing to CockroachDB (`jobs` count unchanged across two separate runs) and every invocation starts fresh at step 1 with the amnesia banner, by construction (nothing persisted to resume from).
- **F5 (streaming terminal output):** implicit in the above — every run streamed live tokens with `[STEP n/20] [region]` labels throughout.

## Open items for M1+

- [ ] Re-measure F2 failover timing during the real Feature-Freeze demo rehearsal (3x cold) — current number is one dev-machine sample, not a rehearsal result
- [ ] F3 full 20-step pipeline: step-plan logic and prompts are built and unit-verified (`research.py`), not yet run start-to-finish for a real timed pass (M1 exit criteria: 3-5 min unattended)
- [ ] F4 seed episodic memories for Beat 4 (curated corpus itself is done — 10 docs in `corpus/`)
- [ ] F7-F9 (brain monitor, recall query, MCP) — M2
- [ ] F10-F11 (arena, deployment) — M3
- [ ] ECS Fargate services (us-east-1 + eu-central-1) + ALB — needs explicit go-ahead at M3
- [ ] Flip repo to public before T-2h submission
- [ ] Swap Bedrock back in once support case 178690525700030 clears
- [ ] Connect CockroachDB Managed MCP Server to this session (read-only)
