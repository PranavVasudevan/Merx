"""Bridge REST routing — exercises `_route_request()` (the single routing/auth/
error-mapping function both server transports call, see bridge_server.py's module
docstring) directly, no socket involved. `banklens_mcp.tools`/`data` are
monkeypatched per test so no landed Bronze or Postgres is required; `auth` is
monkeypatched too where a route isn't open, so this never needs a real OIDC token.

If bridge_server.py (or one of its real dependencies — prometheus_client,
banklens_mcp, banklens_agents, banklens_common) can't be imported in this
environment, every test SKIPs rather than fails.

Run: ``python services/api-gateway/tests/test_bridge.py``  (no pytest needed)
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for rel in ("services/api-gateway/src", "services/mcp-server/src",
            "pipelines/transforms/src", "services/agents/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class SkipTest(Exception):
    """A real dependency of bridge_server.py isn't importable here — a SKIP,
    not a failure (mirrors services/mcp-server/tests/test_mcp.py's convention)."""


try:
    import auth
    import bridge_server
    from banklens_agents.agent import AgentResult
    _IMPORT_ERROR: Exception | None = None
except Exception as e:  # pragma: no cover - environment-dependent
    _IMPORT_ERROR = e


def require_bridge_importable():
    if _IMPORT_ERROR is not None:
        raise SkipTest(f"bridge_server.py not importable here: {_IMPORT_ERROR}")


class _AuthDisabled:
    """Context manager: bypass the real OIDC/OPA path for routes that aren't in
    auth.OPEN_ROUTES, exactly the way BANKLENS_AUTH_ENABLED=false does for local
    dev (see auth.py) -- these tests care about ROUTING, not authentication."""

    def __enter__(self):
        self._prev = auth.AUTH_ENABLED
        auth.AUTH_ENABLED = False
        return self

    def __exit__(self, *exc):
        auth.AUTH_ENABLED = self._prev


# ---- health / unmatched routes (no stubbing needed) ------------------------

def test_health_route_is_open_and_needs_no_auth():
    require_bridge_importable()
    status, body = bridge_server._route_request("GET", "/api/health", {}, {}, None)
    assert status == 200
    assert body == {"status": "ok"}


def test_openapi_json_route_is_open_and_returns_a_real_spec_covering_itself():
    """F19 — served through the normal JSON dispatch, open (no auth), and the
    generated document must include the bridge's actual current route set,
    not a stale/hand-maintained list."""
    require_bridge_importable()
    status, body = bridge_server._route_request("GET", "/api/openapi.json", {}, {}, None)
    assert status == 200
    assert body["openapi"] == "3.1.0"
    assert "/api/health" in body["paths"]
    assert "/api/openapi.json" in body["paths"]  # doesn't omit itself
    assert "/api/assistant/ask" in body["paths"]  # F16's SSE route, not in POST_ROUTES


def test_unmatched_route_returns_404():
    require_bridge_importable()
    status, body = bridge_server._route_request("GET", "/api/does-not-exist", {}, {}, None)
    assert status == 404
    assert "error" in body


def test_wrong_method_on_a_real_path_is_unmatched_not_500():
    """DELETE isn't declared for /api/health -- must fall through to the same
    404 path as a nonexistent URL, not raise."""
    require_bridge_importable()
    status, _ = bridge_server._route_request("DELETE", "/api/health", {}, {}, None)
    assert status == 404


# ---- successful GET with a stubbed tools layer -----------------------------

def test_successful_get_route_returns_the_stubbed_tools_payload_verbatim():
    require_bridge_importable()
    canned = {"cert": 6976, "name": "Testbank", "quarter": "2026Q1"}
    original = bridge_server.tools.get_bank_profile
    bridge_server.tools.get_bank_profile = lambda cert, **kwargs: canned
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks/profile", {"cert": "6976"}, {}, None)
    finally:
        bridge_server.tools.get_bank_profile = original
    assert status == 200
    assert body == canned


def test_list_banks_route_passes_query_params_through_to_the_tool():
    require_bridge_importable()
    captured = {}

    def fake_list_banks(**kwargs):
        captured.update(kwargs)
        return {"banks": [], "count": 0}

    original = bridge_server.tools.list_banks
    bridge_server.tools.list_banks = fake_list_banks
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks", {"query": "test", "state": "NY", "limit": "5"}, {}, None)
    finally:
        bridge_server.tools.list_banks = original
    assert status == 200
    assert body == {"banks": [], "count": 0}
    assert captured["query"] == "test"
    assert captured["state"] == "NY"
    assert captured["limit"] == 5  # coerced from the query-string "5" to an int


# ---- missing required query param -> 400, not a 500 or a crash ------------

def test_missing_required_cert_param_maps_to_400_not_a_crash():
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "GET", "/api/banks/profile", {}, {}, None)   # no "cert" in query
    assert status == 400
    assert "cert" in body["error"]


