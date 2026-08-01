"""bridge_server.py tests — the pure helper logic only (query/body parsing,
the watchlist "sub" guard). The route table itself is exercised live via a
real browser session against the running bridge (see CHANGELOG.md); no
hermetic HTTP-level test doubles the ThreadingHTTPServer here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bridge_server  # noqa: E402


def test_certs_parses_comma_separated_list():
    assert bridge_server._certs("1,2,3") == [1, 2, 3]


def test_certs_ignores_stray_whitespace_and_empty_entries():
    assert bridge_server._certs(" 1, 2,,3 ") == [1, 2, 3]


def test_require_sub_returns_sub_claim():
    assert bridge_server._require_sub({"sub": "abc-123"}) == "abc-123"


def test_require_sub_raises_when_claim_missing():
    try:
        bridge_server._require_sub({})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_assistant_ask_rejects_unknown_persona():
    try:
        bridge_server._assistant_ask({"persona": "not_a_real_persona", "question": "hi"}, {})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown persona" in str(e)


def test_assistant_ask_rejects_empty_question():
    try:
        bridge_server._assistant_ask({"persona": "generalist", "question": "   "}, {})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "non-empty" in str(e)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
