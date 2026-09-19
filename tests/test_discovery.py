"""Tests for autonomous opportunity discovery (find -> record -> pipeline)."""

import json

import pytest

from src.agents.discovery import _extract_json, _norm, discover
from src.config.settings import Settings


class _FakeLLM:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.invocations = 0

    def invoke(self, messages):
        self.invocations += 1
        content = self._payloads.pop(0) if self._payloads else "[]"
        return type("Resp", (), {"content": content})


def _idea_payload(title="Widget automation", summary="A case for a widget service",
                  category="automation", revenue_model="recurring", signal=0.8,
                  capital=500.0, monthly=4000.0, months=6):
    return {
        "title": title,
        "summary": summary,
        "category": category,
        "revenue_model": revenue_model,
        "source_urls": ["https://example.com/widget"],
        "signal_strength": signal,
        "required_capital": capital,
        "projected_monthly_revenue": monthly,
        "timeframe_months": months,
    }


@pytest.fixture(autouse=True)
def _offline_research(monkeypatch):
    monkeypatch.setattr("src.agents.discovery.web_research", lambda q: f"signals for {q}")


def test_extract_json_tolerates_fences_and_has_words():
    assert _extract_json('Here is the list:\n```json\n[{"title": "A"}]\n```\nthanks') == [{"title": "A"}]
    assert _extract_json("nothing here") == []
    assert _extract_json('{"not": "an array"}') == []


def test_extract_json_regex_finds_trailing_bracket():
    assert _extract_json('scale 0..1 then:\n[{"title": "B", "summary": "s"}]') == [{"title": "B", "summary": "s"}]


def test_discover_records_new_ideas_and_dedupes(fresh_store):
    payload = [_idea_payload("Auto widget", summary="one"), _idea_payload("Auto widget", summary="duplicate")]
    llm = _FakeLLM(["[]", json.dumps(payload)])
    settings = Settings.from_env(require_key=False)

    ids = discover(settings, llm=llm, queries=["q1", "q2"], per_run=2)

    assert ids and len(ids) == 1
    recorded = [i for i in STORE_data(fresh_store)["ideas"] if i["title"] == "Auto widget"]
    assert len(recorded) == 1
    assert recorded[0]["status"] == "proposed"
    assert recorded[0]["source_urls"] == ["https://example.com/widget"]


def test_discover_skips_existing_idea_titles(fresh_store):
    STORE_data(fresh_store)["ideas"].append({
        "id": "IV-000", "title": "Existing widget", "summary": "x", "status": "proposed",
        "required_capital": 0, "projected_monthly_revenue": 0, "timeframe_months": 1,
        "category": "service", "revenue_model": "project", "signal_strength": 0.5, "source_urls": [],
    })
    llm = _FakeLLM([json.dumps([_idea_payload("Existing widget")])])

    ids = discover(Settings.from_env(require_key=False), llm=llm, queries=["q"], per_run=1)

    assert ids == []


def test_discover_honors_per_run_cap(fresh_store):
    payload = [_idea_payload("C1"), _idea_payload("C2"), _idea_payload("C3")]
    llm = _FakeLLM([json.dumps(payload)])

    ids = discover(Settings.from_env(require_key=False), llm=llm, queries=["q"], per_run=2)

    assert len(ids) == 2


def test_discover_skips_invalid_records(fresh_store):
    bad = _idea_payload("Bad idea", category="category-that-does-not-exist")
    llm = _FakeLLM([json.dumps([bad])])

    ids = discover(Settings.from_env(require_key=False), llm=llm, queries=["q"], per_run=2)

    assert ids == []


def test_norm_tokens():
    assert _norm("  A B.C !!  ") == "a b c"


def STORE_data(fresh_store):
    from src.tools.base import STORE
    return STORE.data