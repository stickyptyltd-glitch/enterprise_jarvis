"""Tests for the probability engine: EPI scoring, council vetoes, and the invest/implement pipeline."""

import pytest

from src.tools.builder import reset_generated_registry, set_generated_dir
from src.tools.invest import (
    assess_idea,
    implement_idea,
    invest,
    list_investments,
    update_investment_progress,
)
from src.tools.research import list_ideas, record_idea


def _record(fresh_store, **overrides):
    params = dict(
        title="Micro-SaaS subscription bundle",
        summary="Sell a bundle of small tools for indie hackers",
        category="product",
        revenue_model="recurring",
        source_urls=["http://example.com/saas"],
        signal_strength=0.9,
        required_capital=5000,
        projected_monthly_revenue=3000,
        timeframe_months=3,
    )
    params.update(overrides)
    record_idea(**params)
    return fresh_store.data["ideas"][-1]


@pytest.fixture(autouse=True)
def isolated_generated(tmp_path):
    set_generated_dir(tmp_path)
    reset_generated_registry()
    yield
    reset_generated_registry()
    set_generated_dir(None)


def _credible(size, conviction=5):
    return [
        {"assessor": f"M{i}", "credible": True, "conviction": conviction, "kill": False, "notes": "solid"}
        for i in range(size)
    ]


def test_assess_solo_is_deterministic_without_council(fresh_store, monkeypatch):
    from src.tools import invest as invest_mod

    idea = _record(fresh_store)
    assert idea["id"] == "IV-001"
    first = assess_idea("IV-001")
    second = assess_idea("IV-001")
    assert first == second  # identical inputs -> identical score, no LLM involved
    assert "EPI: 83.2/100" in first
    assert "STRONG BUY" in first and "solo" in first.lower()
    assert fresh_store.data["ideas"][0]["status"] == "vetted"
    assert "IV-001" in list_ideas(status="vetted")


def test_council_veto_caps_epi_and_rejects(fresh_store):
    strong = _record(fresh_store)
    verdict = assess_idea("IV-001", _credible(3))
    assert "EPI: 90.8/100" in verdict  # all agree, full conviction
    assert strong["council"]["agreement"] == 1.0

    bad = _record(fresh_store, title="Doomed pivot", signal_strength=0.9, required_capital=100000, projected_monthly_revenue=100, timeframe_months=24)
    assert bad["id"] == "IV-002"
    veto = assess_idea(
        "IV-002",
        [
            {"credible": False, "conviction": 1, "kill": True, "notes": "no demand"},
            {"credible": True, "conviction": 3, "kill": False, "notes": "maybe"},
            {"credible": True, "conviction": 2, "kill": False, "notes": "weak"},
        ],
    )
    assert "REJECT" in veto and "vetoes 1" in veto
    assert fresh_store.data["ideas"][1]["status"] == "rejected"


def test_invest_enforces_gates(fresh_store):
    _record(fresh_store)
    assert "has not been assessed" in invest("IV-001", 1000)

    assess_idea("IV-001", _credible(3))
    assert "exceeds the plan" in invest("IV-001", 10_000_000)
    assert "insufficient funds" in invest("IV-001", 5000)

    fresh_store.data["company"]["bank_balance"] = 100000
    fresh_store.save()
    out = invest("IV-001", 3000)
    assert "Invested $3,000.00" in out
    assert fresh_store.data["company"]["bank_balance"] == 97000
    assert len(fresh_store.data["investments"]) == 1
    assert fresh_store.data["ideas"][0]["status"] == "funded"
    assert any(e["kind"] == "investment" and e["amount"] == -3000 for e in fresh_store.data["ledger"])
    assert "already funded" in invest("IV-001", 1000)


def test_conditional_requires_explicit_force(fresh_store):
    _record(
        fresh_store,
        title="Borderline venture",
        signal_strength=0.7,
        required_capital=14000,
        projected_monthly_revenue=3000,
        timeframe_months=5,
    )
    verdict = assess_idea("IV-001", _credible(3, conviction=3))
    assert "CONDITIONAL" in verdict
    fresh_store.data["company"]["bank_balance"] = 50000
    fresh_store.save()
    assert "force=True" in invest("IV-001", 14000)
    assert "Invested $14,000.00" in invest("IV-001", 14000, force=True)


def test_implement_turns_vetted_idea_into_operating_system(fresh_store):
    _record(fresh_store)
    assess_idea("IV-001", _credible(2))
    fresh_store.data["company"]["bank_balance"] = 60000
    fresh_store.save()
    invest("IV-001", 5000)

    out = implement_idea("IV-001", description="auto-collection system", execute=True)
    assert "system_iv_001" in out
    assert "implemented" in fresh_store.data["ideas"][0]["status"]
    assert fresh_store.data["ideas"][0]["system_tool"] == "system_iv_001"
    from src.tools.builder import run_generated_tool

    result = run_generated_tool("system_iv_001", '{"note": "sweep 1"}')
    assert "operating system run" in result

    assert "Error" in implement_idea("IV-999")


def test_investment_progress_and_lists(fresh_store):
    assert "No investments deployed" in list_investments()
    _record(fresh_store)
    assess_idea("IV-001", _credible(2))
    fresh_store.data["company"]["bank_balance"] = 60000
    fresh_store.save()
    invest("IV-001", 5000)
    assert "IS-001" in list_investments()
    assert "Error: status" in update_investment_progress("IS-001", "note", status="forged")
    assert "active -> matured" in update_investment_progress("IS-001", "revenue doubling", status="matured")
    assert len(fresh_store.data["investments"][0]["notes"]) == 1
    assert "IS-001" in list_investments(status="matured")