def test_missing_required_body_field_on_a_post_route_maps_to_400():
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "DELETE", "/api/watchlist", {}, {}, None)   # no "cert" in query
    assert status == 400
    assert "error" in body


# ---- a genuine tool-layer exception still maps to 400 (current behaviour,
#      not a 500 -- see F18, which will change this to 500 with a request ID) --

# ---- F18: real 4xx vs 5xx status codes -------------------------------------

def test_a_genuine_server_fault_maps_to_500_not_400():
    """RuntimeError isn't a validation guard anyone wrote on purpose — it's a
    real bug/data-layer fault, and F18's whole point is that this must fire
    5xx-based alerting instead of being invisible in a bucket of routine 400s."""
    require_bridge_importable()
    original = bridge_server.tools.get_bank_profile

    def boom(cert, **kwargs):
        raise RuntimeError("simulated data-layer failure")

    bridge_server.tools.get_bank_profile = boom
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks/profile", {"cert": "6976"}, {}, None)
    finally:
        bridge_server.tools.get_bank_profile = original
    assert status == 500
    assert body["error"] == "internal server error"
    assert "simulated data-layer failure" not in body["error"]  # no internal detail leaked
    assert body["request_id"]


def test_a_deliberate_validation_failure_still_maps_to_400():
    """ValueError is what every real handler raises on purpose (unknown
    persona, cert not in the population, etc.) — must stay 400, and the real
    message stays visible since it's the app's own validation text, not
    something leaked from a lower layer."""
    require_bridge_importable()
    original = bridge_server.tools.get_bank_profile

    def bad_request(cert, **kwargs):
        raise ValueError(f"CERT {cert} not in the population slice.")

    bridge_server.tools.get_bank_profile = bad_request
    try:
        with _AuthDisabled():
            status, body = bridge_server._route_request(
                "GET", "/api/banks/profile", {"cert": "999999"}, {}, None)
    finally:
        bridge_server.tools.get_bank_profile = original
    assert status == 400
    assert "not in the population slice" in body["error"]


def test_missing_required_param_still_maps_to_400():
    """KeyError (a genuinely missing query param) is the other deliberate
    validation case F18 keeps at 400 — unchanged from before this phase."""
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "GET", "/api/banks/profile", {}, {}, None)  # no "cert" in query
    assert status == 400
    assert "cert" in body["error"]


# ---- auth still gates non-open routes when enabled -------------------------

def test_auth_enabled_and_no_token_is_rejected_not_routed_through():
    require_bridge_importable()
    prev = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        status, body = bridge_server._route_request(
            "GET", "/api/banks/profile", {"cert": "6976"}, {}, None)  # no Authorization header
    finally:
        auth.AUTH_ENABLED = prev
    assert status == 401
    assert "error" in body


# ---- F10: compression + caching ---------------------------------------

def test_prepare_json_body_cacheable_gets_etag_and_cache_control():
    require_bridge_importable()
    _status, body, headers = bridge_server._prepare_json_body(
        {"banks": [1, 2, 3]}, cacheable=True, accept_encoding=None, if_none_match=None)
    assert body  # a real body was sent, not empty
    assert headers["ETag"].startswith('"') and headers["ETag"].endswith('"')
    assert "max-age=" in headers["Cache-Control"]
    assert headers["Vary"] == "Accept-Encoding"


