# Single entry point for the project. Every generated artifact is produced by
# a target here; the repository carries the recipe, not the product.

UV ?= uv

.DEFAULT_GOAL := all
.PHONY: all help setup scaffold lint fmt test audit install-hook \
        schemas bench-setup bench-status bench-validate calibrate bench bench-plan smoke stack-start stack-stop stack-status eval project manuscript manuscript-budget clean

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
	@echo "bench-setup   clone the target application at its pin and check it builds and starts"
	@echo "bench-status  report whether the local checkout matches the pin"
	@echo "bench-validate check the change-request set against its schema and the pin"
	@echo "calibrate     check every hidden check is red on the pristine pin"
	@echo "evidence      capture the incident evidence from the running application"
	@echo "review-sample build the arm-concealed review packet;  review-verify  check it"
	@echo "review-start/-stop/-abandon ITEM=<item>   time one review;  review-status"
	@echo "review-ingest reduce the timings to the per-arm figure make eval reads"
	@echo "bench         run the change-request set across the arms"
	@echo "bench-plan    list the cells a run would cover, and which are pending"
	@echo "smoke         prove the executor plumbing with one trivial run"
	@echo "stack-start   run the target application locally as folder-local processes"
	@echo "stack-stop    stop it;  stack-status  report on each service"
	@echo "eval          regenerate every metric and figure from runs/"
	@echo "manuscript    regenerate its numbers and build the PDF"
	@echo "manuscript-budget  count the manuscript against its word budget"
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
	$(UV) run python lifecycle-ir/validate.py examples

bench-validate:
	@$(UV) run python -m pipelines.common.changerequests

calibrate:
	$(UV) run python infra/calibrate.py $(CALIBRATE_FLAGS)

evidence:
	$(UV) run python infra/capture_evidence.py $(EVIDENCE_FLAGS)

review-sample:
	$(UV) run python -m eval.review sample $(REVIEW_FLAGS)

review-verify:
	@$(UV) run python -m eval.review verify

review-start:
	@$(UV) run python -m eval.review start $(ITEM)

review-stop:
	@$(UV) run python -m eval.review stop $(ITEM)

review-abandon:
	@$(UV) run python -m eval.review abandon $(ITEM)

review-status:
	@$(UV) run python -m eval.review status

review-ingest:
	$(UV) run python -m eval.review ingest

bench-setup:
	$(UV) run python infra/bench_setup.py $(BENCH_SETUP_FLAGS)

bench-status:
	@$(UV) run python infra/bench_setup.py --status

bench:
	$(UV) run python -m pipelines.common.runner $(BENCH_FLAGS)

bench-plan:
	@$(UV) run python -m pipelines.common.runner --plan $(BENCH_FLAGS)

smoke:
	$(UV) run python infra/smoke.py $(SMOKE_FLAGS)

stack-start:
	$(UV) run python infra/stack.py start

stack-stop:
	@$(UV) run python infra/stack.py stop

stack-status:
	@$(UV) run python infra/stack.py status

eval:
	@$(UV) run python -m eval.report $(EVAL_FLAGS)

project:
	@$(UV) run python -m eval.projection $(PROJECT_FLAGS)

manuscript:
	@bash infra/build_manuscript.sh $(MANUSCRIPT_FLAGS)

manuscript-budget:
	@$(UV) run python infra/wordcount.py manuscript/main.tex

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
