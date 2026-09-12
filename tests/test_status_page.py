"""The per-minute STATUS page leads with actionable sections (2026-09-09
operator ruling): pending checkpoint proposals and checkpoint debt are shown,
history/telemetry enumerations render only with full=True."""
import unittest

from research_loops.dashboard import render_dashboard


def managed_state():
    items = [
        {"id": "alpha", "title": "Alpha Topic", "status": "running", "desired_state": "running",
         "claimed_by": "station-1", "attempts": 5, "lane": "research"},
        {"id": "beta", "title": "Beta Topic", "status": "paused", "desired_state": "paused",
         "attempts": 40, "lane": "research"},
        {"id": "gamma", "title": "Gamma Topic", "status": "completed", "desired_state": "running",
         "attempts": 60, "finished_at": "2026-09-01T00:00:00Z", "lane": "research"},
    ]
    work = {
        "topics": {
            "alpha": {"topic_id": "alpha", "research_iterations_completed": 12,
                      "next_research_ordinal": 13, "review_state": "eligible",
                      "active_episode_id": None},
            "beta": {"topic_id": "beta", "research_iterations_completed": 40,
                     "next_research_ordinal": 41, "review_state": "checkpoint_due",
                     "active_episode_id": "checkpoint-beta"},
        },
        "proposals": {
            "proposal-1": {"proposal_id": "proposal-1", "topic_id": "alpha", "kind": "addition",
                           "proposal_version": 1, "episode_id": "checkpoint-alpha",
                           "status": "pending"},
            "proposal-0": {"proposal_id": "proposal-0", "topic_id": "alpha", "kind": "amendment",
                           "proposal_version": 1, "episode_id": "checkpoint-old",
                           "status": "resolved"},
        },
        "assignments": {},
        "episodes": {},
    }
    configuration = {"active_count": 1, "checkpoints": {"enabled": True, "every_research_iterations": 25,
                                                        "on_deepening_entry": True, "agent_source": "station_1"},
                     "stations": [{"id": 1, "primary_profile": "terra", "secondary_profile": "luna",
                                   "interval_seconds": 0}]}
    return {"items": items, "paused": False, "stopping": False, "revision": 7,
            "managed_control": {"configuration": configuration, "work": work}}


class StatusPageTests(unittest.TestCase):
    def test_default_page_leads_with_pending_proposals(self):
        page = render_dashboard(managed_state(), [])
        self.assertIn("## Pending checkpoint proposals (awaiting your decision)", page)
        self.assertIn("proposal\\-1", page)
        self.assertNotIn("proposal\\-0", page)  # resolved proposals are history
        self.assertIn("checkpoint-decide", page)
        # Checkpoint debt is deliberately absent (operator request 2026-09-11):
        # a topic owing a routine, self-resolving review is not an operator
        # decision and reading it as a to-do was confusing.
        self.assertNotIn("Checkpoint debt", page)

    def test_default_page_elides_history_but_full_includes_it(self):
        state = managed_state()
        default = render_dashboard(state, [])
        self.assertNotIn("## Paused topics", default)
        self.assertIn("## Completed topics", default)
        self.assertNotIn("## Retained-ledger aggregate", default)
        self.assertNotIn("## Metric definitions and coverage", default)
        self.assertIn("History elided", default)
        self.assertIn("_Generated file.", default)
        full = render_dashboard(state, [], full=True)
        for section in ("## Paused topics", "## Completed topics",
                        "## Retained-ledger aggregate", "## Metric definitions and coverage"):
            self.assertIn(section, full)
        self.assertIn("_Generated file.", full)

    def test_malformed_work_maps_render_a_notice_instead_of_crashing(self):
        state = managed_state()
        state["managed_control"]["work"]["proposals"] = ["bad"]
        state["managed_control"]["work"]["topics"] = ["also bad"]
        page = render_dashboard(state, [])
        self.assertIn("Managed work data malformed/unavailable", page)
        notice = page.split("malformed/unavailable")[1][:80]
        self.assertIn("proposals", notice)
        self.assertIn("topics", notice)
        self.assertIn("## Pending checkpoint proposals", page)

    def test_malformed_episodes_and_work_degrade_with_notice(self):
        # Malformed episodes with a valid active topic previously crashed the
        # Last-checkpoint column (Astra R2-4); work=None crashed the header.
        state = managed_state()
        state["managed_control"]["work"]["episodes"] = ["bad"]
        page = render_dashboard(state, [])
        self.assertIn("Managed work data malformed/unavailable", page)
        self.assertIn("episodes", page.split("malformed/unavailable")[1][:60])
        self.assertIn("Alpha Topic", page)
        state = managed_state()
        state["managed_control"]["work"] = None
        page = render_dashboard(state, [])
        self.assertIn("## Active topics", page)
        # An explicitly null work map is malformed, not merely absent (R3-2).
        self.assertIn("Managed work data malformed/unavailable", page)
        self.assertIn("work", page.split("malformed/unavailable")[1][:40])
        state = managed_state()
        state["managed_control"]["work"] = "garbage"
        page = render_dashboard(state, [])
        self.assertIn("Managed work data malformed/unavailable", page)

    def test_malformed_rows_inside_valid_maps_are_skipped_with_notice(self):
        state = managed_state()
        state["managed_control"]["work"]["topics"]["alpha"] = "not a dict"
        state["managed_control"]["work"]["episodes"] = {"checkpoint-beta": "not a dict"}
        state["managed_control"]["work"]["proposals"]["proposal-1"] = ["bad row"]
        page = render_dashboard(state, [])
        self.assertIn("## Pending checkpoint proposals", page)
        self.assertIn("## Active topics", page)
        # A corrupt row must not vanish silently into an empty section (R3-2).
        self.assertIn("Managed work data malformed/unavailable", page)
        notice = page.split("malformed/unavailable")[1][:120]
        for label in ("topics rows", "episodes rows", "proposals rows"):
            self.assertIn(label, notice)

    def test_empty_pending_section_still_renders(self):
        state = managed_state()
        state["managed_control"]["work"]["proposals"] = {}
        page = render_dashboard(state, [])
        section = page.split("## Pending checkpoint proposals")[1].split("##")[0]
        self.assertIn("| — |", section)


if __name__ == "__main__":
    unittest.main()
