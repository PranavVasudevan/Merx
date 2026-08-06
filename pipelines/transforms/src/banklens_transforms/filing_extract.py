"""Feature 17 (Tier 6 capstone) — extract Item 1A "Risk Factors" from a real SEC
10-K HTML document, with an honest confidence signal instead of a silent guess.

The hard problem, verified live against two real filings (Pinnacle Financial
Partners CIK 2082866, Wells Fargo CIK 72971): a 10-K's table of contents ALWAYS
contains an "Item 1A" heading before the real section, and large banks routinely
say "Information in response to this Item 1A can be found in ... the Annual
Report ... incorporated by reference" instead of including the text at all (Wells
Fargo does exactly this). Naively grabbing the first "Item 1A" match and reading
to the next "Item 1B" embeds either a table-of-contents fragment or a one-sentence
pointer to a document this app doesn't have — plausible-looking garbage, not risk
factors.

The fix that actually works, verified against both real filings:
  1. Match the heading in ALL CAPS only ("ITEM 1A. RISK FACTORS", case-SENSITIVE).
     Real section headings are rendered in caps; cross-references embedded in body
     prose ("...described in \"Item 1A. Risk Factors\" below...") are not — this
     alone separates the TOC/heading occurrences from inline cross-references.
  2. Among the remaining (heading-style) candidates, the TOC entry sits immediately
     before the NEXT heading ("ITEM 1B..."), a tiny gap; the real section is
     followed by tens of thousands of characters of prose before the next heading.
     Picking the candidate with the LARGEST gap to its nearest end-marker
     correctly separates the TOC line from the real section.
  3. The resulting span length is itself the confidence signal: a real risk-factors
     section runs to many thousand characters; an "incorporated by reference"
     pointer (which still passes step 1 as a heading, since WFC's IS capitalized)
     is only a couple hundred. Below MIN_CONFIDENT_CHARS is reported as low
     confidence, not embedded as if it were real content.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r" *\n *")
_BLANK_RE = re.compile(r"\n{2,}")

# Case-SENSITIVE: real headings render in caps; cross-reference prose doesn't.
_START_RE = re.compile(r"ITEM\s*1A\.?\s*RISK\s*FACTORS")
_END_RE = re.compile(r"ITEM\s*1B\.?\s*UNRESOLVED\s*STAFF\s*COMMENTS|ITEM\s*1B\.?\s*"
                     r"|ITEM\s*2\.?\s*PROPERT")

# A real risk-factors section runs thousands of characters; an "incorporated by
# reference" pointer (Wells Fargo: 232 chars) or a stray short match doesn't.
MIN_CONFIDENT_CHARS = 2000


def html_to_text(raw_html: str) -> str:
    """Strip tags/entities to plain text, collapsing whitespace but keeping
    newlines as paragraph breaks (helps chunk_text split at real boundaries)."""
    text = _TAG_RE.sub(" ", raw_html)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n", text)
    return _BLANK_RE.sub("\n", text).strip()


@dataclass
class ExtractionResult:
    text: str | None
    confidence: str          # "high" | "low" | "failed"
    char_count: int
    reason: str


def extract_item_1a(raw_html: str) -> ExtractionResult:
    text = html_to_text(raw_html)
    starts = [m.end() for m in _START_RE.finditer(text)]
    ends = [m.start() for m in _END_RE.finditer(text)]

    if not starts:
        return ExtractionResult(None, "failed", 0, "no 'ITEM 1A. RISK FACTORS' heading found")

    best: tuple[int, int, int] | None = None
    for s in starts:
        candidates = [e for e in ends if e > s]
        if not candidates:
            continue
        e = min(candidates)
        span = e - s
        if best is None or span > best[2]:
            best = (s, e, span)

    if best is None:
        return ExtractionResult(None, "failed",
                                0, "found an Item 1A heading but no Item 1B/2 boundary after it")

    s, e, span = best
    section = text[s:e].strip()
    if span < MIN_CONFIDENT_CHARS:
        return ExtractionResult(
            section, "low", span,
            f"only {span} chars between heading and next section — likely a table-of-"
            f"contents fragment or 'incorporated by reference' pointer, not real content")
    return ExtractionResult(section, "high", span, "heading + boundary found, section length plausible")


def chunk_text(text: str, *, chunk_chars: int = 1400, overlap_chars: int = 200) -> list[str]:
    """Fixed-size character chunks with overlap, breaking on paragraph/sentence
    boundaries where possible so a chunk doesn't split mid-sentence needlessly.

    Simple and auditable (matches this project's "transparent, not a black box"
    convention elsewhere — see clustering.py, deposit_flight.py) rather than a
    tokenizer-aware splitter; nomic-embed-text's ~2k-token window comfortably
    covers chunk_chars=1400 characters of English prose.
    """
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]

    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_chars, n)
        if end < n:
            # prefer breaking at the last paragraph/sentence boundary in range
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(". "))
            if cut > chunk_chars * 0.5:   # only use it if it's not too early
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
