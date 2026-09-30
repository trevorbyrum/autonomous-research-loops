# Gen-2 build checks (task 0a deliverable 4; charter "Standing rules": a
# boundary-graph violation fails the build). These targets read gen2/, tools/
# and docs/gen2/ only; gen-1's test command stays as documented in
# CONTRIBUTING.md.
#
# Every check runs on the project-isolated build environment (a venv at
# $(GEN2_VENV), built by gen2-venv from the hash-locked requirements with
# --require-hashes --no-deps) — never on a shared interpreter's packages
# (Astra re-review ruling: `pip install --user --break-system-packages` is not
# a build practice). docs/gen2/ENVIRONMENT.md. CI runs these same targets.
PYTHON_BOOTSTRAP ?= python3
GEN2_VENV ?= .venv-gen2
PYTHON ?= $(GEN2_VENV)/bin/python

GEN2_SQLITE_REPORT ?=

.PHONY: gen2-check gen2-venv gen2-sqlite gen2-boundaries gen2-schemas gen2-ddl gen2-catalog gen2-catalog-check gen2-test gen2-trigger-order gen2-mutation gen2-size gen2-linecount gen2-auth-demo

gen2-check: gen2-sqlite gen2-boundaries gen2-schemas gen2-ddl gen2-catalog-check gen2-test gen2-trigger-order gen2-mutation gen2-size
	@echo "gen2-check: all checks passed"

# (Re)built when either lock changes; `venv --clear` starts from an empty
# environment, and `--no-deps` means the locks must list every transitive
# dependency (an incomplete lock fails at import, loudly).
gen2-venv: $(GEN2_VENV)/.gen2-installed

$(GEN2_VENV)/.gen2-installed: gen2/requirements.txt gen2/requirements-dev.txt
	$(PYTHON_BOOTSTRAP) -m venv --clear $(GEN2_VENV)
	$(GEN2_VENV)/bin/python -m pip install --no-input --disable-pip-version-check --require-hashes --no-deps \
		-r gen2/requirements.txt -r gen2/requirements-dev.txt
	$(GEN2_VENV)/bin/python -c "import rfc8785, jsonschema"
	touch $@

# The store's SQLite compatibility gate (gen2/store/compat.py; Astra third
# review ruling 4), run first: the same numeric version floor, JSON probes and
# connection-pragma read-back the store's open path runs. It prints what it
# ran on (the SQLite version this build actually used); GEN2_SQLITE_REPORT=PATH
# also appends that record to PATH (CI: the job summary). Exit 1 = refused.
gen2-sqlite: gen2-venv
	$(PYTHON) -m gen2.store.compat $(if $(GEN2_SQLITE_REPORT),--report "$(GEN2_SQLITE_REPORT)")

gen2-boundaries: gen2-venv
	$(PYTHON) tools/check_boundaries.py

# Needs the hash-locked runtime deps (rfc8785, used by gen2/core/canonical.py)
# and the dev-only validator (jsonschema) — both in $(GEN2_VENV); each check
# fails loudly without them.
gen2-schemas: gen2-venv
	$(PYTHON) tools/check_gen2_schemas.py --part schemas

gen2-ddl: gen2-venv
	$(PYTHON) tools/check_gen2_schemas.py --part ddl

# The generated key catalog and .env example (task 0c deliverable 2): both are
# derived from the gateway source registry, which is the one source of truth.
# gen2-catalog-check (part of gen2-check) fails when the registry and either
# artifact disagree — a new or changed source that was not regenerated, and a
# hand edit of either generated file. gen2-catalog rewrites them.
gen2-catalog: gen2-venv
	$(PYTHON) tools/gen_source_catalog.py

gen2-catalog-check: gen2-venv
	$(PYTHON) tools/gen_source_catalog.py --check

# Verbose, with the whole output kept in a log file whose path it prints
# (tools/gen2_test.py; GEN2_TEST_LOG names it). No pipe: the exit status is
# unittest's own.
gen2-test: gen2-venv
	$(PYTHON) tools/gen2_test.py

# The whole store suite again with every trigger re-created in reverse order;
# every test and subtest must have the same outcome (task 0b cleanup 2: no
# assertion may depend on SQLite's trigger-firing order).
gen2-trigger-order: gen2-venv
	$(PYTHON) tools/gen2_trigger_order.py

# Every guard in the inventory (tools/gen2_mutants/, run by
# tools/gen2_mutations.py) is removed in memory and its named tests must fail
# (task 0a-repair: fixes must be mutation-testable).
gen2-mutation: gen2-venv
	$(PYTHON) tools/gen2_mutations.py

# Size rules (charter "Size rules"; task 2r): fails on a hand-written gen-2
# file over 1,500 lines (generated files are exempt only by the reasoned list
# in tools/gen2_linecount.py) and when production reaches the 15,000-line
# growth-review trigger.
gen2-size: gen2-venv
	$(PYTHON) tools/gen2_linecount.py --check

# Full report, including the like-for-like gen-1 recount.
gen2-linecount: gen2-venv
	$(PYTHON) tools/gen2_linecount.py --gen1-baseline

# The DEPLOYMENT-CONTRACT §4 auth-volume demonstrations (task 1f;
# docs/gen2/AUTH-DEMO.md): builds the engine image (deploy/gen2/Dockerfile),
# runs the compose slice (deploy/gen2/compose.yaml) under its own project
# name, and asserts each demonstration mechanically. Needs Docker with
# Compose; not part of gen2-check. DEMOS=a,b,c,c-control,d1,d2a,d2b,e runs a
# subset. Exit status is the demonstrations' own: no pipe.
gen2-auth-demo: gen2-venv
	$(PYTHON) deploy/gen2/demo/auth_demo.py $(if $(DEMOS),--only $(DEMOS))
