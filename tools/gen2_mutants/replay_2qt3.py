"""Mutants of task 2q-t3 (the debt slice): the order `Router.status` lists its capability facts and engine-wide holds in (DEBT-023 item 2), and the harness's restoration of
the modules a serial case replaced (DEBT-025 NB1). Each is broken alone. The controls are by hand (nothing here was traced): the test of each family that reads the same rows or
runs the same restore without asserting the order or the state the mutant changes.

  2QT3-status-capability-facts-reversed         status lists the current capability facts by capability name, descending;
  2QT3-status-capability-facts-by-onset         ... by the instant each began (`since`), the order the rows were written in, not their name;
  2QT3-status-global-holds-reversed             status lists the open holds of no topic by the instant each was opened, newest first;
  2QT3-status-global-holds-by-subject           ... by the subject each holds, not the instant it was opened;
  2QT3-harness-a-case-keeps-the-replaced-module the restoration no longer puts a replaced `sys.modules` entry back;
  2QT3-harness-a-case-keeps-the-package-attribute  a namespace package (no file, only a path) is not one of the modules whose names are restored, so the attribute for a replaced submodule stays;
  2QT3-harness-a-case-keeps-the-modules-it-imported  a module first imported by the case stays in `sys.modules`;
  2QT3-harness-a-case-keeps-the-names-it-rebound  the names a reload or an assignment rebound in a repository module are not reset.
"""
from __future__ import annotations

from .base import RST, Mutation

HAR = "tools/gen2_mutations.py"
ORDER, VERDICT = "test_router_status_order.StatusOrderTest.", "test_mutation_verdict.RestoredModulesTest."
FACTS, HOLDS = 'sorted(self._core._store.select("capability_facts"), key=lambda f: f["capability"])', 'sorted(self._core._store.select("holds"), key=lambda h: h["created_at"])'
FACTS_KILLER, HOLDS_KILLER = ORDER + "test_status_lists_the_current_capability_facts_by_capability_name", ORDER + "test_status_lists_the_open_global_holds_in_the_order_they_were_opened"
PUT_BACK = '''        for name, mod in self.saved.items():
            if sys.modules.get(name) is not mod:
                sys.modules[name] = mod
'''
DROP_NEW = '''        for name in [name for name, mod in sys.modules.items() if name not in self.saved and self.ours(mod)]:
            del sys.modules[name]
'''
RESET = '''        gone = object()
        for name, held in self.held.items():
            live = self.saved[name].__dict__
            for key in [key for key in live if key not in held]:
                del live[key]
            for key, value in held.items():
                if live.get(key, gone) is not value:
                    live[key] = value
'''

MUTATIONS: list[Mutation] = [
    Mutation("2QT3-status-capability-facts-reversed", "2q-t3", "status lists the current capability facts by capability name, descending", (FACTS_KILLER,), target=RST,
             old=FACTS, new=FACTS[:-1] + ", reverse=True)"),
    Mutation("2QT3-status-capability-facts-by-onset", "2q-t3", "status lists the capability facts by when each began, not by capability name", (FACTS_KILLER,), target=RST,
             old=FACTS, new=FACTS.replace('f["capability"]', 'f["since"]')),
    Mutation("2QT3-status-global-holds-reversed", "2q-t3", "status lists the open holds of no topic newest first", (HOLDS_KILLER,), target=RST,
             old=HOLDS, new=HOLDS[:-1] + ", reverse=True)"),
    Mutation("2QT3-status-global-holds-by-subject", "2q-t3", "status lists the open holds of no topic by their subject, not by when each was opened", (HOLDS_KILLER,), target=RST,
             old=HOLDS, new=HOLDS.replace('h["created_at"]', 'h["subject_ref"]')),
    Mutation("2QT3-harness-a-case-keeps-the-replaced-module", "2q-t3", "a serial case leaves the module it replaced in sys.modules",
             (VERDICT + "test_a_module_put_in_place_of_another_in_sys_modules_is_the_original_again",), target=HAR, old=PUT_BACK, new=""),
    Mutation("2QT3-harness-a-case-keeps-the-package-attribute", "2q-t3", "a namespace package's attribute for a replaced submodule is not restored",
             (VERDICT + "test_a_namespace_packages_attribute_for_a_replaced_submodule_is_the_original_again",), target=HAR, old=' or next(iter(getattr(mod, "__path__", ())), None)', new=""),
    Mutation("2QT3-harness-a-case-keeps-the-modules-it-imported", "2q-t3", "a module first imported by a serial case stays in sys.modules",
             (VERDICT + "test_a_module_first_imported_by_the_case_is_dropped",), target=HAR, old=DROP_NEW, new=""),
    Mutation("2QT3-harness-a-case-keeps-the-names-it-rebound", "2q-t3", "the names a case rebound in a repository module are not reset",
             (VERDICT + "test_a_module_reloaded_over_a_mutant_holds_what_it_held",), target=HAR, old=RESET, new=""),
]
