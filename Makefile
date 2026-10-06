# Tender Intelligence Engine. `make report` arrives in Stage 4.
COMPOSE := docker compose
STATIC_IP := $(shell cat infra/STATIC-IP.txt)
RUN_TESTS := $(COMPOSE) run --rm --no-deps -T tests

.PHONY: up down test test-e2e test-ui check watch migrate deploy logs smoke client hooks evidence-corpus trace gold eval feedback-report report

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

test-ui: ## the reviewer screen in a real browser (Playwright), on a seeded test tender
	$(COMPOSE) --profile e2e up -d --force-recreate api-e2e caddy-e2e
	$(COMPOSE) --profile e2e run --rm -T playwright; code=$$?; \
	  $(COMPOSE) --profile e2e rm -sf api-e2e caddy-e2e >/dev/null 2>&1; exit $$code

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

trace: ## regenerate docs/FIELD-TRACE.md from the schemas, routes, models and web sources
	$(RUN_TESTS) python -m scripts.gen_field_trace

client: ## regenerate the OpenAPI document and the TypeScript client types
	$(RUN_TESTS) python -m scripts.export_openapi --write

hooks: ## enable the pre-commit hook that blocks commits over a red watcher
	@git config core.hooksPath infra/hooks

gold: ## a completed review becomes a gold record: make gold TENDER=<slug>
	$(COMPOSE) exec -T api python -m scripts.make_gold --tender $(TENDER)

eval: ## score every gold record against the candidates in review; PROMPT=section/vN reads that section again first
	$(COMPOSE) exec -T api python -m evals.runner $(if $(PROMPT),--prompt $(PROMPT),)

feedback-report: ## FEEDBACK-REPORT.md from the feedback table
	$(COMPOSE) exec -T api python -m evals.feedback_report

report: ## RELIABILITY-REPORT.md and REVIEW-LOG.md from the gold records
	$(COMPOSE) exec -T api python -m evals.report

