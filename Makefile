# TallyAero Maneuver Overlay Tool — top-level Makefile
# All targets assume the venv at ./venv is the active interpreter.

PY := venv/bin/python
PIP := venv/bin/pip
PYTEST := venv/bin/pytest
RUFF := venv/bin/ruff
PORT ?= 8050

.PHONY: help install install-dev run test test-v snapshot-update lint clean kill-server

help:
	@echo "Targets:"
	@echo "  install        Install runtime deps into ./venv"
	@echo "  install-dev    Install runtime + dev deps (pytest, syrupy, ruff)"
	@echo "  run            Start the Dash dev server on PORT=$(PORT)"
	@echo "  test           Run all pytest tests quietly"
	@echo "  test-v         Run pytest verbosely"
	@echo "  snapshot-update Regenerate syrupy snapshots (deliberate physics changes)"
	@echo "  lint           Run ruff over the codebase"
	@echo "  kill-server    Kill any process listening on PORT"
	@echo "  clean          Remove __pycache__, .pytest_cache, *.pyc"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements.txt
	$(PIP) install -e ".[dev]"

run:
	TALLYAERO_OVERLAY_LOG=INFO $(PY) app.py $(PORT)

test:
	$(PYTEST) -q

test-v:
	$(PYTEST) -v

snapshot-update:
	$(PYTEST) --snapshot-update -v tests/test_snapshots.py

lint:
	$(RUFF) check .

kill-server:
	@lsof -ti:$(PORT) | xargs -r kill -9 || true

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
	find . -name "*.pyc" -delete
