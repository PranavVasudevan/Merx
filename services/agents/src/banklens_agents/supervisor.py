"""Supervisor — routes a free-text question to the specialist persona best equipped
to answer it. Uses a single cheap/fast call with a FORCED tool call (tool_choice)
so routing is a structured decision, not a parsed sentence — reliable and auditable,
and identical across providers since every client translates the same forced-tool
request into its own wire format (see providers.py).
"""

from __future__ import annotations

from . import providers
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


def route(question: str, *, model: str | None = None, provider: str | None = None) -> tuple[str, str]:
    """Return (persona_key, reason). Falls back to 'generalist' on any ambiguity."""
    provider_name, client = providers.get_client(provider)
    model_id = providers.resolve_model(provider_name, model or _fast_model_hint(provider_name))

    resp = client.messages_create(
        model=model_id, system=_SYSTEM,
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


def _fast_model_hint(provider_name: str) -> str | None:
    """Prefer the cheapest/fastest tier for routing where the provider has one
    (Anthropic: haiku). Providers without a cheap tier just use their default."""
    return "haiku" if provider_name == "anthropic" else None
