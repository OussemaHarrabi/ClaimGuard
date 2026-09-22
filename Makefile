# ---------------------------------------------------------------------------
# ClaimGuard AI — developer targets
#
# Windows-friendly: targets only call `uv run ...` and `docker compose ...`
# (no bash-only syntax); run Make from Git Bash, WSL, or a POSIX shell.
# ---------------------------------------------------------------------------

UV      ?= uv
COMPOSE ?= docker compose

# Mentor-delivered benchmark pack (reference material — gitignored, not our source).
# It is the grading oracle: `make conformance` grades our engine with the mentor's
# own strict scorer plus an independently implemented second opinion.
PACK ?= ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack
OUT  ?= artifacts/edu

.PHONY: install lint typecheck test test-all migrate \
        edu-run edu-conformance up down

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

migrate: ## Apply Alembic migrations to the local database
	$(UV) run alembic upgrade head

edu-run: ## Run our 15-rule engine over all three mentor-pack splits
	@mkdir -p "$(OUT)"
	$(UV) run python -m claimguard.edu.run --claims "$(PACK)/data/development/claims.jsonl" --rules-dir "$(PACK)/rules" --output "$(OUT)/development.jsonl"
	$(UV) run python -m claimguard.edu.run --claims "$(PACK)/data/validation/claims.jsonl"  --rules-dir "$(PACK)/rules" --output "$(OUT)/validation.jsonl"
	$(UV) run python -m claimguard.edu.run --claims "$(PACK)/data/stress/claims.jsonl"      --rules-dir "$(PACK)/rules" --output "$(OUT)/stress.jsonl"

edu-conformance: edu-run ## Grade our output with the mentor's scorer + an independent second opinion
	$(UV) run python scripts/edu_conformance.py --pred "$(OUT)/{split}.jsonl" --all

up: ## Build and start the full stack — db, otel-lgtm, api, web
	$(COMPOSE) up --build -d

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down