"""Tests for the probability engine: EPI scoring, council vetoes, and the invest/implement pipeline."""

from datetime import datetime, timedelta

import pytest

from src.tools.builder import reset_generated_registry, set_generated_dir
from src.tools.invest import (
    assess_idea,
    cash_out,
    funding_gate_status,
    implement_idea,
    invest,
    list_investments,
    pause_funding,
    resume_funding,
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


def test_absolute_investment_cap(monkeypatch, fresh_store):
    monkeypatch.setenv("JARVIS_MAX_INVESTMENT_AMOUNT", "2000")
    _record(fresh_store)
    assess_idea("IV-001", _credible(3))
    fresh_store.data["company"]["bank_balance"] = 100000
    fresh_store.save()
    assert "per-idea cap" in invest("IV-001", 3000)
    assert "Invested $2,000.00" in invest("IV-001", 2000)


def test_portfolio_review_job_reports_at_risk(fresh_store):
    days = lambda n: (datetime.now() - timedelta(days=n)).isoformat(timespec="minutes")
    fresh_store.data["investments"] = [
        {"id": "IS-001", "idea_id": "IV-001", "at": days(400), "amount": 5000, "status": "active", "breakeven_months": 3, "notes": []},
        {"id": "IS-002", "idea_id": "IV-002", "at": days(10), "amount": 5000, "status": "active", "breakeven_months": 12, "notes": [{"note": "tracked"}]},
    ]
    fresh_store.save()
    from src.cron import job_portfolio_review

    report = job_portfolio_review()
    assert "PORTFOLIO REVIEW" in report
    assert "$10,000.00 USD deployed across 2 active" in report
    assert "at risk 1" in report
    assert fresh_store.data["notifications"][-1]["message"].startswith("PORTFOLIO REVIEW")


def _funded(fresh_store, bank=100000):
    _record(fresh_store)
    assess_idea("IV-001", _credible(3))
    fresh_store.data["company"]["bank_balance"] = bank
    fresh_store.save()
    invest("IV-001", 5000)
    return fresh_store.data["investments"][-1]


def test_cash_out_returns_funds_to_treasury(fresh_store):
    record = _funded(fresh_store)
    assert record["status"] == "active"
    out = cash_out("IS-001", 9000, "wound down profitably")
    assert "cashed out" in out
    assert "$9,000.00" in out
    assert fresh_store.data["company"]["bank_balance"] == 104000
    record = fresh_store.data["investments"][0]
    assert record["status"] == "cashed_out"
    assert record["net_profit"] == 4000
    assert any(e["kind"] == "return" and e["amount"] == 9000 for e in fresh_store.data["ledger"])


def test_cash_out_validates(fresh_store):
    record = _funded(fresh_store)
    cash_out("IS-001", 1000)
    assert "cannot be cashed out" in cash_out("IS-001", 1000)  # already closed
    assert "no investment 'IS-999'" in cash_out("IS-999", 1000)
    assert "cannot be negative" in cash_out("IS-002", -5)
    assert "must be a number" in cash_out("IS-002", "lots")


def test_cash_out_books_loss_when_income_is_short(fresh_store):
    _funded(fresh_store)
    out = cash_out("IS-001", 3000)
    assert "net loss $2,000.00" in out
    assert fresh_store.data["investments"][0]["net_profit"] == -2000


def test_funding_gate_tools(fresh_store):
    assert "OPEN" in funding_gate_status()
    assert "PAUSED" in pause_funding("testing the leash").upper()
    assert "PAUSED" in funding_gate_status().upper()
    assert fresh_store.data["funding_gate"]["paused"] is True
    resume_funding()
    assert "OPEN" in funding_gate_status()
    assert fresh_store.data["funding_gate"]["paused"] is False


def test_opportunity_loop_respects_exposure_limit(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_AUTONOMY", "full")
    monkeypatch.setenv("JARVIS_EXPOSURE_LIMIT", "1")
    _record(fresh_store)
    assess_idea("IV-001", _credible(3))  # already vetted: loop needs no LLM
    fresh_store.data["company"]["bank_balance"] = 100000
    days = lambda n: (datetime.now() - timedelta(days=n)).isoformat(timespec="minutes")
    fresh_store.data["investments"] = [
        {"id": "IS-001", "idea_id": "IV-X", "at": days(400), "amount": 1000, "status": "active", "breakeven_months": 3, "notes": []},
        {"id": "IS-002", "idea_id": "IV-Y", "at": days(400), "amount": 1000, "status": "active", "breakeven_months": 3, "notes": []},
    ]
    fresh_store.save()
    from src.cron import job_opportunity_loop

    out1 = job_opportunity_loop()
    assert "AUTO-PAUSED" in out1
    assert fresh_store.data["funding_gate"]["paused"] is True
    assert len(fresh_store.data["investments"]) == 2  # gate blocked any new funding

    cash_out("IS-001", 1200)
    cash_out("IS-002", 1200)  # risk cleared
    out2 = job_opportunity_loop()
    assert "gate" in out2.lower() and "reopen" in out2.lower()
    assert "IV-001" in out2 and "Invested" in out2
    assert len(fresh_store.data["investments"]) == 3  # IS-003 now deployed


def test_portfolio_review_auto_matures(fresh_store):
    days = lambda n: (datetime.now() - timedelta(days=n)).isoformat(timespec="minutes")
    fresh_store.data["investments"] = [
        {"id": "IS-001", "idea_id": "IV-999", "at": days(400), "amount": 5000, "status": "active", "breakeven_months": 3, "notes": []},
        {"id": "IS-002", "idea_id": "IV-998", "at": days(10), "amount": 5000, "status": "active", "breakeven_months": 12, "notes": []},
    ]
    fresh_store.save()
    from src.cron import job_portfolio_review

    report = job_portfolio_review()
    assert "auto-matured" in report.lower() or "matured 1" in report
    assert fresh_store.data["investments"][0]["status"] == "matured"
    assert fresh_store.data["investments"][1]["status"] == "active"
    assert "auto-matured" in fresh_store.data["notifications"][-1]["message"].lower()


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