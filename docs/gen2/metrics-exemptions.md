# Architecture-metrics exemptions

The ratchet (`tools/gen2_metrics.py`, `make gen2-metrics`, run by `make gen2-check`; charter "Architecture metrics") fails on any regression against `docs/gen2/metrics-baseline.json`. **This file is the only way past a regression.** An entry is a reviewed, reasoned exception. It is not a way to record that the baseline moved: the baseline only moves through `make gen2-metrics-rebaseline`, which never loosens it (it keeps the old value wherever an entry here covers a regression).

An entry must be **complete**, **match one regression exactly**, and **still be needed**. The check fails on an entry that is incomplete, misspelled, a duplicate, or that no regression needs any more (remove it then: the condition under which it was to go has been met). A value above the entry's `limit` is not covered.

## Format

One `###` section per entry, headed `### EX-<id>` and any title, then `- key: value` lines (a long value continues on lines indented two spaces). Fenced blocks are skipped, so the example below is not an entry.

```
### EX-1 - Router._write_evidence grows by one branch
- metric: function_cyclomatic
- location: engine:gen2/router/service.py::Router._write_evidence
- limit: 56
- reason: why the regression is accepted rather than fixed
- accepted by: the review that accepted it (a report file name, or Gate D #n, with its date)
- removal: the condition under which this entry is deleted (a task, a repair, a phase)
```

| Field | Rule |
|---|---|
| `metric` | one of the names below |
| `location` | the regression's own location: `<service>:<where>`, or the service alone for a service-wide number; services are `engine`, `gateway`, and `repo` for an import between them |
| `limit` | required for a number (the highest value accepted: an integer for counts and complexity, a decimal such as `0.1500` for a propagation cost); not allowed for a named instance |
| `reason` | what is regressing and why it is accepted instead of fixed; not a placeholder |
| `accepted by` | the review that accepted it: a report file name (`.md`), a date, or `Gate D #n` |
| `removal` | a condition, not a word: what must happen for the entry to be deleted |

| Metric | Location | Limit |
|---|---|---|
| `propagation_file`, `propagation_component` | `engine` or `gateway` | a decimal |
| `cycle_file` | `<service>:<files of the cycle, sorted, comma-separated>` | none |
| `cycle_component` | `<service>:<components of the cycle, sorted, comma-separated>` | none |
| `self_calls` | `<service>:<calling file>-><defining file>` | an integer (call sites) |
| `smell_hub_like` | `<service>:<file>` | none |
| `smell_unstable_dependency` | `<service>:<importing file>-><imported file>` | none |
| `smell_god_component` | `<service>:<component>` | none |
| `function_cyclomatic`, `function_cognitive` | `<service>:<file>::<qualified name>` (`#2` for a second function of the same name in a file) | an integer |
| `cross_service_import` | `repo:<importing file>-><imported file>` | none |

## Entries

None. The baseline recorded at the task 2q-a pin is the present state of the engine and the gateway, so nothing is exempt: every metric and smell the code has today is in the baseline, and only something worse than the baseline needs an entry here.
