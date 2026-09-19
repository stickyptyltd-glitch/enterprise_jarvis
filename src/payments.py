"""Real-money rail for JARVIS.

Modes (``JARVIS_REAL_MONEY``):

* ``simulate`` (default) — payments are previewed but nothing touches a wallet
  or the ledger; the whole stack stays offline-testable.
* ``real`` — outbound moves are capped by the burn-wallet limit
  (``JARVIS_REAL_SPEND_CAP``, ``0`` = no cap) and executed through the
  configured providers; inbound collections go through the billing provider.

Providers are adapter functions behind one facade, and all HTTP goes through
the ``_http_*`` seams so tests can stub the network. Nothing here is invoked
unless the relevant provider is configured.
"""

import os
import time

from src.tools.base import STORE

MODE_SIMULATE = "simulate"
MODE_REAL = "real"
MODE_OFF = "off"
VALID_MODES = (MODE_SIMULATE, MODE_REAL, MODE_OFF)


def resolve_mode() -> str:
    raw = os.getenv("JARVIS_REAL_MONEY", MODE_SIMULATE).strip().lower()
    return raw if raw in VALID_MODES else MODE_SIMULATE


def is_real() -> bool:
    return resolve_mode() == MODE_REAL


def spend_cap() -> float:
    try:
        return max(0.0, float(os.getenv("JARVIS_REAL_SPEND_CAP", "0")))
    except (TypeError, ValueError):
        return 0.0


def providers() -> list[str]:
    found = []
    if os.getenv("STRIPE_SECRET_KEY"):
        found.append("stripe")
    if os.getenv("WISE_API_TOKEN") and os.getenv("WISE_PROFILE_ID"):
        found.append("wise")
    if os.getenv("PLAID_ACCESS_TOKEN"):
        found.append("plaid")
    return found


def burn_wallet(amount: float, label: str) -> str | None:
    """Return an error message when a real outbound move exceeds the burn-wallet cap."""
    if not is_real():
        return None
    cap = spend_cap()
    if cap and amount > cap:
        active = ", ".join(providers()) or "no provider configured"
        return (
            f"Error: real-money {label} of {STORE.currency(amount)} exceeds the burn-wallet "
            f"cap of {STORE.currency(cap)} ({active}). Nothing moved."
        )
    return None


def _http_post(url: str, **kwargs):
    import requests

    return requests.post(url, **kwargs)


def _http_get(url: str, **kwargs):
    import requests

    return requests.get(url, **kwargs)


def _sim_ref(prefix: str) -> str:
    return f"sim_{prefix}_{int(time.time()):x}"


def charge_customer(amount: float, description: str = "") -> dict:
    """Charge a customer card (Stripe PaymentIntent). Money flows in."""
    if not is_real():
        return {"mode": MODE_SIMULATE, "ok": True, "ref": _sim_ref("pi"), "amount": amount}
    if "stripe" not in providers():
        return {"mode": MODE_REAL, "ok": False, "error": "stripe not configured (STRIPE_SECRET_KEY)"}
    try:
        resp = _http_post(
            "https://api.stripe.com/v1/payment_intents",
            auth=(os.getenv("STRIPE_SECRET_KEY", ""), ""),
            data={
                "amount": int(round(amount * 100)),
                "currency": "usd",
                "description": description[:250],
            },
            timeout=15,
        )
    except Exception as exc:
        return {"mode": MODE_REAL, "ok": False, "error": f"stripe request failed ({type(exc).__name__})"}
    if resp.status_code != 200:
        return {"mode": MODE_REAL, "ok": False, "error": f"stripe HTTP {resp.status_code}"}
    data = resp.json()
    return {"mode": MODE_REAL, "ok": True, "ref": data.get("id", "pi_unknown"), "status": data.get("status")}


def pay_recipient(amount: float, recipient: str = "") -> dict:
    """Pay a counterparty (Wise outgoing transfer). Money flows out."""
    if not is_real():
        return {"mode": MODE_SIMULATE, "ok": True, "ref": _sim_ref("tx"), "amount": amount}
    if "wise" not in providers():
        return {"mode": MODE_REAL, "ok": False, "error": "wise not configured (WISE_API_TOKEN + WISE_PROFILE_ID)"}
    try:
        resp = _http_post(
            "https://api.transferwise.com/v1/transfers",
            headers={"Authorization": f"Bearer {os.getenv('WISE_API_TOKEN', '')}"},
            json={
                "targetAccount": recipient,
                "sourceCurrency": "USD",
                "targetCurrency": "USD",
                "targetAmount": round(amount, 2),
                "maxFee": 0,
            },
            timeout=15,
        )
    except Exception as exc:
        return {"mode": MODE_REAL, "ok": False, "error": f"wise request failed ({type(exc).__name__})"}
    if resp.status_code > 201:
        return {"mode": MODE_REAL, "ok": False, "error": f"wise HTTP {resp.status_code}"}
    data = resp.json()
    return {"mode": MODE_REAL, "ok": True, "ref": data.get("id", "tx_unknown")}


def fetch_balance() -> dict:
    """Pull the live treasury balance from the linked account (Plaid)."""
    if not is_real():
        return {"mode": MODE_SIMULATE, "ok": True, "amount": None, "note": "preview only — set JARVIS_REAL_MONEY=real"}
    if "plaid" not in providers():
        return {"mode": MODE_REAL, "ok": False, "error": "plaid not configured (PLAID_ACCESS_TOKEN)"}
    try:
        resp = _http_post(
            "https://sandbox.plaid.com/accounts/balance/get",
            json={
                "client_id": os.getenv("PLAID_CLIENT_ID", ""),
                "secret": os.getenv("PLAID_SECRET", ""),
                "access_token": os.getenv("PLAID_ACCESS_TOKEN", ""),
            },
            timeout=15,
        )
    except Exception as exc:
        return {"mode": MODE_REAL, "ok": False, "error": f"plaid request failed ({type(exc).__name__})"}
    if resp.status_code != 200:
        return {"mode": MODE_REAL, "ok": False, "error": f"plaid HTTP {resp.status_code}"}
    data = resp.json()
    try:
        amount = float(data["accounts"][0]["balances"]["available"])
    except (KeyError, IndexError, TypeError, ValueError):
        return {"mode": MODE_REAL, "ok": False, "error": "plaid: no available balance in response"}
    return {"mode": MODE_REAL, "ok": True, "amount": amount}