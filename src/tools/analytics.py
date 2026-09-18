"""Analytics and reporting domain tools (read-only)."""

from src.tools.base import STORE


def revenue_report() -> str:
    """Produce a monthly revenue report for the trailing periods on record."""
    lines = "\n".join(f"  - {r['period']}: {STORE.currency(r['amount'])}" for r in STORE.data["revenue"])
    total = sum(r["amount"] for r in STORE.data["revenue"])
    return f"Revenue report:\n{lines}\nTotal: {STORE.currency(total)}"


def expense_report() -> str:
    """Produce a categorised expense summary."""
    by_cat: dict[str, float] = {}
    for exp in STORE.data["expenses"]:
        by_cat[exp["category"]] = by_cat.get(exp["category"], 0.0) + exp["amount"]
    lines = "\n".join(f"  - {cat}: {STORE.currency(amt)}" for cat, amt in sorted(by_cat.items()))
    total = sum(by_cat.values())
    return f"Expense report:\n{lines}\nTotal: {STORE.currency(total)}"


def kpi_dashboard() -> str:
    """Assemble a KPI dashboard from the core business metrics."""
    data = STORE.data
    revenue_total = sum(r["amount"] for r in data["revenue"])
    open_value = sum(op["amount"] * op["probability"] for op in data["opportunities"])
    active_emps = sum(1 for e in data["employees"] if e["status"] == "active")
    open_inv = sum(i["amount"] for i in data["invoices"] if i["status"] in ("open", "overdue"))
    return (
        "KPI Dashboard:\n"
        f"  - Cash balance: {STORE.currency(data['company']['bank_balance'])}\n"
        f"  - Revenue (trailing): {STORE.currency(revenue_total)}\n"
        f"  - Open receivables: {STORE.currency(open_inv)}\n"
        f"  - Open opportunities (weighted): {STORE.currency(open_value)}\n"
        f"  - Active employees: {active_emps}\n"
        f"  - Active projects: {len([p for p in data['projects'] if (p['budget'] - p['spent']) > 0])}"
    )