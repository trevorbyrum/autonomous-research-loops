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
GEN2_TEST_ARGS ?=
GEN2_MUTATION_ARGS ?=
GEN2_CI_MODE ?= push
GEN2_CI_SHARD ?= 1/1
GEN2_GATEWAY_MODE ?= all
GEN2_BASE ?= origin/gen2
GEN2_COVERAGE ?= build/gen2-coverage.sqlite
GEN2_TEST_WORKERS ?= 8

GEN2_CC_MAX_FUNCTION = 48
GEN2_CC_MAX_AVERAGE = 10

.PHONY: gen2-check gen2-accept gen2-venv gen2-sqlite gen2-sqlite-native gen2-boundaries gen2-complexity gen2-debt gen2-locators gen2-schemas gen2-ddl gen2-catalog gen2-catalog-check gen2-test gen2-mutation gen2-mutation-report gen2-size gen2-linecount gen2-auth-demo gen2-gateway

gen2-check: gen2-sqlite gen2-sqlite-native gen2-boundaries gen2-complexity gen2-debt gen2-locators gen2-schemas gen2-ddl gen2-catalog-check gen2-test gen2-size
	@echo "gen2-check: all checks passed"

# Acceptance runs the full checks, then changed-line mutation.
gen2-accept: export GEN2_TEST_COVERAGE = $(abspath $(GEN2_COVERAGE))
gen2-accept: GEN2_TEST_ARGS += --workers $(GEN2_TEST_WORKERS)
gen2-accept: export GEN2_MUTATION_ARGS += --workers $(GEN2_TEST_WORKERS)
gen2-accept: gen2-check
	$(MAKE) gen2-mutation
	@echo "gen2-accept: all checks passed"

.PHONY: gen2-push gen2-ci gen2-ci-default gen2-ci-unit gen2-ci-mutation gen2-ci-gateway-no-db gen2-ci-gateway-db
# T0 is deliberately separate from full acceptance. No acceptance verdict is
# inferred from this target. Full acceptance uses gen2-accept.
gen2-push: gen2-sqlite gen2-boundaries gen2-size gen2-schemas gen2-ddl gen2-catalog-check gen2-complexity gen2-debt gen2-locators

gen2-ci: gen2-venv
	$(PYTHON) tools/gen2_ci.py --mode $(GEN2_CI_MODE) --shard $(GEN2_CI_SHARD)

# The currently deployed library has one execution. Keep the long modes
# independently runnable for v1.2. Only the declared unit partition runs here;
# all eight partitions (or the unsharded target) are required for full units.
gen2-ci-default: gen2-venv
	$(PYTHON) tools/gen2_ci.py --mode default

gen2-ci-unit:
	$(MAKE) gen2-ci GEN2_CI_MODE=engine-unit

gen2-ci-mutation:
	$(MAKE) gen2-ci GEN2_CI_MODE=engine-mutation

gen2-ci-gateway-no-db:
	$(MAKE) gen2-ci GEN2_CI_MODE=gateway-no-db GEN2_CI_SHARD=1/1

gen2-ci-gateway-db:
	$(MAKE) gen2-ci GEN2_CI_MODE=gateway-db GEN2_CI_SHARD=1/1

# (Re)built when either lock changes; `venv --clear` starts from an empty
# environment, and `--no-deps` means the locks must list every transitive
# dependency (an incomplete lock fails at import, loudly).
gen2-venv: $(GEN2_VENV)/.gen2-installed

$(GEN2_VENV)/.gen2-installed: gen2/requirements.txt gen2/requirements-dev.txt gen2/requirements-build.txt
	$(PYTHON_BOOTSTRAP) -m venv --clear $(GEN2_VENV)
	$(GEN2_VENV)/bin/python -m pip install --no-input --disable-pip-version-check --require-hashes --no-deps --only-binary=:all: -r gen2/requirements-build.txt
	$(GEN2_VENV)/bin/python -m pip install --no-build-isolation --no-input --disable-pip-version-check --require-hashes --no-deps \
		-r gen2/requirements.txt -r gen2/requirements-dev.txt
	$(GEN2_VENV)/bin/python -c "import rfc8785, jsonschema, rope, hypothesis, time_machine, radon, cosmic_ray, pytest, coverage"
	touch $@

