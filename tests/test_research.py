"""Tests for market intelligence: web research (offline via stubbed fetcher) and idea records."""

import pytest

from src.tools import research
from src.tools.research import archive_idea, list_ideas, record_idea, web_research


def _signals():
    return [
        {"title": "How Indie Hackers Ship Micro-SaaS", "url": "http://example.com/saas", "snippet": "a deep dive on bootstrapped products", "source": "hacker_news"},
        {"title": "Bootstrapped SaaS", "url": "https://en.wikipedia.org/wiki/Bootstrapped_SaaS", "snippet": "companies that develop a product with no outside capital", "source": "wikipedia"},
        {"title": "excellent blog card", "url": "https://radio.example.com/dup", "snippet": "an algorithm", "source": "duckduckgo"},
        {"title": "How Indie Hackers Ship Micro-SaaS", "url": "http://example.com/saas", "snippet": "deduped duplicate", "source": "reddit"},
    ]


def test_web_research_consolidates_sources(monkeypatch, fresh_store):
    monkeypatch.setattr(research, "_run_sources", lambda query: _signals())
    out = web_research("micro saas ideas")
    assert "WEB RESEARCH" in out
    assert out.count("[hacker_news] How Indie Hackers Ship Micro-SaaS") == 1
    assert "[wikipedia]" in out
    assert "[reddit]" not in out  # duplicate dropped by dedupe
    assert "3 signals" in out


def test_web_research_no_results(monkeypatch, fresh_store):
    monkeypatch.setattr(research, "_run_sources", lambda query: [])
    assert "No usable signals" in web_research("nothing here")


def test_record_idea_validates_schema(fresh_store):
    idea = dict(
        title="Micro-SaaS subscription bundle",
        summary="Sell a bundle of small tools for indie hackers",
        category="product",
        revenue_model="recurring",
        source_urls=["http://example.com/saas"],
        signal_strength=0.8,
        required_capital=5000,
        projected_monthly_revenue=1200,
        timeframe_months=6,
    )
    assert "Error: category" in record_idea(**{**idea, "category": "nope"})
    assert "Error: revenue_model" in record_idea(**{**idea, "revenue_model": "nope"})
    assert "Error: signal_strength" in record_idea(**{**idea, "signal_strength": 1.5})
    assert "Error: required_capital" in record_idea(**{**idea, "required_capital": -5})
    assert "timeframe_months must be 1..36" in record_idea(**{**idea, "timeframe_months": 60})
    assert "Error: title" in record_idea(**{**idea, "title": "  "})


def test_record_list_archive_lifecycle(fresh_store):
    out = record_idea(
        title="API reselling market",
        summary="Resell aggregated data APIs to SMBs",
        category="marketplace",
        revenue_model="transactional",
        source_urls=["http://api.notes/a"],
        signal_strength=0.7,
        required_capital=25000,
        projected_monthly_revenue=8000,
        timeframe_months=9,
    )
    assert "IV-001" in out and "assess_idea" in out
    fresh_store.data["ideas"][0]["status"] = "funded"
    fresh_store.save()
    listed = list_ideas()
    assert "IV-001" in listed and "EPI --" in listed
    assert "has been funded" in archive_idea("IV-001")
    fresh_store.data["ideas"][0]["status"] = "proposed"
    fresh_store.save()
    assert "Archived IV-001" in archive_idea("IV-001")
    assert all(i["status"] == "archived" for i in fresh_store.data["ideas"])
    assert "no idea" in archive_idea("IV-999")