"""Tests for the credibility council: independent multi-agent judging + deterministic consensus."""

from langchain_core.messages import AIMessage
from pytest import approx

from src.agents.council import run_council


class StubCouncilLLM:
    """Returns preset JSON verdicts, one per invoke, remembering each prompt."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.replies[len(self.calls) - 1])


def _idea():
    return {
        "id": "IV-001",
        "title": "Micro-SaaS subscription bundle",
        "summary": "Sell a bundle of small tools for indie hackers",
        "category": "product",
        "revenue_model": "recurring",
        "source_urls": ["http://example.com/saas"],
        "signal_strength": 0.8,
        "required_capital": 5000,
        "projected_monthly_revenue": 1200,
        "timeframe_months": 6,
    }


def test_council_all_agree_high_conviction():
    llm = StubCouncilLLM(
        [
            '{"credible": true, "conviction": 5, "kill": false, "notes": "clear demand"}',
            '{"credible": true, "conviction": 4, "kill": false, "notes": "executable"}',
            '{"credible": true, "conviction": 5, "kill": false, "notes": "acceptable risk"}',
        ]
    )
    verdict = run_council(_idea(), llm, size=3)
    assert verdict["agreement"] == 1.0
    assert verdict["hard_kill"] == 0
    assert verdict["avg_conviction"] == approx(14 / 3)
    assert verdict["compound_confidence"] == approx(round(1.0 * (14 / 3 / 5), 4))
    assert len(llm.calls) == 3


def test_council_unparseable_member_defaults_to_veto():
    llm = StubCouncilLLM(
        [
            '{"credible": true, "conviction": 5, "kill": false, "notes": "good market"}',
            "this member returned prose instead of JSON",
            '{"credible": true, "conviction": 4, "kill": false, "notes": "fine"}',
        ]
    )
    verdict = run_council(_idea(), llm, size=3)
    assert verdict["agreement"] == 2 / 3
    assert verdict["hard_kill"] == 1
    assert any("M2" in m["assessor"] and m["kill"] for m in verdict["members"])


def test_council_assigns_distinct_briefs():
    llm = StubCouncilLLM(
        [
            '{"credible": false, "conviction": 1, "kill": true, "notes": "no demand"}',
            '{"credible": false, "conviction": 2, "kill": true, "notes": "bad math"}',
            '{"credible": false, "conviction": 1, "kill": true, "notes": "sunk cost"}',
        ]
    )
    run_council(_idea(), llm, size=3)
    joined = "\n".join(str(m[0].content) for m in llm.calls)
    assert all(brief_token in joined for brief_token in ("market analyst", "operational lead", "risk & compliance"))
    assert joined.count("Your only role:") == 3