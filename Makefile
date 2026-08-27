# Single entry point for the project. Every generated artifact is produced by
# a target here; the repository carries the recipe, not the product.

UV ?= uv

.DEFAULT_GOAL := all
.PHONY: all help setup scaffold lint fmt test audit install-hook \
        schemas bench-setup bench eval manuscript clean

all: lint test audit

help:
	@echo "setup         create the virtual environment and install dependencies"
	@echo "scaffold      prepare a fresh clone for work (env plus untracked directories)"
	@echo "lint          run ruff over the tree"
	@echo "fmt           format the tree with ruff"
	@echo "test          run the test suite"
	@echo "audit         run the pre-push repository hygiene checks"
	@echo "install-hook  install the audit script as a pre-push hook"
	@echo "schemas       validate every Lifecycle IR example against its schema"
	@echo "bench-setup   clone and pin the target application"
	@echo "bench         run the change-request set across the arms"
	@echo "eval          regenerate every metric and figure from runs/"
	@echo "manuscript    build the manuscript PDF"
	@echo "clean         remove caches and build state"

setup:
	$(UV) sync

# Directories that git cannot carry: manuscript/ is untracked, and the
# generated-output directories are ignored except for their .gitkeep.
scaffold: setup
	mkdir -p manuscript runs figures data

lint:
	$(UV) run ruff check .

fmt:
	$(UV) run ruff format .

test:
	$(UV) run pytest

audit:
	@bash infra/audit.sh

install-hook:
	@bash infra/audit.sh --install-hook

schemas:
	@echo "schemas: implemented in phase 1"; exit 1

bench-setup:
	@echo "bench-setup: implemented in phase 2"; exit 1

bench:
	@echo "bench: implemented in phase 2"; exit 1

eval:
	@echo "eval: implemented in phase 4"; exit 1

manuscript:
	@echo "manuscript: implemented in phase 5"; exit 1

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
