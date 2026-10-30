"""Unit tests for the crew's adjudication logic, using a fake transport.

Test doubles live here, in tests/, only — never in the shipped path.
The behaviors pinned down:
  * the planner adjudicates ONLY when cross-verification disagrees;
  * on agreement the two parts are assembled untouched (no extra model call);
  * worker B's receipt honestly records grounded true/false;
  * an unparseable review escalates instead of silently passing.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proofcrew import crew as crew_mod
from proofcrew.config import Config

PLAN_JSON = json.dumps(
    {
        "plan": "do both halves",
        "worker_a_task": "PART-A: write the overview",
        "worker_b_task": "PART-B: write the current-facts section",
        "search_query": "current facts query",
    }
)
SCREEN_JSON = json.dumps(
    {
        "worker_a": {"pass": True, "notes": "fine"},
        "worker_b": {"pass": True, "notes": "fine"},
        "flags": [],
    }
)
AGREE = json.dumps({"verdict": "agree", "issues": []})


class FakeTransport:
    """Records every call; responds from a script keyed by system prompt."""

    def __init__(self, verify_a=AGREE, verify_b=AGREE, adjudicated_text="ADJUDICATED FINAL"):
        self.calls: list[tuple[str, str, str]] = []
        self._verify_by_target_output = {
            "Output B": verify_a,  # worker A verifies B's output
            "Output A": verify_b,  # worker B verifies A's output
        }
        self._adjudicated_text = adjudicated_text

    def complete(self, model: str, system: str, user: str) -> str:
        self.calls.append((model, system, user))
        if system == crew_mod.PLAN_SYSTEM:
            return PLAN_JSON
        if system == crew_mod.WORKER_SYSTEM:
            return "Output A" if "PART-A" in user else "Output B"
        if system == crew_mod.SCREEN_SYSTEM:
            return SCREEN_JSON
        if system == crew_mod.VERIFY_SYSTEM:
            for marker, response in self._verify_by_target_output.items():
                if marker in user:
                    return response
            raise AssertionError("verify prompt contained no known output")
        if system == crew_mod.ADJUDICATE_SYSTEM:
            return self._adjudicated_text
        raise AssertionError(f"unexpected system prompt: {system[:40]}")

    def count(self, system: str) -> int:
        return sum(1 for _, s, _ in self.calls if s == system)


class FakeTavily:
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        return [
            {
                "title": "Fact page",
                "url": "https://example.com/fact",
                "content": "A current fact.",
            }
        ]


def test_config() -> Config:
    return Config(api_key="test-key", tavily_api_key=None)


class TestAdjudicationGate(unittest.TestCase):
    def test_needs_adjudication_truth_table(self):
        self.assertFalse(crew_mod.needs_adjudication({"verdict": "agree"}, {"verdict": "agree"}))
        self.assertTrue(crew_mod.needs_adjudication({"verdict": "disagree"}, {"verdict": "agree"}))
        self.assertTrue(crew_mod.needs_adjudication({"verdict": "agree"}, {"verdict": "disagree"}))
        # Unparseable / missing reviews must escalate, never silently pass.
        self.assertTrue(crew_mod.needs_adjudication(None, {"verdict": "agree"}))
        self.assertTrue(crew_mod.needs_adjudication({}, {}))

    def test_agreement_assembles_without_adjudication(self):
        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertFalse(result.adjudicated)
        self.assertEqual(transport.count(crew_mod.ADJUDICATE_SYSTEM), 0)
        # Planner called exactly once (the plan) — not again for adjudication.
        planner_calls = [c for c in transport.calls if c[0] == test_config().planner_model]
        self.assertEqual(len(planner_calls), 1)
        self.assertIn("Output A", result.deliverable)
        self.assertIn("Output B", result.deliverable)
        kinds = [r["kind"] for r in result.chain.receipts]
        self.assertEqual(
            kinds,
            ["plan", "work", "work", "screen", "verify", "verify", "assembly", "final"],
        )

    def test_disagreement_triggers_adjudication(self):
        transport = FakeTransport(
            verify_b=json.dumps({"verdict": "disagree", "issues": ["A is wrong"]})
        )
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertTrue(result.adjudicated)
        self.assertEqual(transport.count(crew_mod.ADJUDICATE_SYSTEM), 1)
        self.assertEqual(result.deliverable, "ADJUDICATED FINAL")
        kinds = [r["kind"] for r in result.chain.receipts]
        self.assertIn("adjudication", kinds)
        self.assertNotIn("assembly", kinds)

    def test_unparseable_review_escalates(self):
        transport = FakeTransport(verify_a="I looked and it seems fine, no JSON here")
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertTrue(result.adjudicated)


class TestGroundingHonesty(unittest.TestCase):
    def test_no_tavily_key_means_grounded_false_in_receipt(self):
        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config(), tavily_client=None)
        self.assertFalse(result.grounded_worker_b)
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertIs(worker_b["payload"]["grounded"], False)

    def test_tavily_grounding_reaches_worker_b_and_receipt(self):
        transport = FakeTransport()
        result = crew_mod.run_crew(
            "the task", transport, test_config(), tavily_client=FakeTavily()
        )
        self.assertTrue(result.grounded_worker_b)
        worker_b = next(
            r for r in result.chain.receipts if r["actor"] == "worker_b" and r["kind"] == "work"
        )
        self.assertIs(worker_b["payload"]["grounded"], True)
        b_prompts = [
            user
            for _, system, user in transport.calls
            if system == crew_mod.WORKER_SYSTEM and "PART-B" in user
        ]
        self.assertTrue(any("https://example.com/fact" in p for p in b_prompts))

    def test_receipt_chain_from_a_run_verifies(self):
        from proofcrew.receipts import verify_receipts

        transport = FakeTransport()
        result = crew_mod.run_crew("the task", transport, test_config())
        self.assertEqual(verify_receipts(result.chain.receipts), [])


if __name__ == "__main__":
    unittest.main()
