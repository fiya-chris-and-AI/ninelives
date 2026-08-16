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
LEASE_TTL_SECONDS = int(os.environ.get("LEASE_TTL_SECONDS", "3"))
STANDBY_POLL_SECONDS = float(os.environ.get("STANDBY_POLL_SECONDS", "1.0"))