def test_prepare_json_body_matching_if_none_match_returns_304_with_empty_body():
    require_bridge_importable()
    payload = {"banks": [1, 2, 3]}
    _status, _body, headers = bridge_server._prepare_json_body(
        payload, cacheable=True, accept_encoding=None, if_none_match=None)
    etag = headers["ETag"]

    status_override, body, headers2 = bridge_server._prepare_json_body(
        payload, cacheable=True, accept_encoding=None, if_none_match=etag)
    assert status_override == 304
    assert body == b""
    assert headers2["ETag"] == etag


def test_prepare_json_body_stale_if_none_match_still_returns_the_real_body():
    require_bridge_importable()
    status_override, body, _headers = bridge_server._prepare_json_body(
        {"banks": [1, 2, 3]}, cacheable=True, accept_encoding=None, if_none_match='"stale-etag"')
    assert status_override is None
    assert body  # the real (uncompressed here) body, not empty


def test_prepare_json_body_non_cacheable_has_no_etag_or_cache_control():
    require_bridge_importable()
    _status, _body, headers = bridge_server._prepare_json_body(
        {"items": []}, cacheable=False, accept_encoding=None, if_none_match=None)
    assert "ETag" not in headers
    assert "Cache-Control" not in headers


def test_prepare_json_body_gzip_compresses_a_large_body_when_client_accepts_it():
    require_bridge_importable()
    big_payload = {"banks": [{"cert": i, "name": f"Bank {i}" * 5} for i in range(200)]}
    _status, body, headers = bridge_server._prepare_json_body(
        big_payload, cacheable=False, accept_encoding="gzip, deflate", if_none_match=None)
    assert headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(body) == json.dumps(big_payload, default=str).encode("utf-8")


def test_prepare_json_body_skips_gzip_without_accept_encoding():
    require_bridge_importable()
    big_payload = {"banks": [{"cert": i, "name": f"Bank {i}" * 5} for i in range(200)]}
    _status, _body, headers = bridge_server._prepare_json_body(
        big_payload, cacheable=False, accept_encoding=None, if_none_match=None)
    assert "Content-Encoding" not in headers


def test_prepare_json_body_skips_gzip_for_a_tiny_body_even_if_accepted():
    require_bridge_importable()
    _status, _body, headers = bridge_server._prepare_json_body(
        {"status": "ok"}, cacheable=False, accept_encoding="gzip", if_none_match=None)
    assert "Content-Encoding" not in headers


def test_cors_headers_expose_etag_to_javascript():
    """Without Access-Control-Expose-Headers, the browser hides the ETag
    response header from api.ts's JS entirely -- the conditional-GET path
    would silently never engage."""
    require_bridge_importable()
    headers = bridge_server._cors_headers("http://localhost:5173")
    assert "ETag" in headers["Access-Control-Expose-Headers"]


def test_non_cacheable_paths_include_the_per_user_and_dynamic_routes():
    require_bridge_importable()
    for route in ("/api/watchlist", "/api/activity/audit-log", "/api/health"):
        assert route in bridge_server._NON_CACHEABLE_PATHS


# ---- F10: wsgi_app end to end (mocked start_response, no real socket) -----

class _CapturedResponse:
    def __init__(self):
        self.status: str | None = None
        self.headers: list[tuple[str, str]] = []

    def __call__(self, status, headers, exc_info=None):
        self.status = status
        self.headers = headers

    def header(self, name: str) -> str | None:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return None


def _wsgi_environ(method: str, path: str, *, query: str = "", extra: dict | None = None) -> dict:
    env = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
        "REMOTE_ADDR": "127.0.0.1",
    }
    env.update(extra or {})
    return env


def test_wsgi_app_get_response_carries_etag_and_cache_control_for_a_cacheable_route():
    require_bridge_importable()
    original = bridge_server.tools.get_bank_profile
    bridge_server.tools.get_bank_profile = lambda cert, **kwargs: {"cert": cert, "name": "Testbank"}
    prev_auth = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = False
    try:
        cap = _CapturedResponse()
        list(bridge_server.wsgi_app(_wsgi_environ("GET", "/api/banks/profile", query="cert=6976"), cap))
        assert cap.status == "200 OK"
        assert cap.header("ETag")
        assert "max-age=" in (cap.header("Cache-Control") or "")
    finally:
        bridge_server.tools.get_bank_profile = original
        auth.AUTH_ENABLED = prev_auth


