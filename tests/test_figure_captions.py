"""Tests for `docs/figure_captions.md` discipline.

Per ТЗ §10 + the viz-005 feature spec:
  * one caption per Tier A figure (fig01, fig02, fig03, fig04, fig06; fig05 retired)
  * each caption ≤ 80 words
  * fig03 caption must explicitly note setup2 ≡ setup3 (no workflow controls)
  * no caption claims accuracy against truth (no "matches the observed", "outperforms
    truth", "accuracy against" phrasings)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CAPTIONS_PATH = Path(__file__).resolve().parent.parent / "docs" / "figure_captions.md"
EXPECTED_FIGURES = ("fig01", "fig02", "fig03", "fig04", "fig06")
WORD_LIMIT = 80
TRUTH_CLAIM_PATTERNS = (
    r"matches the observed",
    r"matches the actual",
    r"matches the truth",
    r"outperforms .*truth",
    r"outperforms .*baseline",  # too strong — needs a Phase-3 caveat
    r"accuracy against",
)


def _document() -> str:
    assert CAPTIONS_PATH.exists(), f"docs/figure_captions.md missing"
    return CAPTIONS_PATH.read_text(encoding="utf-8")


def _captions() -> dict[str, str]:
    """Return {fig_id: blockquote_text} for each top-level caption section."""
    text = _document()
    sections = re.split(r"\n## Figure ", text)[1:]   # drop preamble
    out: dict[str, str] = {}
    for s in sections:
        # Map heading number → fig id: 1→fig01, 2→fig02, 3→fig03, 4→fig04, 6→fig06
        m = re.match(r"^(\d+)", s)
        if not m:
            continue
        n = int(m.group(1))
        fig_id = f"fig{n:02d}"
        # Pull the first blockquote in the section
        quote_lines = [
            ln[2:] for ln in s.splitlines() if ln.startswith("> ")
        ]
        out[fig_id] = " ".join(quote_lines)
    return out


def test_document_present_and_non_empty() -> None:
    text = _document()
    assert len(text) > 1500, "document is suspiciously short"


def test_all_five_tier_a_captions_present() -> None:
    captions = _captions()
    assert set(captions.keys()) == set(EXPECTED_FIGURES), (
        f"Missing or extra figures: {set(EXPECTED_FIGURES) ^ set(captions.keys())}"
    )


@pytest.mark.parametrize("fig_id", EXPECTED_FIGURES)
def test_each_caption_under_word_limit(fig_id: str) -> None:
    cap = _captions()[fig_id]
    n_words = len(cap.split())
    assert n_words <= WORD_LIMIT, (
        f"{fig_id} caption is {n_words} words, exceeds the {WORD_LIMIT}-word limit"
    )


def test_fig03_notes_setup2_equals_setup3() -> None:
    """The fig03 caption MUST mention the setup2 ≡ setup3 degeneration."""
    cap = _captions()["fig03"]
    cap_lower = cap.lower()
    assert (
        "setup3 reproduces setup2" in cap_lower
        or "setup2 ≡ setup3" in cap_lower
        or "setup3 ≡ setup2" in cap_lower
        or ("degrades" in cap_lower and "setup2" in cap_lower)
    ), (
        "fig03 caption must explicitly note that setup3 degenerates to setup2 "
        "because workflow controls are absent for this dataset."
    )


@pytest.mark.parametrize("fig_id", EXPECTED_FIGURES)
def test_no_truth_claim_phrasing(fig_id: str) -> None:
    """No caption may claim accuracy against truth — no such truth exists."""
    cap = _captions()[fig_id]
    for pattern in TRUTH_CLAIM_PATTERNS:
        assert not re.search(pattern, cap, flags=re.IGNORECASE), (
            f"{fig_id} caption contains forbidden truth-claim phrasing "
            f"matching r'{pattern}'. There is no out-of-sample truth for "
            f"2019-2024; captions must be careful not to suggest otherwise."
        )


def test_retired_fig05_explicitly_acknowledged() -> None:
    """The retired fig05 must be explicitly called out so readers do not assume
    it is missing in error."""
    text = _document()
    assert "fig05" in text.lower() or "figure 5" in text.lower()
    assert "retired" in text.lower()


def test_methodology_cross_references_present() -> None:
    """At least three captions cross-reference docs/methodology.md."""
    captions = _captions()
    n_refs = sum(1 for cap in captions.values() if "methodology.md" in cap or "data_format.md" in cap)
    assert n_refs >= 3, (
        f"Only {n_refs} captions cross-reference docs/methodology.md or "
        f"docs/data_format.md; expected at least 3 for a publishable set."
    )
