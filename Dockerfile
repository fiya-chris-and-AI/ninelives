# F11: one image, three ECS services (two workers + the arena) — same
# codebase, the command each runs is set per-service in the task
# definition. Sizes toward the smallest Fargate footprint that holds the
# demo; the sentence-transformers model is baked in at build time so a
# cold container start never depends on Hugging Face Hub reachability
# during the live demo.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# CockroachDB Cloud's DATABASE_URL uses sslmode=verify-full, which needs
# this CA locally at ~/.postgresql/root.crt — found missing only by
# actually running the built image against the live cluster (it isn't
# on a fresh Debian base, and the base image's system trust store
# doesn't verify it either). Public root cert (Let's Encrypt ISRG Root
# X1, generic, not cluster-specific, no secret material) — safe to bake in.
RUN mkdir -p /root/.postgresql && cp deploy/cockroachdb-ca.crt /root/.postgresql/root.crt

# Fargate is CPU-only; uv's normal resolution pulls PyPI's default Linux
# torch wheel, which is CUDA-enabled (~2GB of unused nvidia-*/cuda-*/
# triton packages). Force the CPU-only build after the fact rather than
# fighting uv.lock's platform-marker resolution for one transitive
# dependency, then remove the now-orphaned CUDA packages the original
# resolve pulled in — reinstalling torch alone doesn't drop them.
RUN UV_HTTP_TIMEOUT=180 uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu --force-reinstall \
 && uv pip uninstall --python .venv/bin/python $(ls .venv/lib/python3.12/site-packages | grep -iE '^(nvidia|cuda|triton)[_-]' | sed -E 's/-[0-9].*//; s/_/-/g' | sort -u)

# .venv/bin/python directly, not `uv run` — uv run re-syncs the venv
# against uv.lock on every invocation, which would silently re-install
# the CUDA torch build just removed above. uv is a build-time tool only;
# nothing at runtime should touch it.
RUN .venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 8100

CMD [".venv/bin/uvicorn", "arena:app", "--host", "0.0.0.0", "--port", "8000"]
