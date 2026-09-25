# Gen-2 build checks (task 0a deliverable 4; charter "Standing rules": a
# boundary-graph violation fails the build). These targets read gen2/, tools/
# and docs/gen2/ only; gen-1's test command stays as documented in
# CONTRIBUTING.md.
PYTHON ?= python3

.PHONY: gen2-check gen2-boundaries gen2-test

gen2-check: gen2-boundaries gen2-test
	@echo "gen2-check: all checks passed"

gen2-boundaries:
	$(PYTHON) tools/check_boundaries.py

gen2-test:
	$(PYTHON) -m unittest discover -s gen2/tests -p 'test_*.py'
