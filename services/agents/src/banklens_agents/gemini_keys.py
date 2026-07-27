"""Gemini API key pool with automatic rotation on exhaustion.

Ported from project-matcher's `matcher/clients/gemini_keys.py` (same design, same
env-var contract) so a BankLens deployment gets the identical "drop in N keys, get
Nx the throughput" behavior without new plumbing per call site.

A deployment can supply SEVERAL Gemini keys (e.g. "1 main + 4 backups"). When the
key currently in use hits its quota (HTTP 429) or is rejected (401/403), the caller
transparently rotates to the next key instead of failing the whole run.

Design notes (identical to the project-matcher original):
  - Keys are read FRESH from the environment on every request — no cached snapshot
    to go stale when a key is added or removed.
  - Exhaustion is remembered process-wide by key VALUE (not position), so a key
    that 429'd once is skipped for the life of the process. reset_exhausted()
    clears that (tests, or a deliberate fresh start).
  - Imports nothing but stdlib, so it has zero coupling to the rest of the agent
    framework.

Env sources (all unioned, de-duplicated, in this priority order):
  - GEMINI_API_KEYS      comma-separated list, e.g. "k1,k2,k3,k4,k5"
  - GEMINI_API_KEY_1..N  individually numbered (stops at the first gap)
  - GEMINI_API_KEY       single key / "the main key" (back-compat)

To set up "1 main + 4 backups": GEMINI_API_KEY=<main>, GEMINI_API_KEY_1..GEMINI_API_KEY_4=<backups>
(or just GEMINI_API_KEYS=<main>,<backup1>,<backup2>,<backup3>,<backup4> — simplest).
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Set

# HTTP statuses that mean "this KEY is unusable — rotate to the next one" rather
# than "transient, retry the SAME key with backoff": quota exhausted (429) or auth
# rejected (401/403). Everything else (5xx, network) is the caller's transient-
# retry concern, not a reason to burn a key.
KEY_ROTATION_STATUSES = {401, 403, 429}

# Process-wide, by key value. Not thread-locked: worst case under a race is an
# already-exhausted key gets one extra doomed attempt, which is harmless.
_exhausted: Set[str] = set()


def load_keys() -> List[str]:
    """All configured Gemini keys, de-duplicated, in priority order. Reads the
    environment live every call (see module docstring)."""
    keys: List[str] = []

    multi = os.environ.get("GEMINI_API_KEYS", "")
    keys.extend(k.strip() for k in multi.split(","))

    i = 1
    while True:
        numbered = os.environ.get(f"GEMINI_API_KEY_{i}")
        if not numbered:
            break
        keys.append(numbered.strip())
        i += 1

    single = os.environ.get("GEMINI_API_KEY")
    if single:
        keys.append(single.strip())

    seen: Set[str] = set()
    ordered: List[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered


def usable_keys() -> List[str]:
    """Configured keys minus the ones already known to be exhausted."""
    return [k for k in load_keys() if k not in _exhausted]


def key_count() -> int:
    """How many keys are configured (regardless of exhaustion) — for diagnostics."""
    return len(load_keys())


def mark_exhausted(key: Optional[str]) -> None:
    if key:
        _exhausted.add(key)


def reset_exhausted() -> None:
    """Forget which keys were exhausted (tests, or a manual fresh start)."""
    _exhausted.clear()


def is_rotation_error(exc: BaseException) -> bool:
    """Does this exception mean 'rotate to the next key'? True for an error the
    HTTP layer tagged with a 401/403/429 `status_code`."""
    return getattr(exc, "status_code", None) in KEY_ROTATION_STATUSES


def call_with_rotation(
    do_call: Callable[[str], object],
    explicit_key: Optional[str],
    no_key_error_factory: Callable[[str], BaseException],
):
    """Run `do_call(key)`, rotating keys on exhaustion.

    - `explicit_key` given: call once with exactly that key, no pool/rotation.
    - otherwise: try each usable env key in order. On a rotation error (401/403/429)
      mark that key exhausted and try the next; any other error propagates
      immediately. When every key is exhausted, re-raise the last rotation error.
    """
    if explicit_key:
        return do_call(explicit_key)

    keys = usable_keys()
    if not keys:
        raise no_key_error_factory("exhausted" if load_keys() else "no_keys")

    last_rotation_exc: Optional[BaseException] = None
    for key in keys:
        try:
            return do_call(key)
        except Exception as exc:  # noqa: BLE001 — inspect, then rotate or re-raise
            if is_rotation_error(exc):
                mark_exhausted(key)
                last_rotation_exc = exc
                continue
            raise
    if last_rotation_exc is not None:
        raise last_rotation_exc
    raise no_key_error_factory("exhausted")
