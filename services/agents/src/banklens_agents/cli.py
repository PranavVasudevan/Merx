"""BankLens agent CLI — the "ask it anything" analyst copilot.

    python -m banklens_agents.cli "which banks look most exposed to a deposit run?"
    python -m banklens_agents.cli --persona macro_stress "stress Dime under a 60% run" --cert-hint 6976

Requires ANTHROPIC_API_KEY (env var or .env at the repo root) — see anthropic_client.py.
Every run is saved to data/agent_runs/<timestamp>.json for audit, mirroring the MCP
server's own per-tool-call audit log.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agent import run_agent, to_json
from .anthropic_client import MissingApiKey
from .personas import PERSONAS
from .supervisor import route

REPO = Path(__file__).resolve().parents[4]
RUNS_DIR = REPO / "data" / "agent_runs"


def _on_event(kind: str, payload) -> None:
    if kind == "tool_call":
        print(f"    -> calling {payload['name']}({payload['input']})")
    elif kind == "tool_result":
        print(f"       {payload['preview'][:160]}")
    elif kind == "final":
        pass  # printed by caller


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens agent — ask it anything")
    p.add_argument("question", nargs="+", help="your question, in plain English")
    p.add_argument("--persona", choices=list(PERSONAS), default=None,
                   help="skip the supervisor and force a specialist")
    p.add_argument("--model", default="sonnet", choices=["opus", "sonnet", "haiku"])
    args = p.parse_args()
    question = " ".join(args.question)

    try:
        if args.persona:
            persona_key, reason = args.persona, "user-forced"
        else:
            print("[supervisor] routing question to a specialist...")
            persona_key, reason = route(question)
        persona = PERSONAS[persona_key]
        print(f"[supervisor] -> {persona.label}  ({reason})\n")

        print(f"[{persona.label}] working...")
        result = run_agent(persona, question, model=args.model, on_event=_on_event)

        print(f"\n{'=' * 70}")
        print(result.answer)
        print("=" * 70)

        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        out = RUNS_DIR / f"{ts}.json"
        out.write_text(json.dumps(to_json(result), indent=2), encoding="utf-8")
        print(f"\n(transcript saved to {out.relative_to(REPO)})")

    except MissingApiKey as e:
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
