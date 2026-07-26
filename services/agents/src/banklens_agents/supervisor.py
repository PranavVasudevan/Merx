"""Supervisor — routes a free-text question to the specialist persona best equipped
to answer it. Uses a single cheap Haiku call with a FORCED tool call (tool_choice)
so routing is a structured decision, not a parsed sentence — reliable and auditable.
"""

from __future__ import annotations

from .anthropic_client import MODELS, messages_create
from .personas import PERSONAS

_ROUTE_TOOL = {
    "name": "route",
    "description": "Choose the specialist analyst best suited to answer the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "persona": {
                "type": "string",
                "enum": [p for p in PERSONAS if p != "generalist"],
                "description": (
                    "risk_analyst: concentration/run risk, X-Ray, deposit-flight score. "
                    "filings_analyst: what changed quarter-over-quarter and why. "
                    "ma_scout: acquisition/partnership fit, peer behavior. "
                    "macro_stress: capital stress-testing under shocks."
                ),
            },
            "reason": {"type": "string", "description": "one short phrase"},
        },
        "required": ["persona", "reason"],
    },
}

_SYSTEM = (
    "You are the routing supervisor for BankLens, a bank-intelligence platform. "
    "Given the user's question, call `route` exactly once to pick the best specialist."
)


def route(question: str, *, model: str = "haiku") -> tuple[str, str]:
    """Return (persona_key, reason). Falls back to 'generalist' on any ambiguity."""
    resp = messages_create(
        model=MODELS.get(model, model), system=_SYSTEM,
        messages=[{"role": "user", "content": question}],
        tools=[_ROUTE_TOOL], tool_choice={"type": "tool", "name": "route"},
    )
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "route":
            inp = block.get("input", {})
            persona = inp.get("persona")
            if persona in PERSONAS:
                return persona, inp.get("reason", "")
    return "generalist", "routing was inconclusive; using the generalist (all tools)"
