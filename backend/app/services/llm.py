"""Provider-agnostic LLM adapter.

One interface, three implementations (mock / OpenAI / Gemini), selected by
LLM_PROVIDER. Every call returns JSON; the caller never sees provider details.

The LLM is only ever used for semantic work — classifying a title, phrasing an
explanation. It never produces a statistic (Section 14).
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx

from app.config import settings
from app.utils.logging import logger


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    name: str

    def complete_json(self, system: str, user: str, *, model: str | None = None) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in prose or fences. Pull out the first object."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError(f"No JSON object in model output: {text[:200]}")
    return json.loads(match.group(0))


class MockLLM:
    """Keyword-driven stand-in.

    Not a toy: it produces consistent, plausible classifications and evidence-led
    prose, so the whole pipeline is demoable and testable without a key or a bill.
    """

    name = "mock"

    TOPIC_RULES: list[tuple[tuple[str, ...], tuple[str, str]]] = [
        (("ai agent", "agentic", "autonomous"), ("AI", "AI Agents")),
        (("prompt",), ("AI", "Prompt Engineering")),
        (("local llm", "ollama", "open source model"), ("AI", "Local LLMs")),
        (("ai video", "veo", "sora", "runway"), ("AI", "AI Video Tools")),
        (("automation", "automate", "workflow"), ("Creator Economy", "Creator Automation")),
        (("monetiz", "sponsor", "revenue", "adsense"), ("Creator Economy", "Monetization")),
        (("subscriber", "grow", "audience", "algorithm"), ("Creator Economy", "Audience Growth")),
        (("notion", "obsidian", "note"), ("Productivity", "Note Taking")),
        (("system", "routine", "productiv"), ("Productivity", "Workflow Systems")),
        (("solo founder", "indie hacker", "bootstrap"), ("Business", "Solo Founders")),
        (("saas", "startup", "teardown"), ("Business", "SaaS Teardowns")),
        (("review", "hardware", "laptop", "camera"), ("Technology", "Hardware Reviews")),
        (("ai",), ("AI", "General AI")),
    ]

    FORMAT_RULES: list[tuple[tuple[str, ...], str]] = [
        (("i tested", "i tried", "i used", "days of", "experiment"), "Experiment"),
        (("how to", "guide", "tutorial", "setup", "step by step"), "Tutorial"),
        (("review", "worth it", "honest"), "Review"),
        (("how i", "case study", "what worked", "grew"), "Case Study"),
        (("why", "truth about", "wrong about", "problem with"), "Commentary"),
        (("interview", "talking", "explains", "with "), "Interview"),
    ]

    def _classify_title(self, title: str, tags: list[str]) -> dict[str, str]:
        haystack = f"{title} {' '.join(tags)}".lower()

        topic, subtopic = "General", "General"
        for keywords, (t, s) in self.TOPIC_RULES:
            if any(k in haystack for k in keywords):
                topic, subtopic = t, s
                break

        fmt = "Listicle" if re.search(r"\b\d+\b", title) else "Commentary"
        for keywords, f in self.FORMAT_RULES:
            if any(k in haystack for k in keywords):
                fmt = f
                break

        # Angle: the distinctive part of the title, trimmed of boilerplate.
        angle = re.sub(r"\s*\((?:complete guide|full guide|2026|2025)\)\s*", "", title, flags=re.I).strip()
        return {"topic": topic, "subtopic": subtopic, "format": fmt, "angle": angle[:200]}

    def complete_json(self, system: str, user: str, *, model: str | None = None) -> dict[str, Any]:
        payload = _extract_json(user) if user.strip().startswith("{") else {"input": user}

        if "videos" in payload:  # batch classification
            return {
                "results": [
                    {"id": v.get("id"), **self._classify_title(v.get("title", ""), v.get("tags", []))}
                    for v in payload["videos"]
                ]
            }

        if "brief" in payload:  # daily brief narration
            return self._narrate_brief(payload["brief"])

        return {}

    def _narrate_brief(self, data: dict[str, Any]) -> dict[str, Any]:
        opportunities = []
        for item in data.get("opportunities", []):
            ev = item.get("evidence", {})
            opportunities.append(
                {
                    "id": item.get("id"),
                    "why_it_matters": (
                        f"{ev.get('creator_count', 0)} tracked creators published on "
                        f"{item.get('subtopic') or item.get('topic')} in the last "
                        f"{ev.get('window_days', 7)} days, {ev.get('volume_growth_pct', '0%')} more than the "
                        f"prior window, and those videos averaged "
                        f"{ev.get('avg_performance', '1×')} their creators' median views."
                    ),
                    "suggested_direction": _suggest_title(
                        item.get("subtopic") or item.get("topic", ""), item.get("top_format", "Experiment")
                    ),
                }
            )

        highlights = []
        for item in data.get("competitor_highlights", []):
            highlights.append(
                {
                    "id": item.get("id"),
                    "why_it_matters": (
                        f"{item.get('channel_name')} is running {item.get('performance')} their normal baseline "
                        f"with a {item.get('format', 'video').lower()} on {item.get('subtopic') or 'this topic'} — "
                        f"a format-and-topic pairing that is working right now in your niche."
                    ),
                }
            )

        headline = data.get("headline_fallback") or "Today's signals from your tracked channels."
        return {"headline": headline, "opportunities": opportunities, "competitor_highlights": highlights}


def _suggest_title(subtopic: str, fmt: str) -> str:
    """Section 15: trend + working format + niche -> a content direction."""
    # Don't produce "AI Agents Tools" — a topic that's already a plural noun
    # ("AI Agents", "AI Video Tools") reads fine on its own.
    noun = "" if subtopic.rstrip().lower().endswith("s") else " Tools"

    templates = {
        "Experiment": f"I Tested 10 {subtopic}{noun} to See Which Ones Actually Save Time",
        "Tutorial": f"{subtopic}: The Complete Setup Guide (2026)",
        "Listicle": f"7 {subtopic}{noun} Worth Your Time Right Now",
        "Review": f"{subtopic} After 30 Days — An Honest Review",
        "Case Study": f"How I Used {subtopic} to Change My Workflow",
        "Commentary": f"What Everyone Gets Wrong About {subtopic}",
        "Interview": f"A Full-Time Creator Explains {subtopic}",
    }
    return templates.get(fmt, templates["Experiment"])


class OpenAILLM:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.api_key = api_key

    def complete_json(self, system: str, user: str, *, model: str | None = None) -> dict[str, Any]:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model or settings.llm_classify_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=90.0,
        )
        if response.status_code >= 400:
            raise LLMError(f"OpenAI error {response.status_code}: {response.text[:300]}")
        return _extract_json(response.json()["choices"][0]["message"]["content"])


class GeminiLLM:
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.api_key = api_key

    def complete_json(self, system: str, user: str, *, model: str | None = None) -> dict[str, Any]:
        model_name = model or settings.llm_classify_model
        if model_name.startswith("gpt"):  # sensible default if left at the OpenAI value
            model_name = "gemini-2.0-flash"
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
            params={"key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
            },
            timeout=90.0,
        )
        if response.status_code >= 400:
            raise LLMError(f"Gemini error {response.status_code}: {response.text[:300]}")
        candidates = response.json().get("candidates") or []
        if not candidates:
            raise LLMError("Gemini returned no candidates")
        return _extract_json(candidates[0]["content"]["parts"][0]["text"])


def get_llm() -> LLMClient:
    provider = settings.llm_provider
    try:
        if provider == "openai":
            return OpenAILLM(settings.openai_api_key)
        if provider == "gemini":
            return GeminiLLM(settings.gemini_api_key)
    except LLMError as exc:
        logger.warning("LLM provider '%s' unavailable (%s) — using mock", provider, exc)
    return MockLLM()


def get_llm_with_fallback() -> tuple[LLMClient, LLMClient]:
    """Primary client plus the mock, so a provider outage degrades instead of failing."""
    return get_llm(), MockLLM()
