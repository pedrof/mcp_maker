.PHONY: dev stop test lint lint-fix build push migrate venv clean deploy-k3s deploy-ocp

BACKEND_DIR   := backend
VENV          := .venv
PYTHON        := python3.12
PIP           := $(VENV)/bin/pip
PYTEST        := $(VENV)/bin/pytest
RUFF          := $(VENV)/bin/ruff
MYPY          := $(VENV)/bin/mypy
ALEMBIC       := $(VENV)/bin/alembic
IMAGE_TAG     ?= dev
REGISTRY      ?= git.shadyknollcave.io/micro/forge
PLATFORM      ?= k3s

# ── Local dev ────────────────────────────────────────────────────────────────

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -e ".[dev]"

dev: venv
	podman-compose up --build

stop:
	podman-compose down

# ── Testing ──────────────────────────────────────────────────────────────────

test: venv
	cd $(BACKEND_DIR) && ../$(PYTEST) -v --cov=app --cov-report=term-missing

# ── Lint ─────────────────────────────────────────────────────────────────────

lint: venv
	$(RUFF) check $(BACKEND_DIR)/app $(BACKEND_DIR)/tests $(BACKEND_DIR)/migrations
	$(MYPY) $(BACKEND_DIR)/app

lint-fix: venv
	$(RUFF) check --fix $(BACKEND_DIR)/app $(BACKEND_DIR)/tests

# ── Database ─────────────────────────────────────────────────────────────────

migrate: venv
	cd $(BACKEND_DIR) && ../$(ALEMBIC) upgrade head

migrate-new: venv
	cd $(BACKEND_DIR) && ../$(ALEMBIC) revision --autogenerate -m "$(msg)"

# ── Container build ──────────────────────────────────────────────────────────

build:
	podman build -t $(REGISTRY)-backend:$(IMAGE_TAG) $(BACKEND_DIR) -f $(BACKEND_DIR)/Containerfile

push: build
	podman push $(REGISTRY)-backend:$(IMAGE_TAG)

# ── Deploy ───────────────────────────────────────────────────────────────────

deploy-k3s:
	kubectl apply -k deploy/kustomize/overlays/prod
	argocd app sync argocd/forge --core

deploy-ocp:
	kubectl apply -k deploy/kustomize/overlays/openshift
	argocd app sync argocd/forge --core

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(VENV) .mypy_cache .ruff_cache .pytest_cache
