"""Skeleton tests for extraction robustness (run with pytest or python -m pytest).

These are fast and do not require keys.
"""

from market_research.llm import _extract_json


def test_extract_json_plain():
    assert _extract_json('[{"name": "Foo"}]') == [{"name": "Foo"}]


def test_extract_json_markdown():
    txt = 'Here is the list:\n```json\n[{"name": "Bar", "description": "x"}]\n```\nThanks.'
    assert _extract_json(txt) == [{"name": "Bar", "description": "x"}]


def test_extract_json_trailing_comma():
    txt = '[{"name": "Baz", "evidence": [{"url":"u"}]},]'
    assert _extract_json(txt) == [{"name": "Baz", "evidence": [{"url": "u"}]}]


def test_extract_bad():
    assert _extract_json("no json here") is None
    assert _extract_json("") is None
