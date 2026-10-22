"""2d-5: disabled capability truth, with independent startup/status controls."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
ACT = "test_tier0_disabled.Tier0ActivationTest.test_"
STATUS = "test_tier0_disabled.Tier0StatusTest.test_"
REG = "gen2/router/registries.py"


def add(name, killers, old, new, *, target=REG, control=ACT + "config_activation_control"):
    mid = "2D5-" + name
    MUTATIONS.append(Mutation(mid, "2d-5", name, tuple(killers), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [control], "why":
        "Separate accepted startup/status path executes the changed code and checks unrelated config or capability visibility."}


FRESH = 'self._fact("tier-0", "unknown", "tier-0 disabled", now)'
RESTORE = 'self._fact("tier-0", "unknown", "tier-0 disabled", self._core._now())'
add("fresh-missing", (ACT + "fresh_activation_records_dated_disabled_fact",), FRESH, 'None')
add("retained-missing", (ACT + "retained_store_without_fact_gets_one_at_activation",), RESTORE, 'None')
add("performed", (STATUS + "operator_status_never_reports_tier0_performed_or_passed",),
    FRESH, FRESH.replace('"tier-0 disabled"', '"tier-0 performed: passed"'))
add("retained-performed", (ACT + "retained_store_without_fact_gets_one_at_activation",),
    RESTORE, RESTORE.replace('"tier-0 disabled"', '"tier-0 performed: passed"'))
add("healthy", (ACT + "fresh_activation_records_dated_disabled_fact",),
    FRESH, FRESH.replace('"unknown"', '"healthy"'))
add("last-success", (STATUS + "operator_status_never_reports_tier0_performed_or_passed",),
    '"affected_lanes": [], "recorded_at": now})',
    '"affected_lanes": [], "recorded_at": now, "last_success_at": now})')
add("redated", (ACT + "restart_and_status_preserve_original_fact_without_performed_records",),
    'if (current["state"] if current is not None else "healthy") == state:',
    'if capability != "tier-0" and (current["state"] if current is not None else "healthy") == state:')
add("status-omission", (STATUS + "operator_status_never_reports_tier0_performed_or_passed",),
    '"capability_facts": facts["capability_facts"]',
    '"capability_facts": [f for f in facts["capability_facts"] if f["capability"] != "tier-0"]',
    target="gen2/operator/status.py", control=STATUS + "other_capability_facts_remain_visible_control")