def test_wsgi_app_returns_304_when_the_client_sends_a_matching_etag():
    require_bridge_importable()
    original = bridge_server.tools.get_bank_profile
    bridge_server.tools.get_bank_profile = lambda cert, **kwargs: {"cert": cert, "name": "Testbank"}
    prev_auth = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = False
    try:
        first = _CapturedResponse()
        body1 = list(bridge_server.wsgi_app(_wsgi_environ("GET", "/api/banks/profile", query="cert=6976"), first))
        etag = first.header("ETag")
        assert etag and body1 and body1[0]  # sanity: a real first response with a real body

        second = _CapturedResponse()
        body2 = list(bridge_server.wsgi_app(
            _wsgi_environ("GET", "/api/banks/profile", query="cert=6976",
                          extra={"HTTP_IF_NONE_MATCH": etag}), second))
        assert second.status == "304 Not Modified"
        assert body2 == [b""]
    finally:
        bridge_server.tools.get_bank_profile = original
        auth.AUTH_ENABLED = prev_auth


def test_wsgi_app_never_caches_the_watchlist_route():
    require_bridge_importable()
    original_fetch = bridge_server.common_db.fetch_watchlist
    original_auth = auth.authenticate
    original_authorize = auth.authorize
    bridge_server.common_db.fetch_watchlist = lambda sub: []
    auth.authenticate = lambda header: {"sub": "u1"}
    auth.authorize = lambda *a, **k: None
    prev_auth_enabled = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        cap = _CapturedResponse()
        list(bridge_server.wsgi_app(
            _wsgi_environ("GET", "/api/watchlist", extra={"HTTP_AUTHORIZATION": "Bearer fake"}), cap))
        assert cap.status == "200 OK"  # sanity: the route itself actually succeeded
        assert cap.header("ETag") is None
        assert cap.header("Cache-Control") is None
    finally:
        bridge_server.common_db.fetch_watchlist = original_fetch
        auth.authenticate = original_auth
        auth.authorize = original_authorize
        auth.AUTH_ENABLED = prev_auth_enabled


# ---- F17: structured logging + request IDs ---------------------------------

def test_route_request_embeds_the_given_request_id_in_an_error_body():
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "GET", "/api/banks/profile", {}, {}, None, "test-req-1")  # no "cert" -> 400
    assert status == 400
    assert body["request_id"] == "test-req-1"


def test_route_request_embeds_the_given_request_id_in_a_404_body():
    require_bridge_importable()
    status, body = bridge_server._route_request(
        "GET", "/api/does-not-exist", {}, {}, None, "test-req-2")
    assert status == 404
    assert body["request_id"] == "test-req-2"


def test_route_request_does_not_add_request_id_to_a_successful_body():
    """Only error responses get the field — a successful GET's shape must
    stay exactly what the underlying tool returned, unpolluted."""
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request(
            "GET", "/api/health", {}, {}, None, "test-req-3")
    assert status == 200
    assert "request_id" not in body


def test_route_request_auto_generates_a_request_id_when_omitted():
    require_bridge_importable()
    with _AuthDisabled():
        status, body = bridge_server._route_request("GET", "/api/banks/profile", {}, {}, None)
    assert status == 400
    assert body["request_id"]  # a real, non-empty value, not a crash


def test_wsgi_app_echoes_the_request_id_as_a_response_header():
    require_bridge_importable()
    original = bridge_server.tools.get_bank_profile
    bridge_server.tools.get_bank_profile = lambda cert, **kwargs: {"cert": cert}
    prev_auth = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = False
    try:
        cap = _CapturedResponse()
        list(bridge_server.wsgi_app(_wsgi_environ("GET", "/api/banks/profile", query="cert=1"), cap))
        assert cap.header("X-Request-ID")
    finally:
        bridge_server.tools.get_bank_profile = original
        auth.AUTH_ENABLED = prev_auth


