"""Hermetic tests for filing_extract — synthetic HTML fixtures that reproduce the
real structural patterns found live in two actual 10-Ks (Pinnacle Financial
Partners CIK 2082866: TOC entry + cross-references + real section; Wells Fargo
CIK 72971: heading present but incorporated by reference, no real text)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.filing_extract import (  # noqa: E402
    chunk_text, extract_item_1a, html_to_text,
)

REAL_RISK_TEXT = (
    "Investing in our common stock involves various risks which are particular "
    "to our company, our industry and our market areas. " + ("Risk factor prose. " * 200)
)

PNFP_LIKE = f"""
<html><body>
<p>TABLE OF CONTENTS Page No. PART I ITEM 1. BUSINESS 4 ITEM 1A. RISK FACTORS 23
ITEM 1B. UNRESOLVED STAFF COMMENTS 46 ITEM 2. PROPERTIES 48</p>
<p>A detailed description of these and other risks is contained in "Item 1A. Risk
Factors" below. Many of such factors are beyond our ability to control.</p>
<p>The disclosures set forth in this item are qualified by Item 1A. Risk Factors
and the section captioned Forward-Looking Statements.</p>
<p>ITEM 1A. RISK FACTORS {REAL_RISK_TEXT}</p>
<p>ITEM 1B. UNRESOLVED STAFF COMMENTS None.</p>
</body></html>
"""

WFC_LIKE = """
<html><body>
<p>ITEM 1A. RISK FACTORS Information in response to this Item 1A can be found in
this report under Item 1 and in the Annual Report to Shareholders under
"Financial Review Risk Factors." That information is incorporated by reference.</p>
<p>ITEM 1B. UNRESOLVED STAFF COMMENTS None.</p>
</body></html>
"""

NO_HEADING = "<html><body><p>This filing has no Item 1A section at all.</p></body></html>"


def test_html_to_text_strips_tags_and_entities():
    out = html_to_text("<p>Hello&nbsp;World &amp; Co.</p>")
    assert "Hello" in out and "World" in out and "&nbsp;" not in out and "<p>" not in out


def test_extracts_real_section_not_toc_or_cross_references():
    r = extract_item_1a(PNFP_LIKE)
    assert r.confidence == "high"
    assert r.text is not None
    assert "Investing in our common stock" in r.text
    # must NOT be the TOC fragment or a cross-reference
    assert "TABLE OF CONTENTS" not in r.text
    assert '"Item 1A. Risk Factors" below' not in r.text


def test_incorporated_by_reference_is_low_confidence_not_embedded_as_real():
    r = extract_item_1a(WFC_LIKE)
    assert r.confidence == "low"
    assert r.char_count < 2000
    assert "incorporated by reference" in (r.text or "")


def test_no_heading_found_is_a_clear_failed_state():
    r = extract_item_1a(NO_HEADING)
    assert r.confidence == "failed"
    assert r.text is None
    assert "no 'ITEM 1A" in r.reason


def test_chunk_text_covers_the_whole_input_with_overlap():
    text = "Sentence one. " * 500
    chunks = chunk_text(text, chunk_chars=500, overlap_chars=50)
    assert len(chunks) > 1
    # every chunk is non-empty and within a sane size band
    for c in chunks:
        assert 0 < len(c) <= 600
    # reassembling with overlap removed should not lose content from the middle
    assert chunks[0] in text
    assert chunks[-1].strip() in text


def test_chunk_text_short_input_returns_single_chunk():
    assert chunk_text("short text") == ["short text"]


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("") == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + (f"OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
