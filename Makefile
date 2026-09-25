# Gen-2 build checks (task 0a deliverable 4; charter "Standing rules": a
# boundary-graph violation fails the build). These targets read gen2/, tools/
# and docs/gen2/ only; gen-1's test command stays as documented in
# CONTRIBUTING.md.
PYTHON ?= python3

.PHONY: gen2-check gen2-boundaries gen2-schemas gen2-ddl gen2-test gen2-mutation gen2-size gen2-linecount

gen2-check: gen2-boundaries gen2-schemas gen2-ddl gen2-test gen2-mutation gen2-size
	@echo "gen2-check: all checks passed"

gen2-boundaries:
	$(PYTHON) tools/check_boundaries.py

# Needs jsonschema (pip install -r gen2/requirements-dev.txt); fails loudly without it.
gen2-schemas:
	$(PYTHON) tools/check_gen2_schemas.py --part schemas

gen2-ddl:
	$(PYTHON) tools/check_gen2_schemas.py --part ddl

gen2-test:
	$(PYTHON) -m unittest discover -s gen2/tests -p 'test_*.py'

# Every guard in tools/gen2_mutations.py is removed in memory and its named
# tests must fail (task 0a-repair: fixes must be mutation-testable).
gen2-mutation:
	$(PYTHON) tools/gen2_mutations.py

# Size budget (charter; design review §10): fails above the 12,000-line ceiling.
gen2-size:
	$(PYTHON) tools/gen2_linecount.py --check

# Full report, including the like-for-like gen-1 recount.
gen2-linecount:
	$(PYTHON) tools/gen2_linecount.py --gen1-baseline
