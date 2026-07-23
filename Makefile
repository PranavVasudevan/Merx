# BankLens — developer task runner.
# On Windows, `make` may not be present; the PowerShell scripts in scripts/ mirror
# these targets. If you have Git Bash / WSL / choco make, these work directly.

.DEFAULT_GOAL := help
PY ?= python
ING_SRC := pipelines/ingestion/src
TRF_SRC := pipelines/transforms/src
export PYTHONPATH := $(ING_SRC):$(TRF_SRC)

.PHONY: help slice test lint fmt up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

slice: ## Run the Phase-1 vertical slice (CERT=3511 by default)
	$(PY) -m banklens_ingestion.cli --cert $(or $(CERT),3511) --quarters $(or $(QUARTERS),6)

test: ## Run the hermetic test suites
	$(PY) pipelines/transforms/tests/test_gold_metrics.py
	$(PY) pipelines/ingestion/tests/test_fdic.py

lint: ## Lint Python (requires ruff)
	ruff check pipelines

fmt: ## Format Python (requires black + ruff)
	black pipelines && ruff check --fix pipelines

up: ## Start local infra (Postgres/MinIO/ClickHouse) — needs Docker
	docker compose -f platform/docker/docker-compose.dev.yml up -d

down: ## Stop local infra
	docker compose -f platform/docker/docker-compose.dev.yml down

clean: ## Remove landed local data
	rm -rf data/bronze data/silver data/gold
