"""Payments domain tools: inspect the rail and move money through providers."""

from src import payments
from src.payments import charge_customer as _charge
from src.payments import fetch_balance
from src.payments import pay_recipient as _payout
from src.tools.base import STORE


def payment_status() -> str:
    """Show which payment mode and providers are active, and the burn-wallet cap."""
    mode = payments.resolve_mode()
    cap = payments.spend_cap()
    found = payments.providers()
    cap_text = STORE.currency(cap) if cap else "no cap (0)"
    return (
        f"Payments mode: {mode}\n"
        f"  burn-wallet cap: {cap_text}\n"
        f"  providers enabled: {', '.join(found) or 'none — simulate-mode previews only'}"
    )


def real_balance() -> str:
    """Read the live treasury balance from the linked account (Plaid)."""
    result = fetch_balance()
    if not result["ok"]:
        return f"Error: {result.get('error', 'balance unavailable')}"
    if result.get("amount") is None:
        return (
            f"Real balance: preview only — set JARVIS_REAL_MONEY=real with PLAID_ACCESS_TOKEN. "
            f"Local ledger shows {STORE.currency(STORE.data['company']['bank_balance'])}."
        )
    return f"Real balance: {STORE.currency(result['amount'])} (live, from Plaid)."


def sync_real_balance() -> str:
    """Pull the live balance and reconcile it into the treasury ledger."""
    company = STORE.data["company"]
    result = fetch_balance()
    if not result["ok"]:
        return f"Error: {result.get('error', 'balance unavailable')}"
    if result.get("amount") is None:
        return real_balance()
    previous = company["bank_balance"]
    if previous == result["amount"]:
        return f"Reconciled: live balance matches ledger ({STORE.currency(previous)})."
    company["bank_balance"] = result["amount"]
    STORE.data.setdefault("ledger", []).append(
        {
            "at": STORE.timestamp(),
            "kind": "reconcile",
            "id": f"RC-{len(STORE.data.get('ledger', [])) + 1}",
            "counterparty": "plaid",
            "amount": round(result["amount"] - previous, 2),
            "note": "live balance reconciliation",
        }
    )
    STORE.notify(f"Treasury reconciled with live rail: {STORE.currency(previous)} -> {STORE.currency(result['amount'])}.")
    STORE.save()
    return f"Reconciled treasury with live balance: {STORE.currency(previous)} -> {STORE.currency(result['amount'])}."


def charge_customer(amount: float, description: str = "") -> str:
    """Charge a customer's card for a product or service (money in, via Stripe)."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Error: amount must be a number."
    if amount <= 0:
        return "Error: charge amount must be positive."
    result = _charge(amount, description)
    if not result["ok"]:
        return f"Error: {result.get('error', 'charge failed')}"
    if result["mode"] == payments.MODE_SIMULATE:
        return f"[simulate] would charge {STORE.currency(amount)} ({description or 'sale'}) — {result['ref']}"
    status = result.get("status", "")
    suffix = f" status {status}" if status else ""
    return f"Charged {STORE.currency(amount)} ({description or 'sale'}) — ref {result['ref']}{suffix}"


def payout(amount: float, recipient: str) -> str:
    """Send money to a counterparty via Wise (outbound; hard-capped in real mode)."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Error: amount must be a number."
    if amount <= 0:
        return "Error: payout amount must be positive."
    blocked = payments.burn_wallet(amount, "payout")
    if blocked:
        return blocked
    result = _payout(amount, recipient)
    if not result["ok"]:
        return f"Error: {result.get('error', 'payout failed')}"
    if result["mode"] == payments.MODE_SIMULATE:
        return f"[simulate] would pay {STORE.currency(amount)} to {recipient} — {result['ref']}"
    return f"Paid {STORE.currency(amount)} to {recipient} — ref {result['ref']}"