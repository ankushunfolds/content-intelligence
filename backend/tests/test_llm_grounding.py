"""Section 14 is a product rule, so it gets tested like one: the LLM may only
rephrase numbers that came from the database."""
from __future__ import annotations

import re

from app.services.llm import MockLLM, _extract_json


def test_classification_is_consistent_for_the_same_title():
    llm = MockLLM()
    payload = '{"videos":[{"id":1,"title":"I Tested 10 AI Agents for 30 Days","tags":[]}]}'
    first = llm.complete_json("", payload)["results"][0]
    second = llm.complete_json("", payload)["results"][0]
    assert first == second


def test_classification_recognises_topic_and_format():
    result = MockLLM().complete_json("", '{"videos":[{"id":1,"title":"I Tested 10 AI Agents","tags":[]}]}')
    row = result["results"][0]
    assert row["topic"] == "AI"
    assert row["subtopic"] == "AI Agents"
    assert row["format"] == "Experiment"


def test_narration_only_uses_supplied_numbers():
    brief = {
        "opportunities": [
            {
                "id": 0,
                "topic": "AI",
                "subtopic": "AI Agents",
                "top_format": "Experiment",
                "evidence": {
                    "window_days": 7,
                    "creator_count": 7,
                    "volume_growth_pct": "+43%",
                    "avg_performance": "2.7×",
                },
            }
        ],
        "competitor_highlights": [],
    }
    written = MockLLM().complete_json("", f'{{"brief": {_json(brief)}}}')
    text = written["opportunities"][0]["why_it_matters"]

    for supplied in ("7", "43%", "2.7×"):
        assert supplied in text

    # Every number in the sentence must be traceable to the evidence we passed in.
    allowed = {"7", "43", "2.7"}
    for number in re.findall(r"\d+(?:\.\d+)?", text):
        assert number in allowed, f"invented number {number!r} in: {text}"


def test_json_extraction_survives_fenced_output():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def _json(value) -> str:
    import json

    return json.dumps(value)
