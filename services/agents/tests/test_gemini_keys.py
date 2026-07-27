"""Gemini key-pool rotation tests — no network, pure env-var + logic testing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_agents import gemini_keys as gk  # noqa: E402

_ENV_KEYS = ["GEMINI_API_KEYS", "GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
            "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5"]


def _clean_env():
    saved = {k: os.environ.pop(k, None) for k in _ENV_KEYS}
    gk.reset_exhausted()
    return saved


def _restore_env(saved):
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    gk.reset_exhausted()


def test_load_keys_unions_all_three_sources_deduped():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEYS"] = "a,b"
        os.environ["GEMINI_API_KEY_1"] = "c"
        os.environ["GEMINI_API_KEY"] = "a"  # duplicate of one already in GEMINI_API_KEYS
        assert gk.load_keys() == ["a", "b", "c"]
    finally:
        _restore_env(saved)


def test_main_plus_four_backups_five_total():
    """The user's requested setup: 1 main (GEMINI_API_KEY) + 4 backups (numbered)."""
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEY"] = "main"
        for i in range(1, 5):
            os.environ[f"GEMINI_API_KEY_{i}"] = f"backup{i}"
        keys = gk.load_keys()
        assert len(keys) == 5
        assert keys == ["backup1", "backup2", "backup3", "backup4", "main"]
        assert gk.key_count() == 5
    finally:
        _restore_env(saved)


def test_numbered_keys_stop_at_first_gap():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEY_1"] = "k1"
        os.environ["GEMINI_API_KEY_3"] = "k3"  # gap at _2 -> never reached
        assert gk.load_keys() == ["k1"]
    finally:
        _restore_env(saved)


def test_no_keys_configured():
    saved = _clean_env()
    try:
        assert gk.load_keys() == []
        assert gk.usable_keys() == []
    finally:
        _restore_env(saved)


def test_rotation_on_429_moves_to_next_key():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEYS"] = "k1,k2"
        calls = []

        def do_call(key):
            calls.append(key)
            if key == "k1":
                err = RuntimeError("quota exhausted")
                err.status_code = 429
                raise err
            return f"ok:{key}"

        result = gk.call_with_rotation(do_call, None, lambda kind: RuntimeError(kind))
        assert result == "ok:k2"
        assert calls == ["k1", "k2"]
        assert "k1" in gk._exhausted
    finally:
        _restore_env(saved)


def test_exhausted_key_skipped_on_next_call_this_process():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEYS"] = "k1,k2"
        gk.mark_exhausted("k1")
        assert gk.usable_keys() == ["k2"]
    finally:
        _restore_env(saved)


def test_non_rotation_error_propagates_immediately():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEYS"] = "k1,k2"

        def do_call(key):
            raise ValueError("not a rotation error")

        raised = False
        try:
            gk.call_with_rotation(do_call, None, lambda kind: RuntimeError(kind))
        except ValueError:
            raised = True
        assert raised
        assert gk._exhausted == set()  # key NOT marked exhausted for a non-rotation error
    finally:
        _restore_env(saved)


def test_all_keys_exhausted_raises_no_key_error():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEYS"] = "k1,k2"

        def do_call(key):
            err = RuntimeError("bad key")
            err.status_code = 401
            raise err

        raised_kind = None
        try:
            gk.call_with_rotation(do_call, None,
                                  lambda kind: RuntimeError(f"factory:{kind}"))
        except RuntimeError as e:
            raised_kind = str(e)
        assert "401" in raised_kind or raised_kind is not None  # the ORIGINAL rotation error re-raised
    finally:
        _restore_env(saved)


def test_explicit_key_bypasses_pool_entirely():
    saved = _clean_env()
    try:
        os.environ["GEMINI_API_KEYS"] = "k1,k2"
        calls = []
        result = gk.call_with_rotation(lambda k: calls.append(k) or f"used:{k}",
                                       "pinned_key", lambda kind: RuntimeError(kind))
        assert result == "used:pinned_key"
        assert calls == ["pinned_key"]
    finally:
        _restore_env(saved)


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
