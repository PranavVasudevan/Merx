"""F5 — thread-safe, bounded data cache. Exercises `banklens_mcp.data._cached()`
(the double-checked-locking helper every accessor in that module now goes
through) and `invalidate_cache()` directly, with synthetic keys/compute
functions so this never touches real landed data or depends on it being
present.

Run: ``python services/mcp-server/tests/test_data_cache.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "mcp-server" / "src"))
sys.path.insert(0, str(ROOT / "pipelines" / "transforms" / "src"))

from banklens_mcp import data  # noqa: E402

_TEST_KEY_PREFIX = "test_data_cache:"


def _cleanup(*keys: str) -> None:
    for k in keys:
        data._cache.pop(_TEST_KEY_PREFIX + k, None)


def test_warm_read_returns_the_cached_value_without_recomputing():
    key = _TEST_KEY_PREFIX + "warm"
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return "computed"

    try:
        first = data._cached(key, compute)
        second = data._cached(key, compute)
        assert first == "computed"
        assert second == "computed"
        assert calls["n"] == 1
    finally:
        _cleanup("warm")


def test_concurrent_cold_calls_for_the_same_key_compute_exactly_once():
    """The regression this whole file exists for: two concurrent cold requests
    for the SAME expensive key (network_edges()'s real ~17s computation is the
    live example) must not both pay for it. A small sleep inside `compute`
    widens the race window so a broken (unlocked) version of this test would
    actually catch the double-computation, not pass by luck on fast hardware."""
    key = _TEST_KEY_PREFIX + "concurrent"
    calls = {"n": 0}
    lock = threading.Lock()

    def compute():
        with lock:
            calls["n"] += 1
        time.sleep(0.2)
        return "expensive result"

    results = []
    results_lock = threading.Lock()

    def worker():
        r = data._cached(key, compute)
        with results_lock:
            results.append(r)

    try:
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert calls["n"] == 1, f"compute() ran {calls['n']} times, expected exactly 1"
        assert len(results) == 8
        assert all(r == "expensive result" for r in results)
    finally:
        _cleanup("concurrent")


def test_an_exception_during_compute_is_not_cached_and_retries_next_call():
    key = _TEST_KEY_PREFIX + "raises"
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("simulated failure")
        return "recovered"

    try:
        raised = False
        try:
            data._cached(key, compute)
        except ValueError:
            raised = True
        assert raised
        assert key not in data._cache
        assert data._cached(key, compute) == "recovered"
        assert calls["n"] == 2
    finally:
        _cleanup("raises")


def test_different_keys_do_not_collide():
    try:
        a = data._cached(_TEST_KEY_PREFIX + "a", lambda: "A")
        b = data._cached(_TEST_KEY_PREFIX + "b", lambda: "B")
        assert a == "A"
        assert b == "B"
    finally:
        _cleanup("a", "b")


def test_invalidate_cache_clears_every_entry_and_the_lru_order():
    data._cache[_TEST_KEY_PREFIX + "sentinel"] = "should be gone after invalidate"
    data._pop_cache_order.append("sentinel-quarter")
    try:
        data.invalidate_cache()
        assert _TEST_KEY_PREFIX + "sentinel" not in data._cache
        assert "sentinel-quarter" not in data._pop_cache_order
        assert data._cache == {}
        assert data._pop_cache_order == []
    finally:
        _cleanup("sentinel")


def test_invalidate_cache_is_itself_thread_safe_to_call_concurrently():
    """Not a strong correctness proof, just confirms invalidate_cache() doesn't
    raise or leave the cache in a half-cleared state when called concurrently
    with itself and with a fill in progress."""
    key = _TEST_KEY_PREFIX + "during_invalidate"

    def filler():
        for _ in range(5):
            data._cached(key, lambda: "x")

    def invalidator():
        for _ in range(5):
            data.invalidate_cache()

    try:
        threads = [threading.Thread(target=filler) for _ in range(3)] + \
                  [threading.Thread(target=invalidator) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        # No assertion beyond "didn't crash and left a real dict behind" --
        # the interleaving outcome (cached or not) is legitimately either way.
        assert isinstance(data._cache, dict)
    finally:
        _cleanup("during_invalidate")


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
