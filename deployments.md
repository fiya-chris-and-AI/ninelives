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

## Open items for M1+

- [ ] ECS Fargate services (us-east-1 + eu-central-1) + ALB — needs explicit go-ahead at M3
- [ ] Flip repo to public before T-2h submission
- [ ] Swap Bedrock back in once support case 178690525700030 clears
- [ ] Connect CockroachDB Managed MCP Server to this session (read-only)
