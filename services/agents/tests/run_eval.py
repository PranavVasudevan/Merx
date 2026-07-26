"""Supervisor routing eval — checks the router picks the expected specialist for a
small, hand-labeled question set. Requires a real ANTHROPIC_API_KEY (network call
per question); NOT part of the hermetic test suite, run manually:

    $env:PYTHONPATH = "services/agents/src;services/mcp-server/src;pipelines/transforms/src"
    python services/agents/tests/run_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_agents.anthropic_client import MissingApiKey  # noqa: E402
from banklens_agents.supervisor import route  # noqa: E402


def main() -> None:
    cases = json.loads((Path(__file__).parent / "eval_questions.json").read_text())
    correct = 0
    try:
        for c in cases:
            persona, reason = route(c["question"])
            ok = persona == c["expected_persona"]
            correct += ok
            mark = "PASS" if ok else "FAIL"
            print(f"{mark}  expected={c['expected_persona']:<15} got={persona:<15} "
                  f"({reason})\n      Q: {c['question']}")
    except MissingApiKey as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)
    print(f"\n{correct}/{len(cases)} routed correctly")


if __name__ == "__main__":
    main()
