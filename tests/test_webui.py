"""Tests for the web dashboard: state projection and the HTTP layer."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src.config.settings import Settings
from src.webui import Handler, state_snapshot


def _seed() -> dict:
    return {
        "company": {"name": "Acme Industries", "currency": "USD", "bank_balance": 18075.0},
        "invoices": [
            {"id": "INV-1001", "client": "Northwind Traders", "amount": 1200.0, "status": "paid", "due": "2026-10-01"},
            {"id": "INV-1002", "client": "Globex", "amount": 500.0, "status": "open", "due": "2026-10-05"},
            {"id": "INV-1003", "client": "Initech", "amount": 900.0, "status": "overdue", "due": "2026-09-01"},
        ],
        "employees": [
            {"name": "A", "salary": 1000.0, "status": "active"},
            {"name": "B", "salary": 0.0, "status": "inactive"},
        ],
        "opportunities": [{"amount": 2000.0, "probability": 0.5}],
        "projects": [{"budget": 1000.0, "spent": 300.0}, {"budget": 0.0, "spent": 0.0}],
        "ideas": [
            {"id": "IV-002", "title": "Later", "category": "automation", "revenue_model": "recurring", "status": "proposed", "assessment": {}, "required_capital": 1000},
            {"id": "IV-001", "title": "SaaS", "category": "automation", "revenue_model": "recurring", "status": "implemented", "assessment": {"epi": 83.0}, "required_capital": 7500},
        ],
        "investments": [
            {"id": "IS-001", "idea_id": "IV-001", "amount": 7500.0, "status": "active", "breakeven_months": 2.2, "at": "2026-09-19T04:42", "notes": [], "epi_at_funding": 83.0},
            {"id": "IS-002", "idea_id": "IV-001", "amount": 5625.0, "status": "matured", "breakeven_months": 1.0, "at": "2026-09-19T05:00", "notes": [{"note": "x"}], "epi_at_funding": 78.1},
        ],
        "ledger": [
            {"at": "2026-09-19T04:40", "type": "deposit", "amount": 30000.0, "ref": "opening seed"},
            {"at": "2026-09-19T04:42", "type": "investment", "amount": -7500.0, "ref": "IS-001"},
        ],
        "notifications": [{"at": "2026-09-19T05:00", "message": "ok"}],
        "funding_gate": {"paused": False, "at": "2026-09-19T05:01", "reason": "risk cleared"},
    }


def test_snapshot_projects_core_state():
    snap = state_snapshot(_seed(), Settings(real_money="real", real_spend_cap=100))
    assert snap["company"]["balance"] == 18075.0
    assert snap["company"]["name"] == "Acme Industries"
    assert snap["payments"]["mode"] == "real"
    assert snap["payments"]["cap"] == 100
    assert snap["payments"]["spend_cap_enforced"] is True
    assert snap["gate"] == {"paused": False, "at": "2026-09-19T05:01", "reason": "risk cleared"}
    assert snap["metrics"]["open_receivables"] == 1400.0
    assert snap["metrics"]["overdue_invoice_count"] == 1
    assert snap["metrics"]["weighted_pipeline"] == 1000.0
    assert snap["metrics"]["monthly_payroll"] == 1000.0
    assert snap["metrics"]["active_employees"] == 1
    assert snap["metrics"]["active_projects"] == 1
    assert snap["metrics"]["portfolio_deployed"] == 7500.0
    assert snap["metrics"]["active_investments"] == 1
    assert snap["metrics"]["investments_matured"] == 1
    assert snap["metrics"]["investments_written_off"] == 0
    assert len(snap["ledger"]) == 2
    assert snap["ideas"][0]["id"] == "IV-001"
    assert snap["ideas"][0]["epi"] == pytest.approx(83.0)
    assert snap["ideas"][1]["id"] == "IV-002"
    assert snap["ideas"][1]["epi"] is None
    assert snap["investments"][0]["status"] == "active"
    assert snap["investments"][1]["progress"] == 1
    assert any(j["name"] == "opportunities" for j in snap["schedule"]["jobs"])
    assert snap["schedule"]["interval"] == 30
    assert isinstance(snap["domains"], list)


def test_snapshot_providers_from_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_x")
    snap = state_snapshot(_seed(), Settings(real_money="real", real_spend_cap=0))
    assert "stripe" in snap["payments"]["providers"]
    assert snap["payments"]["spend_cap_enforced"] is False


@pytest.fixture()
def server(monkeypatch):
    from src.webui import live_state, run_query  # noqa: F401

    monkeypatch.setattr(
        "src.webui.live_state",
        lambda: state_snapshot(_seed(), Settings(real_money="simulate")),
    )
    monkeypatch.setattr(
        "src.webui.run_query",
        lambda q: {"reply": f"ok: {q}", "approval_required": False},
    )
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base
    srv.shutdown()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as resp:
        return resp.status, json.load(resp)


def test_http_state_endpoint(server):
    _, data = _get(server, "/api/state")
    assert data["company"]["balance"] == 18075.0
    assert data["payments"]["mode"] == "simulate"


def test_http_ask_endpoint(server):
    req = urllib.request.Request(
        server + "/api/ask",
        data=json.dumps({"query": "status"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert json.load(resp)["reply"] == "ok: status"


def test_http_ask_requires_query(server):
    req = urllib.request.Request(
        server + "/api/ask",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)
    assert err.value.code == 400


def test_http_unknown_route_404(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(server + "/nope", timeout=5)
    assert err.value.code == 404