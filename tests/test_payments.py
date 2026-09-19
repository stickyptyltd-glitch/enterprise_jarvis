"""Tests for the payments rail: simulate-by-default, burn-wallet cap, provider routing."""


class Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _invoice(store, invoice_id="INV-1001", amount=2500.0, client="Northwind Traders"):
    inv = next(i for i in store.data["invoices"] if i["id"] == invoice_id)
    inv["amount"] = amount
    inv["status"] = "open"
    inv["client"] = client
    store.save()
    return inv


def test_simulate_mode_is_default_and_only_previews(fresh_store):
    from src.tools.payments import charge_customer, payout, payment_status, sync_real_balance

    status = payment_status()
    assert "simulate" in status
    assert "no cap" in status
    out = charge_customer(500, "widget")
    assert "[simulate]" in out and "$500.00" in out and "sim_pi_" in out
    out = payout(500, "vendor")
    assert "[simulate]" in out and "sim_tx_" in out
    before = fresh_store.data["company"]["bank_balance"]
    sync_real_balance()
    assert fresh_store.data["company"]["bank_balance"] == before
    assert not any(e["kind"] == "reconcile" for e in fresh_store.data.get("ledger", []))


def test_burn_wallet_cap_blocks_real_outbound(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("JARVIS_REAL_SPEND_CAP", "100")
    from src.tools.invest import assess_idea, invest
    from src.tools.payments import payout
    from src.tools.research import record_idea

    fresh_store.data["company"]["bank_balance"] = 5000
    fresh_store.save()
    assert "burn-wallet cap" in payout(500, "vendor")
    record_idea(
        title="T",
        summary="S",
        category="product",
        revenue_model="recurring",
        source_urls=["http://x"],
        signal_strength=0.9,
        required_capital=2000,
        projected_monthly_revenue=1000,
        timeframe_months=3,
    )
    assess_idea("IV-001")
    assert "burn-wallet cap" in invest("IV-001", 2000)
    assert len(fresh_store.data["investments"]) == 0


def test_burn_wallet_cap_ignored_in_simulate_mode(fresh_store):
    from src.tools.payments import payout

    assert "[simulate]" in payout(9999, "vendor")


def test_real_collect_charges_card_and_posts_ledger(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(
        "src.payments._http_post",
        lambda url, **kw: Resp(200, {"id": "pi_abc123", "status": "succeeded"}),
    )
    from src.tools.finance import collect_invoice

    _invoice(fresh_store, "INV-1001", 2500)
    balance_before = fresh_store.data["company"]["bank_balance"]
    out = collect_invoice("INV-1001")
    assert "pi_abc123" in out
    inv = next(i for i in fresh_store.data["invoices"] if i["id"] == "INV-1001")
    assert inv["status"] == "paid"
    assert fresh_store.data["company"]["bank_balance"] == balance_before + 2500
    assert any(e["kind"] == "receipt" and e["id"] == "pi_abc123" for e in fresh_store.data["ledger"])


def test_real_collect_keeps_invoice_open_on_charge_failure(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr("src.payments._http_post", lambda url, **kw: Resp(402, {}))
    from src.tools.finance import collect_invoice

    _invoice(fresh_store, "INV-1003", 900)
    balance_before = fresh_store.data["company"]["bank_balance"]
    out = collect_invoice("INV-1003")
    assert "stripe HTTP 402" in out
    assert "stays open" in out
    inv = next(i for i in fresh_store.data["invoices"] if i["id"] == "INV-1003")
    assert inv["status"] == "open"
    assert fresh_store.data["company"]["bank_balance"] == balance_before


def test_real_pay_invoice_flags_ref_and_deducts(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("WISE_API_TOKEN", "t")
    monkeypatch.setenv("WISE_PROFILE_ID", "p")
    monkeypatch.setattr("src.payments._http_post", lambda url, **kw: Resp(201, {"id": "tx_wxyz1"}))
    from src.tools.finance import pay_invoice

    _invoice(fresh_store, "INV-1003", 800)
    fresh_store.data["company"]["bank_balance"] = 10000
    fresh_store.save()
    balance_before = fresh_store.data["company"]["bank_balance"]
    out = pay_invoice("INV-1003")
    assert "tx_wxyz1" in out
    inv = next(i for i in fresh_store.data["invoices"] if i["id"] == "INV-1003")
    assert inv["status"] == "paid"
    assert fresh_store.data["company"]["bank_balance"] == balance_before - 800


def test_real_pay_invoice_failure_leaves_open(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("WISE_API_TOKEN", "t")
    monkeypatch.setenv("WISE_PROFILE_ID", "p")
    monkeypatch.setattr("src.payments._http_post", lambda url, **kw: Resp(500, {}))
    from src.tools.finance import pay_invoice

    _invoice(fresh_store, "INV-1001", 700)
    fresh_store.data["company"]["bank_balance"] = 10000
    fresh_store.save()
    balance_before = fresh_store.data["company"]["bank_balance"]
    out = pay_invoice("INV-1001")
    assert "wise HTTP 500" in out
    inv = next(i for i in fresh_store.data["invoices"] if i["id"] == "INV-1001")
    assert inv["status"] == "open"
    assert fresh_store.data["company"]["bank_balance"] == balance_before


def test_real_transfer_uses_provider(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("JARVIS_REAL_SPEND_CAP", "0")
    monkeypatch.setenv("WISE_API_TOKEN", "t")
    monkeypatch.setenv("WISE_PROFILE_ID", "p")
    monkeypatch.setattr("src.payments._http_post", lambda url, **kw: Resp(201, {"id": "tx_tr99"}))
    from src.tools.finance import transfer_funds

    fresh_store.data["company"]["bank_balance"] = 10000
    fresh_store.save()
    out = transfer_funds(1500, "vendor llc")
    assert "tx_tr99" in out
    assert fresh_store.data["company"]["bank_balance"] == 8500


def test_real_plaid_reconciles_treasury(fresh_store, monkeypatch):
    monkeypatch.setenv("JARVIS_REAL_MONEY", "real")
    monkeypatch.setenv("PLAID_ACCESS_TOKEN", "acc")
    fresh_store.data["company"]["bank_balance"] = 1234.0
    fresh_store.save()
    monkeypatch.setattr(
        "src.payments._http_post",
        lambda url, **kw: Resp(200, {"accounts": [{"balances": {"available": 9999.0}}]}),
    )
    from src.tools.payments import sync_real_balance

    out = sync_real_balance()
    assert "USD -> $9,999.00 USD" in out
    assert fresh_store.data["company"]["bank_balance"] == 9999.0
    assert any(e["kind"] == "reconcile" for e in fresh_store.data["ledger"])