# The store's SQLite compatibility gate (gen2/store/compat.py; Astra third
# review ruling 4), run first: the same numeric version floor, JSON probes and
# connection-pragma read-back the store's open path runs. It prints what it
# ran on (the SQLite version this build actually used); GEN2_SQLITE_REPORT=PATH
# also appends that record to PATH (CI: the job summary). Exit 1 = refused.
gen2-sqlite: gen2-venv
	$(PYTHON) -m gen2.store.compat $(if $(GEN2_SQLITE_REPORT),--report "$(GEN2_SQLITE_REPORT)")

# Native writes bypass the retained-support SQL observer (2d-4c-p4b2c2 closure).
gen2-sqlite-native: gen2-venv
	$(PYTHON) tools/check_gen2_sqlite_native.py

gen2-boundaries: gen2-venv
	$(PYTHON) tools/check_boundaries.py

# Absolute cyclomatic ceilings over engine and gateway production functions,
# including methods and closures (ruling 3 / D5). No ledger or exemptions.
gen2-complexity: gen2-venv
	$(PYTHON) tools/check_gen2_complexity.py --max-function $(GEN2_CC_MAX_FUNCTION) --max-average $(GEN2_CC_MAX_AVERAGE)

# The debt register's phase-close check (charter "Root-cause fixes, not patches";
# task 2q-a; tools/check_gen2_debt.py): docs/gen2/DEBT-REGISTER.md against
# docs/gen2/phase-status.json. Fails when a closed task or phase still owns an open
# entry. A task or phase is set to closed in the status file when it is accepted.
gen2-debt: gen2-venv
	$(PYTHON) tools/check_gen2_debt.py

# Every file and function locator in backticks in docs/gen2/INVARIANTS.md and
# DEBT-REGISTER.md must exist (task 2q-a; tools/check_gen2_locators.py): line numbers
# may drift, names may not.
gen2-locators: gen2-venv
	$(PYTHON) tools/check_gen2_locators.py

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
	$(PYTHON) tools/gen2_test.py $(GEN2_TEST_ARGS)

# Acceptance mutates changed production lines against the explicit merge-base.
gen2-mutation: gen2-venv
	$(PYTHON) tools/gen2_mutation_scope.py --base "$(GEN2_BASE)" --coverage "$(GEN2_COVERAGE)" $(GEN2_MUTATION_ARGS)

# Full production campaigns are advisory evidence for phase gates and Gate S.
gen2-mutation-report: gen2-venv
	$(PYTHON) tools/gen2_mutation_scope.py --full --report-only --coverage "$(GEN2_COVERAGE)" $(GEN2_MUTATION_ARGS)

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

# The gateway repairs of task 2b (tools/gen2_gateway_check.py): the gateway's own
# suite, again on a throwaway PostgreSQL cluster (a temporary directory, a Unix socket,
# no TCP port; never an existing database). The gateway is a
# separate package with its own dependency (psycopg), so this runs on the gateway's
# interpreter ($(PYTHON_BOOTSTRAP)), not the gen-2 venv, and needs PostgreSQL server
# binaries; not part of gen2-check. Exit status is the checks' own: no pipe.
gen2-gateway:
	$(PYTHON_BOOTSTRAP) tools/gen2_gateway_check.py --mode $(GEN2_GATEWAY_MODE)

# Prepared, opt-in only: the ci-2 amendment keeps gateway dependency provisioning
# and DB execution off the default path until image :2 is confirmed on cir.
.PHONY: gen2-gateway-venv gen2-gateway-ci
gen2-gateway-venv: .venv-gateway-ci/.installed

.venv-gateway-ci/.installed: gateway/requirements-ci.txt
	$(PYTHON_BOOTSTRAP) -m venv --clear .venv-gateway-ci
	.venv-gateway-ci/bin/python -m pip install --no-input --disable-pip-version-check --require-hashes --no-deps --only-binary=:all: -r gateway/requirements-ci.txt
	.venv-gateway-ci/bin/python -m pip check
	.venv-gateway-ci/bin/python -c "import psycopg; print(psycopg.__version__, psycopg.pq.version())"
	touch $@

gen2-gateway-ci: gen2-gateway-venv
	.venv-gateway-ci/bin/python tools/gen2_gateway_check.py --mode $(GEN2_GATEWAY_MODE)
