"""Supervisor routing eval — checks the router picks the expected specialist for a
small, hand-labeled question set. Works with the default (ollama, $0) or any
configured provider; NOT part of the hermetic test suite (it makes real model calls,
local or remote), run manually:

    $env:PYTHONPATH = "services/agents/src;services/mcp-server/src;pipelines/transforms/src"
    python services/agents/tests/run_eval.py
    python services/agents/tests/run_eval.py --provider gemini
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_agents import providers  # noqa: E402
from banklens_agents.supervisor import route  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens supervisor routing eval")
    p.add_argument("--provider", choices=list(providers.PROVIDERS), default=None)
    args = p.parse_args()
    provider_name, _ = providers.get_client(args.provider)

    cases = json.loads((Path(__file__).parent / "eval_questions.json").read_text())
    correct = 0
    print(f"Provider: {provider_name}\n")
    try:
        for c in cases:
            persona, reason = route(c["question"], provider=args.provider)
            ok = persona == c["expected_persona"]
            correct += ok
            mark = "PASS" if ok else "FAIL"
            print(f"{mark}  expected={c['expected_persona']:<15} got={persona:<15} "
                  f"({reason})\n      Q: {c['question']}")
    except Exception as e:  # MissingApiKey (anthropic/gemini) or OllamaError
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)
    print(f"\n{correct}/{len(cases)} routed correctly")


if __name__ == "__main__":
    main()
