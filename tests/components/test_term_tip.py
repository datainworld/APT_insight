"""TermTip + GLOSSARY 단위 테스트."""

from __future__ import annotations

import pytest

from dash_app.components.term_tip import TermTip
from dash_app.glossary.terms import GLOSSARY


def test_glossary_has_core_terms() -> None:
    for k in ("평당가", "호가", "호가_괴리율", "전세가율", "갭", "전용면적"):
        assert k in GLOSSARY
        assert GLOSSARY[k]["label"]
        assert GLOSSARY[k]["short"]


def test_term_tip_uses_short_as_label() -> None:
    node = TermTip("평당가")
    assert GLOSSARY["평당가"]["short"] in str(node.label)


def test_term_tip_accepts_custom_display() -> None:
    node = TermTip("호가", display="매물가")
    # children is an html.Span — its child is the display text
    assert node.children.children == "매물가"


def test_term_tip_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        TermTip("존재하지않는_용어")
