"""Decision-engine tools: a structured layer for weighing consequential choices.

``decide`` grounds a recommendation in live company metrics, scores options on a
weighted criteria matrix, and logs decisions to an on-record ledger so future
calls and watchdogs can cite how past calls were made and how they turned out."""

import json

from src.tools.base import STORE

DECISION_CRITERIA = ("cost", "risk", "time_to_impact", "upside", "strategic_fit")
CRITERIA_WEIGHTS = {
    "cost": 0.25,
    "risk": 0.25,
    "time_to_impact": 0.15,
    "upside": 0.20,
    "strategic_fit": 0.15,
}


def _payroll_monthly(data: dict) -> float:
    return sum(e["salary"] for e in data["employees"] if e["status"] == "active") / 12


def decision_brief(topic: str = "") -> str:
    """Gather the live metrics an executive needs before a decision: cash, runway, receivables, pipeline, burn."""
    data = STORE.data
    balance = data["company"]["bank_balance"]
    payroll = _payroll_monthly(data)
    revenue = [r["amount"] for r in data["revenue"]]
    avg_revenue = sum(revenue) / len(revenue) if revenue else 0.0
    runway = balance / payroll if payroll > 0 else 0.0
    open_rcv = sum(i["amount"] for i in data["invoices"] if i["status"] in ("open", "overdue"))
    pipeline = sum(o["amount"] * o.get("probability", 0) for o in data["opportunities"])
    overdue = sum(1 for i in data["invoices"] if i["status"] == "overdue")
    remaining = sum(p["budget"] - p["spent"] for p in data["projects"] if p["budget"] - p["spent"] > 0)
    active_dogs = sum(1 for w in data["watchdogs"] if w["active"])
    return (
        f"Decision brief — {topic or 'general'}:\n"
        f"  Cash balance: {STORE.currency(balance)}\n"
        f"  Monthly payroll (run rate): {STORE.currency(payroll)}\n"
        f"  Est. runway at current burn: {runway:.1f} months\n"
        f"  Avg monthly revenue (YTD): {STORE.currency(avg_revenue)}\n"
        f"  Open receivables: {STORE.currency(open_rcv)} ({overdue} overdue)\n"
        f"  Weighted pipeline: {STORE.currency(pipeline)}\n"
        f"  Remaining project budget: {STORE.currency(remaining)}\n"
        f"  Active watchdogs: {active_dogs} | Decisions on record: {len(data['decisions'])}"
    )


def evaluate_options(decision: str, options: list, scores: dict) -> str:
    """Score each option 1–5 on cost/risk/time_to_impact/upside/strategic_fit and rank them by weighted total."""
    if not isinstance(options, list) or not options:
        return "Error: pass at least one option as a list, and a 'scores' map of option -> {criterion: 1..5}."
    if not isinstance(scores, dict):
        return "Error: 'scores' must be a JSON object mapping each option to its per-criterion scores."
    invalid = [o for o in options if o not in scores]
    if invalid:
        return f"Error: missing scores for: {', '.join(invalid)}."
    for option, values in scores.items():
        bad = [c for c in values if c not in DECISION_CRITERIA]
        if bad:
            return f"Error: unknown criteria {bad}. Use: {', '.join(DECISION_CRITERIA)}."
        out_of_range = [
            c for c, v in values.items()
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5
        ]
        if out_of_range:
            return f"Error: scores for {option} ({', '.join(out_of_range)}) must be integers 1–5."

    rows = []
    for option in options:
        values = scores[option]
        weighted = sum(CRITERIA_WEIGHTS[c] * values[c] for c in DECISION_CRITERIA)
        rows.append((weighted, option, values))
    rows.sort(key=lambda r: r[0], reverse=True)

    header = ", ".join(f"{c} x{w:g}" for c, w in CRITERIA_WEIGHTS.items())
    lines = [f"Decision: {decision}", f"Criteria (1–5): {header}"]
    for rank, (weighted, option, values) in enumerate(rows, start=1):
        breakdown = ", ".join(f"{c} {values[c]}" for c in DECISION_CRITERIA)
        lines.append(f"  {rank}. {option} — weighted {weighted:.2f}  [{breakdown}]")
    lines.append(f"Recommended: {rows[0][1]}")
    return "\n".join(lines)


def log_decision(topic: str, decision: str, rationale: str, outcome: str = "pending") -> str:
    """Record a decision (and the reasoning behind it) on the company's decision ledger."""
    ledger = STORE.data["decisions"]
    did = f"D-{len(ledger) + 1}"
    ledger.append(
        {
            "id": did,
            "at": STORE.timestamp(),
            "topic": topic.strip(),
            "decision": decision.strip(),
            "rationale": rationale.strip(),
            "outcome": outcome.strip(),
        }
    )
    STORE.save()
    return f"Logged {did} — {decision.strip()} — outcome '{outcome.strip()}'. {len(ledger)} decisions on record."


def list_decisions(topic: str = "", outcome: str = "") -> str:
    """Show decisions on the ledger, optionally filtered by topic or outcome."""
    entries = STORE.data["decisions"]
    if topic:
        entries = [e for e in entries if topic.strip().lower() in e["topic"].lower()]
    if outcome:
        entries = [e for e in entries if e["outcome"].lower() == outcome.strip().lower()]
    if not entries:
        return "No decisions on record matching that filter."
    lines = [f"Decision ledger ({len(entries)}):"]
    for e in entries:
        lines.append(f"  {e['id']} | {e['at']} | {e['topic']} -> {e['decision']} | outcome: {e['outcome']}")
    return "\n".join(lines)


def update_decision_outcome(decision_id: str, outcome: str) -> str:
    """Mark how a previously logged decision actually turned out, closing the learning loop."""
    for entry in STORE.data["decisions"]:
        if entry["id"].lower() == str(decision_id).strip().lower():
            entry["outcome"] = outcome.strip()
            STORE.save()
            return f"{entry['id']} outcome set to '{outcome.strip()}'."
    return f"Error: no decision '{decision_id}'."


def decisions_export() -> str:
    """Dump the full decision ledger as JSON (for audits or external analysis)."""
    return json.dumps(STORE.data["decisions"], indent=2, default=str)