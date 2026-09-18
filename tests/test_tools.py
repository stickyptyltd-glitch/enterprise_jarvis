"""Unit tests for the business tools and the store they mutate."""

from src.tools import (
    CRITICAL_TOOLS,
    DOMAIN_TOOLS,
    approve_expense,
    check_balance,
    collect_invoice,
    list_invoices,
    pay_invoice,
    receive_funds,
    transfer_funds,
)
from src.tools.human_resources import give_raise, hire_employee, terminate_employee
from src.tools.crm import add_lead, update_lead_stage
from src.tools.operations import assign_task, create_task, update_progress


def _balance(store):
    return store.data["company"]["bank_balance"]


def test_finance_balance_and_transfer(fresh_store):
    assert "0.00" in check_balance()
    assert "insufficient" in transfer_funds(5000, "ACME").lower()
    assert _balance(fresh_store) == 0
    fresh_store.data["company"]["bank_balance"] = 245000
    fresh_store.save()
    result = transfer_funds(5000, "ACME")
    assert "transferred $5,000.00" in result
    assert _balance(fresh_store) == 240000
    assert fresh_store.data["notifications"]


def test_transfer_rejects_insufficient_funds(fresh_store):
    result = transfer_funds(10_000_000, "ACME")
    assert "insufficient" in result.lower()
    assert _balance(fresh_store) == 0


def test_pay_invoice_and_approve_expense(fresh_store):
    assert "paid" in pay_invoice("INV-1001").lower()
    assert list_invoices().count("paid") >= 2
    assert "approved" in approve_expense("X-5001").lower()


def test_receive_funds_and_collect_invoice(fresh_store):
    assert "insufficient" in transfer_funds(1000, "ACME").lower()
    received = receive_funds(50000, "Northwind Traders", "contract milestone")
    assert "Received $50,000.00" in received
    assert _balance(fresh_store) == 50000
    assert "must be positive" in receive_funds(-100, "x") and "must be positive" in receive_funds(0, "x")

    fresh_store.data["invoices"][0]["amount"] = 40000
    fresh_store.save()
    collected = collect_invoice("INV-1001")
    assert "Collected invoice INV-1001" in collected
    assert _balance(fresh_store) == 90000 and fresh_store.data["invoices"][0]["status"] == "paid"
    assert "already paid" in collect_invoice("INV-1001")
    assert "not found" in collect_invoice("INV-9999")

    kinds = [e["kind"] for e in fresh_store.data["ledger"]]
    assert "deposit" in kinds and "receipt" in kinds


def test_hr_raise_hire_terminate(fresh_store):
    result = give_raise("E-001", 10000)
    assert "$10,000" in result
    hire = hire_employee("Staff Engineer", 120000)
    assert "Created employee E-105" in hire
    assert "terminated" in terminate_employee("E-002").lower()
    assert fresh_store.data["employees"][1]["status"] == "terminated"


def test_crm_add_and_advance_lead(fresh_store):
    assert "Logged lead L-04" in add_lead("Umbrella Corp", "Alice", 30000)
    result = update_lead_stage("L-04", "qualified")
    assert result.startswith("Moved lead L-04 to")
    assert fresh_store.data["leads"][-1]["stage"] == "qualified"


def test_ops_tasks(fresh_store):
    created = create_task("P-01", "Write migration docs")
    assert created.startswith("Created task T-")
    assert "assigned" in assign_task("T-303", "E-003").lower()
    assert "now 'done'" in update_progress("T-302", "done")


def test_critical_tools_registered():
    expected = {
        "transfer_funds",
        "pay_invoice",
        "approve_expense",
        "give_raise",
        "hire_employee",
        "approve_pto",
        "terminate_employee",
        "close_opportunity",
        "generate_tool",
    }
    assert expected <= CRITICAL_TOOLS


def test_all_domains_exposed():
    assert set(DOMAIN_TOOLS) == {
        "finance",
        "hr",
        "crm",
        "ops",
        "analytics",
        "comms",
        "leadership",
        "research",
        "invest",
        "watch",
        "builder",
        "generated",
        "decide",
    }
    assert len([t for tools in DOMAIN_TOOLS.values() for t in tools]) >= 55