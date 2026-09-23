# ---------------------------------------------------------------------------
# ClaimGuard AI — developer targets
#
# Windows-friendly: targets only call `uv run ...`, `docker compose ...` and one
# POSIX pipeline in `help` (no bash-only syntax); run Make from Git Bash, WSL or
# a POSIX shell. `make` on its own prints this list.
#
# The engine, the mentor scorer and the report generator are reached through the
# `claimguard` console (claimguard/cli/), which runs the repository's existing
# tooling rather than a second copy of it.
# ---------------------------------------------------------------------------

UV      ?= uv
COMPOSE ?= docker compose

# Mentor-delivered benchmark pack (reference material — gitignored, not our source).
# It is the grading oracle: `make conformance` grades our engine with the mentor's
# own strict scorer plus an independently implemented second opinion.
PACK   ?= ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack
OUT    ?= artifacts/edu
REPORT ?= docs/verification/EDU-EVALUATION-REPORT.md
SPLIT  ?= development

.DEFAULT_GOAL := help
.PHONY: help install lint typecheck test test-all migrate status serve \
        engine-run conformance edu-conformance report up down

help: ## List every target with its purpose
	@echo "ClaimGuard AI — make targets"
	@echo
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sort | sed 's/:.*## /\t/'

install: ## Install all dependencies (project + extras) into the project venv
	$(UV) sync --all-extras

lint: ## Ruff lint + format check (no writes)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: ## Pyright strict type check (see [tool.pyright] in pyproject.toml)
	$(UV) run pyright

test: ## Fast tests — unit + integration, no LLM, no e2e (daily loop)
	$(UV) run pytest -m "not llm and not e2e"

test-all: ## Full suite — requires live infra (DB, and LLM for e2e/llm markers)
	$(UV) run pytest

migrate: ## Apply Alembic migrations to the configured database
	$(UV) run alembic upgrade head

status: ## Readiness: contract in force, rule catalogue, database revision
	$(UV) run claimguard status

serve: ## Run the reviewer API + interface on http://127.0.0.1:8000 (reload on)
	$(UV) run claimguard serve --reload

engine-run: ## Run the engine over all three pack splits (no scoring)
	$(UV) run claimguard evaluate --split all --engine-only --pack-root "$(PACK)" --workdir "$(OUT)"

conformance: ## The gate: engine + mentor scorer + independent harness, all three splits
	$(UV) run claimguard evaluate --split all --pack-root "$(PACK)" --workdir "$(OUT)"

# Kept because docs/10-ADR-Starter-Pack-Authority.md §5.1 and
# docs/verification/EDU-PACK-CONFORMANCE.md cite `make edu-conformance` by name.
edu-conformance: conformance ## Alias of `conformance` (cited by ADR-10)

report: ## Write the versioned evaluation report for one split (SPLIT=..., REPORT=...)
	$(UV) run claimguard report --split "$(SPLIT)" --output "$(REPORT)" --pack-root "$(PACK)"

up: ## Build and start the demo stack — db, migrate, api (plus otel-lgtm)
	$(COMPOSE) up --build -d

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down
