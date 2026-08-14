"""Fails when a comment/docstring references a repo-relative file path that
does not exist — the class of drift F2 in docs/audit/04-remediation-prompts.md
found (eleven files referenced across the codebase that were never written).

Heuristic, by design conservative against false positives:
  - Only scans source/doc files likely to carry prose (py, ts, tsx, rs, md,
    yml, yaml, Dockerfile) — skips node_modules, .git, data, build output.
  - A candidate path must contain at least one "/" and end in a known
    documentation/source extension (.md/.py/.ts/.tsx/.rs/.yml/.yaml), UNLESS
    it's one of a small allowlisted set of bare root-level filenames
    (CHANGELOG.md, README.md, etc.) that are unambiguous even without a
    directory prefix.
  - URLs are stripped from each line before matching, so a real
    https://.../README.md reference on GitHub is never checked against the
    local filesystem.
  - Template/interpolated paths (containing `{`, `}`, `<`, `>`, `$`, or a
    trailing quote/backtick mid-token) are skipped — an f-string path built
    at runtime isn't a static claim this check can verify.
  - A candidate's leading path segment must be one of this repo's own
    top-level directories — "matcher/clients/gemini_keys.py" in a comment
    crediting the prior project this code was ported FROM is not a claim
    about anything in THIS repo, and must never be checked against it.
  - Markdown fenced code blocks (```...```) are skipped entirely — a shell
    command example whose output redirects into a not-yet-created file is not
    a claim that the file already exists.
  - `docs/audit/` is skipped: it's a frozen, dated point-in-time report
    (commit-pinned per `docs/audit/README.md`) whose entire purpose is
    cataloging files that did NOT exist as of that audit — checking it here
    would be circular.

Run: ``python scripts/check_doc_references.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".rs", ".md", ".yml", ".yaml"}
SCAN_BASENAMES = {"Dockerfile"}

SKIP_DIR_NAMES = {
    "node_modules", ".git", "data", "__pycache__", "dist", "build",
    ".venv", "venv", "target", ".pytest_cache", ".tmp", ".claude",
}

# Relative-to-repo-root path prefixes exempt from this check entirely (not a
# generic SKIP_DIR_NAMES entry -- those apply everywhere; this is scoped to
# specific known paths only).
SKIP_PATHS = {"docs/audit"}

# This repo's own top-level directories -- a candidate token must start with
# one of these (or be in BARE_ALLOWLIST) to be treated as a claim about THIS
# repo at all.
_TOP_LEVEL_DIRS = {
    p.name for p in REPO.iterdir()
    if p.is_dir() and p.name not in SKIP_DIR_NAMES and not p.name.startswith(".")
}

# Unambiguous even without a directory prefix — real root-level files a
# comment might reasonably reference by bare name.
BARE_ALLOWLIST = {
    "CHANGELOG.md", "README.md", "SECURITY.md", "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md", "LICENSE", "Makefile",
}

_PATH_EXT_RE = r"[A-Za-z0-9_\-./]+\.(?:md|py|ts|tsx|rs|ya?ml)"
_PATH_WITH_SLASH_RE = re.compile(r"(?<![\w./\-])((?:[A-Za-z0-9_\-]+/)+" + _PATH_EXT_RE.replace("[A-Za-z0-9_\\-./]+\\.", "[A-Za-z0-9_\\-.]+\\.") + r")(?![\w])")
_URL_RE = re.compile(r"https?://\S+")
_BAD_CHARS = set("{}<>$")


def _scan_files() -> list[Path]:
    out = []
    for p in REPO.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        if p.suffix in SCAN_EXTENSIONS or p.name in SCAN_BASENAMES:
            out.append(p)
    return out


def _candidates_in_line(line: str) -> list[str]:
    line = _URL_RE.sub(" ", line)
    found = []
    for m in _PATH_WITH_SLASH_RE.finditer(line):
        tok = m.group(1)
        if any(c in _BAD_CHARS for c in tok):
            continue
        if tok.split("/", 1)[0] not in _TOP_LEVEL_DIRS:
            continue
        found.append(tok)
    for name in BARE_ALLOWLIST:
        if re.search(r"(?<![\w./\-])" + re.escape(name) + r"(?![\w])", line):
            found.append(name)
    return found


def _strip_markdown_code_fences(text: str) -> str:
    out_lines = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out_lines.append("")
            continue
        out_lines.append("" if in_fence else line)
    return "\n".join(out_lines)


def _all_repo_paths() -> list[str]:
    """Every real file's repo-relative POSIX path, for the suffix-match fallback
    below — a short reference like "banklens_mcp/data.py" from an unrelated
    package almost always means the one real file that ends with exactly that,
    not a literal repo-root-relative path."""
    out = []
    for p in REPO.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        out.append(p.relative_to(REPO).as_posix())
    return out


def _resolves(tok: str, referencing_file: Path, all_paths: list[str]) -> bool:
    """A candidate resolves if it exists as: (a) a repo-root-relative path —
    the primary, unambiguous case; (b) relative to some ancestor directory of
    the file that mentioned it — covers "see sources/fdic.py" written from a
    sibling module inside the same package; or (c) as the exact tail of some
    real file's path anywhere in the repo — covers a short cross-package
    mention like "banklens_mcp/data.py" that isn't relative to anything in
    particular, just shorthand for the one file it can only mean."""
    if (REPO / tok).exists():
        return True
    d = referencing_file.parent
    while True:
        if (d / tok).exists():
            return True
        if d == REPO or d.parent == d:
            break
        d = d.parent
    # Every package in this repo is named banklens_<thing> — prose commonly
    # drops that prefix ("see transforms/xray.py" for banklens_transforms/
    # xray.py). Try the bare token first, then with that prefix restored on
    # its leading path segment.
    candidates = [tok]
    if "/" in tok:
        head, rest = tok.split("/", 1)
        if not head.startswith("banklens_"):
            candidates.append(f"banklens_{head}/{rest}")
    for cand in candidates:
        suffix = "/" + cand
        if any(p == cand or p.endswith(suffix) for p in all_paths):
            return True
    return False


def main() -> int:
    all_paths = _all_repo_paths()
    problems: list[tuple[str, int, str]] = []
    for f in _scan_files():
        rel = f.relative_to(REPO).as_posix()
        if any(rel == sp or rel.startswith(sp + "/") for sp in SKIP_PATHS):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if f.suffix == ".md":
            text = _strip_markdown_code_fences(text)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for tok in _candidates_in_line(line):
                if not _resolves(tok, f, all_paths):
                    rel = f.relative_to(REPO).as_posix()
                    problems.append((rel, lineno, tok))

    if problems:
        print(f"FAIL: {len(problems)} reference(s) to a repo path that does not exist:\n")
        for rel, lineno, tok in problems:
            print(f"  {rel}:{lineno}: references {tok!r}, which does not exist")
        print("\nEither create the file, or remove/fix the claim.")
        return 1

    print("OK: no dangling repo-path references found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
