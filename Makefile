# Tender Intelligence Engine. `make trace` and `make report` arrive in Stages 3 and 4.
COMPOSE := docker compose
STATIC_IP := $(shell cat infra/STATIC-IP.txt)
RUN_TESTS := $(COMPOSE) run --rm --no-deps -T tests

.PHONY: up down test test-e2e check watch migrate deploy logs smoke client hooks evidence-corpus

up: hooks ## start the app and the test watcher
	$(COMPOSE) up -d --build
	@echo "app: https://$(STATIC_IP)/   watcher: make watch"

down: ## stop everything (data volumes are kept)
	$(COMPOSE) down

test: ## full python suite and web unit tests, once
	$(RUN_TESTS) python -m pytest -p no:cacheprovider
	$(RUN_TESTS) sh -c "cd web && node node_modules/vitest/vitest.mjs run"

test-e2e: ## slow tests that call the real LLM on a real tender PDF
	$(RUN_TESTS) python -m pytest -p no:cacheprovider -m slow -s tests/e2e

check: ## every watcher check once; writes .ci/status.json
	$(RUN_TESTS) python infra/ci/run_checks.py --once

watch: ## show the watcher status and follow its output
	@cat .ci/status.json 2>/dev/null || echo "no status yet"
	$(COMPOSE) logs -f --tail=20 tests

migrate: ## apply database migrations to the app database
	$(COMPOSE) run --rm -T api alembic upgrade head

deploy: hooks ## pull, build, migrate, restart, health check
	-git pull --ff-only
	$(COMPOSE) build
	$(COMPOSE) up -d db
	$(COMPOSE) run --rm -T api alembic upgrade head
	$(COMPOSE) run --rm -T --no-deps web npm ci --no-audit --no-fund
	$(COMPOSE) up -d --force-recreate api worker web caddy tests
	@for i in $$(seq 1 30); do \
	  if curl -ksf https://$(STATIC_IP)/health >/dev/null; then \
	    echo "healthy: $$(curl -ks https://$(STATIC_IP)/health)"; exit 0; fi; sleep 2; done; \
	  echo "health check failed: https://$(STATIC_IP)/health"; $(COMPOSE) ps; exit 1

logs: ## follow logs of every service
	$(COMPOSE) logs -f --tail=50

smoke: ## one real, logged call to the extraction model
	$(COMPOSE) run --rm -T api python -m scripts.llm_smoke $(PDF)

evidence-corpus: ## pass rate of the evidence resolver on tests/core/evidence_corpus
	$(RUN_TESTS) python -m scripts.evidence_corpus run --failures

client: ## regenerate the OpenAPI document and the TypeScript client types
	$(RUN_TESTS) python -m scripts.export_openapi --write

hooks: ## enable the pre-commit hook that blocks commits over a red watcher
	@git config core.hooksPath infra/hooks