def test_log_request_prints_one_parseable_json_line_with_the_expected_fields():
    require_bridge_importable()
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bridge_server._log_request(
            request_id="abc123", method="GET", route="/api/health", status=200,
            latency_s=0.0123, subject="user-1", error_class=None)
    line = buf.getvalue().strip()
    assert line.count("\n") == 0  # exactly one line — the whole point for log aggregation
    parsed = json.loads(line)
    assert parsed["request_id"] == "abc123"
    assert parsed["route"] == "/api/health"
    assert parsed["status"] == 200
    assert parsed["latency_ms"] == 12.3
    assert parsed["subject"] == "user-1"
    assert parsed["error_class"] is None


# ---- F16: assistant SSE streaming ------------------------------------------

def _collect_sse(chunks) -> list[tuple[str, object]]:
    """Parses `event: X\\ndata: Y\\n\\n` wire chunks (bytes) back into
    (event, data) pairs, mirroring what a real SSE client does."""
    out = []
    for chunk in chunks:
        text = chunk.decode("utf-8").strip("\n")
        lines = text.split("\n")
        event = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        out.append((event, json.loads(data)))
    return out


def test_assistant_ask_sse_rejects_unknown_persona_without_calling_run_agent():
    require_bridge_importable()
    called = []
    original = bridge_server.run_agent
    bridge_server.run_agent = lambda *a, **k: called.append(1) or None
    try:
        events = _collect_sse(bridge_server._assistant_ask_sse(
            {"persona": "not_a_real_persona", "question": "hi"}, {}))
    finally:
        bridge_server.run_agent = original
    assert not called
    assert len(events) == 1
    assert events[0][0] == "error"
    assert "unknown persona" in events[0][1]["error"]


def test_assistant_ask_sse_rejects_empty_question():
    require_bridge_importable()
    events = _collect_sse(bridge_server._assistant_ask_sse(
        {"persona": "risk_analyst", "question": "   "}, {}))
    assert len(events) == 1
    assert events[0][0] == "error"
    assert "non-empty" in events[0][1]["error"]


def test_assistant_ask_sse_streams_tool_events_then_a_result_event():
    require_bridge_importable()

    def fake_run_agent(persona, question, *, roles=None, on_event=None, cancel_event=None, **kw):
        on_event("tool_call", {"name": "get_bank_xray", "input": {"cert": 1}})
        on_event("tool_result", {"name": "get_bank_xray", "preview": "ok"})
        on_event("final", "the answer")
        return AgentResult(persona=persona.key, question=question, answer="the answer",
                           provider="fake", turns=1)

    original_run_agent = bridge_server.run_agent
    original_record = bridge_server.common_db.record_agent_run
    original_resolve = bridge_server.providers.resolve_model
    bridge_server.run_agent = fake_run_agent
    bridge_server.common_db.record_agent_run = lambda **kw: None
    bridge_server.providers.resolve_model = lambda provider_name, model: "fake-model"
    try:
        events = _collect_sse(bridge_server._assistant_ask_sse(
            {"persona": "risk_analyst", "question": "how risky is this bank?"}, {}))
    finally:
        bridge_server.run_agent = original_run_agent
        bridge_server.common_db.record_agent_run = original_record
        bridge_server.providers.resolve_model = original_resolve

    kinds = [e for e, _ in events]
    assert kinds == ["tool_call", "tool_result", "final", "result"]
    result_payload = events[-1][1]
    assert result_payload["answer"] == "the answer"
    assert result_payload["partial"] is False


