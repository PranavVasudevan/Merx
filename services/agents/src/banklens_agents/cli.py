"""BankLens agent CLI — the "ask it anything" analyst copilot.

    python -m banklens_agents.cli "which banks look most exposed to a deposit run?"
    python -m banklens_agents.cli --persona macro_stress "stress Dime under a 60% run"
    python -m banklens_agents.cli --provider gemini "..."     # once GEMINI_API_KEY* is set
    python -m banklens_agents.cli --provider anthropic "..."  # costs money — off by default

Default provider is **ollama** (BANKLENS_LLM_PROVIDER env var overrides) — this
project has a hard $0 spending rule, and Ollama is the only backend that costs
nothing to actually run. See providers.py / services/agents/README.md.

Every run is saved to data/agent_runs/<timestamp>.json (the full transcript) AND
indexed in the real `agent_runs` Postgres table (see banklens_common.db) so it's
queryable without grepping flat files — same store the MCP server's own audit
log now uses. If Postgres is unreachable the JSON transcript still gets written
(that's the actual content); only the queryable index is skipped, with a warning.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from banklens_common import db as common_db

from . import providers
from .agent import run_agent, to_json
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
    p.add_argument("--provider", choices=list(providers.PROVIDERS), default=None,
                   help=f"LLM backend (default: {providers.DEFAULT_PROVIDER}, or $BANKLENS_LLM_PROVIDER)")
    p.add_argument("--model", default=None,
                   help="model name/alias for the chosen provider (default: provider's own default)")
    args = p.parse_args()
    question = " ".join(args.question)
    provider_name, _ = providers.get_client(args.provider)

    try:
        if args.persona:
            persona_key, reason = args.persona, "user-forced"
        else:
            print(f"[supervisor:{provider_name}] routing question to a specialist...")
            persona_key, reason = route(question, model=args.model, provider=args.provider)
        persona = PERSONAS[persona_key]
        print(f"[supervisor] -> {persona.label}  ({reason})\n")

        print(f"[{persona.label}:{provider_name}] working...")
        result = run_agent(persona, question, model=args.model, provider=args.provider,
                           on_event=_on_event)

        print(f"\n{'=' * 70}")
        print(result.answer)
        print("=" * 70)

        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%dT%H%M%S%f")
        out = RUNS_DIR / f"{ts}.json"
        out.write_text(json.dumps(to_json(result), indent=2), encoding="utf-8")
        print(f"\n(transcript saved to {out.relative_to(REPO)})")

        try:
            model_id = providers.resolve_model(provider_name, args.model)
            common_db.record_agent_run(
                persona=persona.key, provider=provider_name, model=model_id,
                question=question, answer=result.answer, ok=True,
                transcript_path=str(out.relative_to(REPO)), ts=now)
        except Exception as exc:
            print(f"[banklens_agents] Postgres agent-run index unavailable ({exc}); "
                  f"transcript is still saved to disk.", file=sys.stderr)

    except Exception as e:  # MissingApiKey (anthropic/gemini) or OllamaError
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
