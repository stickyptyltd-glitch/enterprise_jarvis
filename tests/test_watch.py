"""Tests for the watchdog standing-monitor tools."""

from datetime import datetime, timedelta

from src.tools.watch import (
    WATCHDOG_METRICS,
    check_watchdogs,
    create_watchdog,
    delete_watchdog,
    list_watchdogs,
    pause_watchdog,
    resume_watchdog,
    watchdog_metrics,
)


def test_create_and_list_watchdog(fresh_store):
    result = create_watchdog("bank_balance", "<", 200000, "flag low cash")
    assert "WD-1 armed" in result and "bank_balance < 200000" in result
    listing = list_watchdogs()
    assert "WD-1" in listing and "active" in listing and "last fired: never" in listing
    assert fresh_store.data["watchdogs"][0]["active"] is True


def test_invalid_metric_or_operator(fresh_store):
    assert "unknown metric" in create_watchdog("moon_phases", ">", 1)
    assert "unknown operator" in create_watchdog("bank_balance", "~", 1)
    assert "threshold must be a number" in create_watchdog("bank_balance", "<", "low")


def test_watchdog_fires_when_tripped(fresh_store):
    create_watchdog("bank_balance", "<", 250000)
    before = len(fresh_store.data["notifications"])
    result = check_watchdogs()
    assert "ALERT: WATCHDOG WD-1 tripped" in result
    assert "current 0" in result
    assert len(fresh_store.data["notifications"]) == before + 1
    assert fresh_store.data["watchdogs"][0]["last_fired"] is not None


def test_watchdog_cooldown_suppresses_repeat(fresh_store):
    create_watchdog("bank_balance", "<", 250000)
    check_watchdogs()
    before = len(fresh_store.data["notifications"])
    result = check_watchdogs()
    assert "Suppressed (cooldown)" in result
    assert len(fresh_store.data["notifications"]) == before


def test_pause_resume_delete_skips_inactive(fresh_store):
    create_watchdog("overdue_invoice_count", ">", 0)
    assert "Paused WD-1" in pause_watchdog("WD-1")
    assert "No active watchdog is currently tripping" in check_watchdogs()
    assert "Resumed WD-1" in resume_watchdog("WD-1")
    assert "ALERT" in check_watchdogs()
    assert "Deleted WD-1" in delete_watchdog("WD-1")
    assert fresh_store.data["watchdogs"] == []


def test_counts_metrics_and_info(fresh_store):
    assert "active_employees" in watchdog_metrics()
    assert "weighted_pipeline" in watchdog_metrics()
    create_watchdog("active_employees", ">=", 1)
    create_watchdog("monthly_payroll", ">=", 0)
    result = check_watchdogs()
    assert result.count("ALERT") == 2
    create_watchdog("weighted_pipeline", ">", 1000000)
    assert "No active watchdog is currently tripping" not in check_watchdogs()


def test_portfolio_watchdog_metrics(fresh_store):
    days = lambda n: (datetime.now() - timedelta(days=n)).isoformat(timespec="minutes")
    fresh_store.data["investments"] = [
        {"id": "IS-001", "idea_id": "IV-001", "at": days(400), "amount": 5000, "status": "active", "breakeven_months": 3, "notes": []},
        {"id": "IS-002", "idea_id": "IV-002", "at": days(10), "amount": 5000, "status": "active", "breakeven_months": 12, "notes": [{"note": "on track"}]},
        {"id": "IS-003", "idea_id": "IV-003", "at": days(200), "amount": 2000, "status": "written_off", "breakeven_months": 6, "notes": []},
    ]
    fresh_store.save()
    assert WATCHDOG_METRICS["portfolio_deployed"](fresh_store.data) == 10000
    assert WATCHDOG_METRICS["active_investments"](fresh_store.data) == 2
    assert WATCHDOG_METRICS["investments_at_risk"](fresh_store.data) == 1
    assert WATCHDOG_METRICS["investments_written_off"](fresh_store.data) == 1
    create_watchdog("portfolio_deployed", ">=", 5000)
    result = check_watchdogs()
    assert "ALERT: WATCHDOG WD-1 tripped" in result
    assert "current 10,000" in result