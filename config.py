"""
Central configuration. Provider choice is configuration, not architecture:
model IDs, regions, and interim/primary fallbacks live here only.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.ninelives"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

DATABASE_URL = os.environ["DATABASE_URL"]

# LLM provider: "anthropic" (interim, direct API) or "bedrock" (primary target).
# Bedrock model access is blocked pending AWS support case 178690525700030;
# switch this to "bedrock" once access is granted. No code change needed elsewhere.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-5")
BEDROCK_REGION_PRIMARY = os.environ.get("BEDROCK_REGION_PRIMARY", "us-east-1")
BEDROCK_REGION_STANDBY = os.environ.get("BEDROCK_REGION_STANDBY", "eu-central-1")
STEP_MAX_TOKENS = int(os.environ.get("STEP_MAX_TOKENS", "1500"))

# Embedding provider: "local" (interim, sentence-transformers) or "bedrock" (primary, Titan).
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "local")
LOCAL_EMBEDDING_MODEL = os.environ.get("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
BEDROCK_EMBEDDING_MODEL_ID = os.environ.get("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
# Local MiniLM = 384 dims. Titan v2 default = 1024 dims. Table + index are
# recreated by scripts/setup_db.py whenever this changes (demo data reseeds).
EMBEDDING_DIM = int(os.environ.get(
    "EMBEDDING_DIM", "384" if EMBEDDING_PROVIDER == "local" else "1024"
))

TOTAL_STEPS = int(os.environ.get("TOTAL_STEPS", "20"))
# Revision (Examiner P1, 2026-08-16): project_brief.md's own Failure States
# section claims "Bedrock throttle/timeout mid-demo: per-step retry with
# backoff... worker shows 'retrying step n' rather than dying" — this was
# never implemented (llm.step_stream had zero exception handling). Applies
# to worker.py's run_persistent_step; provider-agnostic (same retry wraps
# either the Anthropic or Bedrock path in llm.py).
STEP_MAX_RETRIES = int(os.environ.get("STEP_MAX_RETRIES", "3"))
STEP_RETRY_BACKOFF_SECONDS = float(os.environ.get("STEP_RETRY_BACKOFF_SECONDS", "1"))
# Tight failover budget (F2 acceptance: standby produces next token <=5s
# after a kill). Worst case is TTL + poll before the standby even claims,
# so both are kept small; the heartbeat renews well inside the TTL so a
# live-but-thinking primary is never falsely evicted.
LEASE_TTL_SECONDS = float(os.environ.get("LEASE_TTL_SECONDS", "2"))
LEASE_HEARTBEAT_SECONDS = float(os.environ.get("LEASE_HEARTBEAT_SECONDS", "0.5"))
STANDBY_POLL_SECONDS = float(os.environ.get("STANDBY_POLL_SECONDS", "0.25"))

# F7 brain monitor: "changefeed" (primary) or "poll" (documented fallback
# from project_brief.md Failure States; also used automatically if the
# changefeed can't be opened). Both paths land the same event shape on
# the SSE panel.
MONITOR_MODE = os.environ.get("MONITOR_MODE", "changefeed")
MONITOR_POLL_SECONDS = float(os.environ.get("MONITOR_POLL_SECONDS", "1"))

# F8 recall: how many nearest memory_events rows back an answer.
RECALL_TOP_K = int(os.environ.get("RECALL_TOP_K", "5"))

# F10: each worker's kill-control server (control.py) and the shared
# secret the arena presents to it. In deployment this arrives via an ECS
# task-definition secret reference (SSM/Secrets Manager) — never baked
# into the image. Local default is dev-only and never used in prod.
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "8100"))
CONTROL_SHARED_SECRET = os.environ.get("CONTROL_SHARED_SECRET", "dev-local-only-secret")
# Revision (Examiner FAIL, 2026-08-16): a kill doesn't just need the
# standby's in-app lease claim (~2-3s, unaffected by this value) — the
# region just killed also needs its ECS Fargate task replaced before it's
# a real standby again. Measured 60-90s in the deployed setup (ECS service
# event timestamps). 30s let a second kill land while that replacement was
# still mid-flight, degrading failover to ECS's replacement speed instead
# of the fast lease claim (reproduced 3/3 in the demo rehearsal: 23.8s,
# 44.1s, 63.3s). 120s gives real margin above the measured range.
KILL_COOLDOWN_SECONDS = float(os.environ.get("KILL_COOLDOWN_SECONDS", "120"))

# Burn-rate throttle (round 2, 2026-08-16, DECISION_LOG.md): continuous
# --auto-mode Opus generation exhausted the Anthropic account's monthly
# spend cap once already. An idle pause between finished jobs cuts
# sustained duty cycle from 100% to ~80-85% (jobs run ~5.6min; a 60-90s
# pause keeps most of the runtime still doing real generation) while a
# resting arena still tells a visitor a job is coming, honestly, rather
# than looking dead. User-approved range: 60-90s (amended down from an
# initial 2-3min proposal). See state.py's get_or_create_demo_job.
IDLE_PAUSE_MIN_SECONDS = float(os.environ.get("IDLE_PAUSE_MIN_SECONDS", "60"))
IDLE_PAUSE_MAX_SECONDS = float(os.environ.get("IDLE_PAUSE_MAX_SECONDS", "90"))
