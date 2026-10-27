# make up | run | demo | test | test-integration | test-e2e | lint | audit | sbom | down      (make help lists everything)
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
SERVE := $(VENV)/bin/gunicorn -c python:oidc_login.interfaces.gunicorn_conf "oidc_login.interfaces.wsgi:build_app()"

-include .env
export

.PHONY: help install env up idp-check run demo health lint format test test-integration test-e2e test-all audit sbom \
        check docker-build docker-run down clean

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file

env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }

# Start Keycloak and wait until the demo realm is imported and the provider answers.
up: env $(STAMP) ## start the identity provider (Keycloak) with the demo realm and wait until it is ready
	docker compose up -d --wait keycloak
	@$(MAKE) --no-print-directory idp-check

idp-check: ## step 1: the discovery document and the signing keys are reachable
	@curl -fsS $(OIDC_ISSUER)/.well-known/openid-configuration | $(PY) -c "import json,sys; d=json.load(sys.stdin); print('issuer                ', d['issuer']); print('authorization_endpoint', d['authorization_endpoint']); print('jwks_uri              ', d['jwks_uri'])"
	@curl -fsS $(OIDC_ISSUER)/protocol/openid-connect/certs | $(PY) -c "import json,sys; print('signing keys          ', len(json.load(sys.stdin)['keys']))"

# Foreground server: gunicorn on APP_HOST:APP_PORT, SIGTERM or Ctrl-C shuts it down gracefully.
run: env $(STAMP) ## start the app on http://localhost:3000 (needs make up)
	$(SERVE)

demo: env $(STAMP) ## run the lesson's scenario against the provider: sign-in, each protection, refresh, logout (needs make up)
	$(PY) -m oidc_login.interfaces.demo_cli

health: $(STAMP) ## exit 0 when the running app answers /healthz
	$(VENV)/bin/oidc-login-health

lint: $(STAMP) ## ruff check (with security rules), ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

# Unit tests need no provider. The domain and application must stay at 95% coverage or more.
test: $(STAMP) ## unit tests with coverage (no provider needed)
	$(PY) -m pytest tests/unit --cov=oidc_login --cov-report=term
	$(PY) -m coverage report --include='src/oidc_login/domain/*,src/oidc_login/application/*' --fail-under=95

test-integration: $(STAMP) ## the provider adapter, token validation and the flow protections against Keycloak (needs make up)
	$(PY) -m pytest tests/integration -m integration -v

test-e2e: $(STAMP) ## a real server process, a scripted browser and Keycloak (needs make up)
	$(PY) -m pytest tests/e2e -m e2e -v

test-all: test test-integration test-e2e ## every test level (needs make up)

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

sbom: $(STAMP) ## write sbom.cdx.json (CycloneDX) for the locked runtime dependencies
	$(VENV)/bin/cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json
	@echo "wrote sbom.cdx.json"

check: lint test ## everything that needs no provider

docker-build: ## build the container image
	docker build -t security-oauth-login-done-right:dev .

docker-run: env ## run the image next to Keycloak and wait until it is healthy
	docker compose --profile app up -d --wait --build app

down: ## stop the containers and delete their data
	docker compose --profile app down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage sbom.cdx.json
