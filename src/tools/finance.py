"""Finance domain tools: treasury visibility plus high-risk money movement."""

from src.tools.base import STORE, register_critical


def check_balance() -> str:
    """Check the company's current operating bank balance."""
    company = STORE.data["company"]
    return f"Current cash reserve: {STORE.currency(company['bank_balance'])} at {company['name']}."


def get_cash_flow() -> str:
    """Summarise recent revenue and outstanding receivables (cash flow outlook)."""
    data = STORE.data
    revenue = sum(r["amount"] for r in data["revenue"])
    open_invoices = [inv for inv in data["invoices"] if inv["status"] in ("open", "overdue")]
    receivable = sum(inv["amount"] for inv in open_invoices)
    lines = (f"  - {inv['id']} {inv['client']}: {STORE.currency(inv['amount'])} ({inv['status']})" for inv in open_invoices)
    return (
        f"Cash flow snapshot: revenue YTD {STORE.currency(revenue)}; "
        f"outstanding receivables {STORE.currency(receivable)} across {len(open_invoices)} open invoices:\n"
        + "\n".join(lines)
    )


def list_invoices() -> str:
    """List all invoices with their client, amount, due date, and payment status."""
    text = "\n".join(
        f"  - {inv['id']} | {inv['client']} | {STORE.currency(inv['amount'])} | due {inv['due']} | {inv['status']}"
        for inv in STORE.data["invoices"]
    )
    return f"Invoices ({len(STORE.data['invoices'])}):\n{text}"


def list_expenses() -> str:
    """List expense reports and their approval status."""
    text = "\n".join(
        f"  - {exp['id']} | {exp['category']} | {STORE.currency(exp['amount'])} | {exp['status']}"
        for exp in STORE.data["expenses"]
    )
    return f"Expense reports ({len(STORE.data['expenses'])}):\n{text}"


def transfer_funds(amount: float, recipient: str) -> str:
    """Transfer funds out of the company bank account to a vendor or counterparty. High-risk action requiring HITL approval."""
    company = STORE.data["company"]
    if amount <= 0:
        return "Error: transfer amount must be positive."
    if amount > company["bank_balance"]:
        return f"Error: insufficient funds (balance {STORE.currency(company['bank_balance'])})."
    company["bank_balance"] -= amount
    ledger = "[outbound]"
    STORE.data.setdefault("ledger", []).append(
        {"at": STORE.timestamp(), "kind": "payment", "id": f"TX-{len(STORE.data.get('ledger', [])) + 1}", "counterparty": recipient, "amount": -amount, "note": ledger}
    )
    STORE.notify(f"Wire transfer of {STORE.currency(amount)} to {recipient} executed.")
    STORE.save()
    return f"Successfully transferred {STORE.currency(amount)} to {recipient}. New balance: {STORE.currency(company['bank_balance'])}."


def pay_invoice(invoice_id: str) -> str:
    """Pay an outstanding invoice from the corporate account. High-risk action requiring HITL approval."""
    invoices = STORE.data["invoices"]
    for inv in invoices:
        if inv["id"].upper() == invoice_id.upper():
            if inv["status"] == "paid":
                return f"Invoice {inv['id']} is already paid."
            company = STORE.data["company"]
            if inv["amount"] > company["bank_balance"]:
                return f"Error: insufficient funds for invoice {inv['id']}."
            company["bank_balance"] -= inv["amount"]
            inv["status"] = "paid"
            STORE.notify(f"Invoice {inv['id']} paid to {inv['client']} for {STORE.currency(inv['amount'])}.")
            STORE.save()
            return f"Paid invoice {inv['id']} ({inv['client']}) for {STORE.currency(inv['amount'])}. New balance: {STORE.currency(company['bank_balance'])}."
    return f"Error: invoice {invoice_id} not found."


def approve_expense(expense_id: str) -> str:
    """Approve an expense report for reimbursement. High-risk action requiring HITL approval."""
    for exp in STORE.data["expenses"]:
        if exp["id"].upper() == expense_id.upper():
            if exp["status"] == "approved":
                return f"Expense {exp['id']} is already approved."
            exp["status"] = "approved"
            STORE.notify(f"Expense {exp['id']} ({exp['category']}) approved for {STORE.currency(exp['amount'])}.")
            STORE.save()
            return f"Approved expense {exp['id']}: {exp['category']} {STORE.currency(exp['amount'])}."
    return f"Error: expense {expense_id} not found."


register_critical("transfer_funds", "pay_invoice", "approve_expense")