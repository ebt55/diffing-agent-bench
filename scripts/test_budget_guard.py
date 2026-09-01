"""The dollar budget guard must not be silently disabled by an unpriced model.

An unpriced brain turn carries cost_usd = 0.0 as a PLACEHOLDER, because the agent
loop needs a float to accumulate. If that placeholder is summed, `spent` stays at
zero while real tokens burn, so `spent > max_cost_usd` never becomes true and the
budget stop is inoperative -- not merely imprecise. This test pins the fail-closed
behaviour: the run stops with `unpriced_no_budget_guard` on the first unpriced turn.

Run: python scripts/test_budget_guard.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diffing_agent import agent as agent_mod           # noqa: E402
from diffing_agent import brain as brain_mod           # noqa: E402
from diffing_agent.agent import run                    # noqa: E402
from diffing_agent.config import RunConfig             # noqa: E402


class UnpricedBrain(brain_mod.MockBrain):
    """Behaves exactly like MockBrain but reports that its price is unknown."""

    def call(self, *a, **kw):
        reply = super().call(*a, **kw)
        reply.cost_exact = False
        reply.cost_usd = 0.0     # the placeholder the real unpriced path produces
        return reply


def main() -> int:
    cfg = RunConfig.from_file("configs/mock_unittest_fixed_labels.json")
    failures = []

    # Offline and free: the mock brain exercises the real loop, recorder and cost
    # accounting without an API call.
    cfg.brain.provider = "mock"

    with tempfile.TemporaryDirectory() as td:
        cfg.results_root = td

        # 1. Priced mock still completes: the guard must not fire on normal runs.
        cfg.run_id = "guard_priced"
        ok = run(cfg, verbose=False)
        if ok["status"] == "unpriced_no_budget_guard":
            failures.append("priced mock run was wrongly stopped by the guard")
        print(f"priced mock      -> status={ok['status']}")

        # 2. Unpriced brain must stop immediately, not run to completion.
        #    agent.py does `from .brain import build_brain`, so the name to patch is
        #    the one bound in agent's namespace, not brain's.
        orig = agent_mod.build_brain
        agent_mod.build_brain = lambda c: UnpricedBrain(c)
        try:
            cfg.run_id = "guard_unpriced"
            bad = run(cfg, verbose=False)
        finally:
            agent_mod.build_brain = orig
        print(f"unpriced brain   -> status={bad['status']}")

        if bad["status"] != "unpriced_no_budget_guard":
            failures.append(
                f"unpriced run status was {bad['status']!r}, expected "
                "'unpriced_no_budget_guard' - the budget guard is silently dead")
        if bad["cost"]["brain_usd"] is not None:
            failures.append(
                f"unpriced run reported brain_usd={bad['cost']['brain_usd']!r}; "
                "an unmeasurable run must report null, never a number")
        if bad["cost"].get("cost_exact") is not False:
            failures.append("unpriced run did not set cost_exact=False")

        ev = [e for e in (Path(td) / "guard_unpriced" / "transcript.jsonl")
              .read_text(encoding="utf-8").splitlines()
              if "budget_guard_inoperative" in e]
        if not ev:
            failures.append("no budget_guard_inoperative event was recorded")

    print()
    for f in failures:
        print("FAIL:", f)
    print("budget guard:", "PASS" if not failures else f"FAIL ({len(failures)})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
