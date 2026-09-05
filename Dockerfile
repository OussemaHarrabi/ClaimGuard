# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# ClaimGuard AI — API image
#
#   docker build -t claimguard-api .
#
# Multi-stage, managed by uv, non-root, lean:
#   * dependencies are installed from the frozen lockfile into their own layer
#     (rebuilt only when pyproject.toml / uv.lock change);
#   * the project itself is installed as plain source (--no-install-project),
#     so the app code layer stays thin;
#   * only the base runtime dependencies land in the image — heavy optional
#     extras (pii, llm, eval) stay out, exactly as designed in pyproject.toml.
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
# --frozen: uv.lock is authoritative. --no-install-project: source is copied
# in the next layer, keeping this layer reusable.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Application source -----------------------------------------------------
COPY claimguard ./claimguard

# --- Non-root user ----------------------------------------------------------
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness: the API exposes GET /health (stdlib urllib — no curl needed).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# FastAPI app entry — claimguard.api.main:app (see docs/05 §"run the API").
CMD ["python", "-m", "uvicorn", "claimguard.api.main:app", "--host", "0.0.0.0", "--port", "8000"]