def test_stream_assistant_answer_deadline_cancels_a_slow_but_cooperative_loop():
    """A run_agent that actually checks cancel_event (like the real one, at a
    turn boundary) must come back as a clean partial result, not an error —
    the whole point of the cooperative-cancellation path (F16)."""
    require_bridge_importable()
    persona = bridge_server.PERSONAS["risk_analyst"]

    def cooperative_run_agent(persona, question, *, roles=None, on_event=None, cancel_event=None, **kw):
        # Simulates a slow provider that checks between "turns" — same
        # contract agent.py's real loop upholds.
        for _ in range(200):
            if cancel_event is not None and cancel_event.is_set():
                return AgentResult(persona=persona.key, question=question,
                                   answer="(partial — cooperatively stopped)",
                                   provider="fake", turns=1, partial=True)
            time.sleep(0.01)
        raise AssertionError("cancel_event was never observed as set")

    original_run_agent = bridge_server.run_agent
    original_deadline = bridge_server._ASSISTANT_DEADLINE_S
    original_grace = bridge_server._ASSISTANT_CANCEL_GRACE_S
    bridge_server.run_agent = cooperative_run_agent
    bridge_server._ASSISTANT_DEADLINE_S = 0.05
    bridge_server._ASSISTANT_CANCEL_GRACE_S = 2.0  # plenty of time for the loop above to notice
    try:
        events = list(bridge_server._stream_assistant_answer(persona, "q?", None))
    finally:
        bridge_server.run_agent = original_run_agent
        bridge_server._ASSISTANT_DEADLINE_S = original_deadline
        bridge_server._ASSISTANT_CANCEL_GRACE_S = original_grace

    kinds = [k for k, _ in events]
    assert "timeout" in kinds
    assert kinds[-1] == "result"
    assert events[-1][1].partial is True


def test_stream_assistant_answer_grace_period_expiry_yields_error_not_hang():
    """A run_agent that ignores cancel_event entirely (the genuinely-hung-
    provider case) must still make this generator return — within the grace
    period, not forever — as an 'error' event."""
    require_bridge_importable()
    persona = bridge_server.PERSONAS["risk_analyst"]

    def unresponsive_run_agent(persona, question, *, roles=None, on_event=None, cancel_event=None, **kw):
        time.sleep(5)  # never checks cancel_event — simulates a truly hung call
        return AgentResult(persona=persona.key, question=question, answer="too late",
                           provider="fake", turns=1)

    original_run_agent = bridge_server.run_agent
    original_deadline = bridge_server._ASSISTANT_DEADLINE_S
    original_grace = bridge_server._ASSISTANT_CANCEL_GRACE_S
    bridge_server.run_agent = unresponsive_run_agent
    bridge_server._ASSISTANT_DEADLINE_S = 0.05
    bridge_server._ASSISTANT_CANCEL_GRACE_S = 0.1
    try:
        start = time.time()
        events = list(bridge_server._stream_assistant_answer(persona, "q?", None))
        elapsed = time.time() - start
    finally:
        bridge_server.run_agent = original_run_agent
        bridge_server._ASSISTANT_DEADLINE_S = original_deadline
        bridge_server._ASSISTANT_CANCEL_GRACE_S = original_grace

    assert elapsed < 5.0, "must not have waited for the hung provider to finish"
    kinds = [k for k, _ in events]
    assert kinds == ["timeout", "error"]


def test_wsgi_app_assistant_ask_streams_sse_and_reaches_a_result_event():
    require_bridge_importable()

    def fake_run_agent(persona, question, *, roles=None, on_event=None, cancel_event=None, **kw):
        on_event("final", "streamed answer")
        return AgentResult(persona=persona.key, question=question, answer="streamed answer",
                           provider="fake", turns=1)

    original_run_agent = bridge_server.run_agent
    original_record = bridge_server.common_db.record_agent_run
    original_resolve = bridge_server.providers.resolve_model
    bridge_server.run_agent = fake_run_agent
    bridge_server.common_db.record_agent_run = lambda **kw: None
    bridge_server.providers.resolve_model = lambda provider_name, model: "fake-model"
    prev_auth = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = False
    try:
        body = json.dumps({"persona": "risk_analyst", "question": "q?"}).encode()
        cap = _CapturedResponse()
        chunks = list(bridge_server.wsgi_app(_wsgi_environ(
            "POST", "/api/assistant/ask",
            extra={"CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}), cap))
    finally:
        bridge_server.run_agent = original_run_agent
        bridge_server.common_db.record_agent_run = original_record
        bridge_server.providers.resolve_model = original_resolve
        auth.AUTH_ENABLED = prev_auth

    assert cap.status == "200 OK"
    assert cap.header("Content-Type") == "text/event-stream"
    events = _collect_sse(chunks)
    assert events[-1][0] == "result"
    assert events[-1][1]["answer"] == "streamed answer"


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
