# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# ClaimGuard AI — reviewer API image
#
#   docker build -t claimguard-api .
#   docker run --rm -p 8000:8000 \
#     -e CLAIMGUARD_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/claimguard \
#     -v "$PWD/tests/edu/fixtures/pack_reference:/catalogue:ro" \
#     -e CLAIMGUARD_RULES_DIR=/catalogue \
#     claimguard-api
#
# WHAT RUNS
#   uvicorn, serving the factory `claimguard.review.app:create_app` on :8000.
#   That one application is the whole product surface: the review API under
#   /v1, the reviewer interface at /review, OpenAPI docs at /docs and
#   readiness at /v1/health. There is no `claimguard.api` package — the only
#   ASGI application in this repository is claimguard/review/app.py.
#
# WHAT IT NEEDS AT RUNTIME (configuration, not code)
#   CLAIMGUARD_DATABASE_URL    the DSN; docker-compose.yml points it at `db`
#   CLAIMGUARD_RULES_DIR  or   the rule catalogue; CLAIMGUARD_PACK_ROOT is the
#   CLAIMGUARD_PACK_ROOT       pack root, with `rules/` appended
#   The mentor pack is gitignored reference data, so it is deliberately NOT
#   baked in: mount a catalogue (the vendored copy under tests/edu/fixtures/
#   works and is committed) or the API starts but reports `rules_ready: false`
#   at /v1/health instead of validating claims.
#
# SHAPE
#   Multi-stage, managed by uv, non-root, lean. Dependencies come from the
#   frozen lockfile into their own layer (rebuilt only when pyproject.toml or
#   uv.lock change); the source is copied after, and the project is installed
#   so the `claimguard` console script exists in the image. Only the base
#   runtime dependencies land here — the heavy optional extras (pii, llm, eval)
#   stay out by design, exactly as pyproject.toml declares them.
# ---------------------------------------------------------------------------

# --- Stage 1: uv binary, pinned to the team toolchain (uv 0.12.0) ----------
FROM ghcr.io/astral-sh/uv:0.12.0 AS uv-image

# --- Stage 2: runtime ------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The official uv image ships the binaries at /uv and /uvx.
COPY --from=uv-image /uv /uvx /bin/

# --- Dependency layer (cached across builds) -------------------------------
# --frozen: uv.lock is authoritative. --no-install-project: the source arrives
# in the next layer, keeping this layer reusable.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Application source -----------------------------------------------------
# alembic.ini + claimguard/db/migrations are included so `alembic upgrade head`
# works in the image (docker-compose.yml runs it as a one-shot `migrate`
# service before the API starts). scripts/ is included so the `claimguard`
# console script can run its own tooling in the image, not just on a host.
COPY alembic.ini ./
COPY claimguard ./claimguard
COPY scripts ./scripts

# Install the project itself: the dependency layer above is already warm, so
# this only adds the package and its `claimguard` console script.
RUN uv sync --frozen --no-dev

# --- Non-root user ----------------------------------------------------------
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness: the API answers on the readiness endpoint that exists
# (GET /v1/health; there is no /health). The body also carries readiness —
# `database`, `schema_revision`, `rules_dir`, `rules_ready` — so an operator
# reads the verdict from the body rather than inferring it from the status code.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3)"]

# The application: the review API and the reviewer interface, one factory.
# `--factory` is required because the target is a factory, not an instance.
CMD ["python", "-m", "uvicorn", "claimguard.review.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000"]
