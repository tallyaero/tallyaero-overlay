# AeroEdge EM Diagram — top-level Makefile
# All targets assume the venv at ./venv is the active interpreter.

PY := venv/bin/python
PIP := venv/bin/pip
PYTEST := venv/bin/pytest
PORT ?= 8051

.PHONY: help install install-dev run test test-v snapshot freeze clean kill-server build build-clean install-build

help:
	@echo "Targets:"
	@echo "  install        Install runtime deps into ./venv"
	@echo "  install-dev    Install runtime + dev deps"
	@echo "  install-build  Install PyInstaller (build-time only)"
	@echo "  run            Start the Dash dev server on PORT=$(PORT)"
	@echo "  test           Run all pytest tests quietly"
	@echo "  test-v         Run pytest verbosely with full output"
	@echo "  snapshot       Regenerate golden figure snapshots (deliberate physics changes only)"
	@echo "  freeze         Compile requirements.txt to requirements.lock.txt via pip-compile"
	@echo "  kill-server    Kill any process listening on PORT"
	@echo "  clean          Remove __pycache__, .pytest_cache, *.pyc"
	@echo "  build          Build a one-dir bundle via PyInstaller (Phase 6)"
	@echo "  build-clean    Remove build/ and dist/ artifacts"
	@echo "  sync-check     Report drift vs overlay tool tree (Phase 7)"
	@echo "  sync-check-verbose       Same, with per-file rows on glob entries"
	@echo "  sync-apply-to-overlay    Copy EM → overlay for any drifted/missing files"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements.txt -r requirements-dev.txt

run:
	AEROEDGE_LOG=WARNING $(PY) app.py $(PORT)

test:
	$(PYTEST) -q

test-v:
	$(PYTEST) -v

snapshot:
	$(PYTEST) --snapshot-update -v tests/test_figure_snapshot.py

freeze:
	venv/bin/pip-compile --output-file=requirements.lock.txt requirements.txt
	venv/bin/pip-compile --output-file=requirements-dev.lock.txt requirements-dev.txt

kill-server:
	@lsof -ti:$(PORT) | xargs -r kill -9 || true

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
	find . -name "*.pyc" -delete

# ─── Phase 6: PyInstaller bundle ────────────────────────────────────────
install-build:
	$(PY) -m pip install pyinstaller

build:
	$(PY) -m PyInstaller tallyaero_em.spec --noconfirm --clean

build-clean:
	rm -rf build/ dist/

# ─── Phase 6S: Ship pipeline (macOS) ────────────────────────────────────
# `make ship-mac` runs the full chain: build → icons → sign → notarize → DMG.
# Requires Developer ID Application cert in keychain + notarytool profile
# named TALLYAERO_NOTARY (see BUILD.md).
icons:
	bash scripts/build_icons.sh

sign:
	bash scripts/sign_macos.sh

dmg:
	bash scripts/build_dmg.sh

ship-mac: build-clean icons build sign dmg
	@echo ""
	@echo "✓ Ship pipeline complete."
	@ls -lh dist/*.dmg 2>/dev/null || true

# ─── Phase 7: cross-app drift detector ─────────────────────────────────
sync-check:
	$(PY) scripts/sync_check.py

sync-check-verbose:
	$(PY) scripts/sync_check.py --verbose

sync-apply-to-overlay:
	$(PY) scripts/sync_check.py --apply em-to-overlay
