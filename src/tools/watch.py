"""Watchdog tools: standing monitors that fire alerts when a metric crosses a threshold.

Watchdogs give JARVIS an autonomous early-warning layer. Register a rule such as
"alert me when bank balance < $200k" and the scheduler sweeps active rules on a
cadence, recording any trips in the notifications log with a cooldown so they
do not spam the owner.
"""

from datetime import datetime

from src.tools.base import STORE

OPS = {
    "<": lambda v, t: v < t,
    "<=": lambda v, t: v <= t,
    ">": lambda v, t: v > t,
    ">=": lambda v, t: v >= t,
}

WATCHDOG_COOLDOWN_MINUTES = 60

def _portfolio_at_risk(data: dict) -> int:
    """Active investments past projected breakeven, or with no progress logged past half-breakeven."""
    from datetime import datetime

    now = datetime.now()
    at_risk = 0
    for inv in data.get("investments", []):
        if inv.get("status") != "active":
            continue
        breakeven = inv.get("breakeven_months")
        if breakeven is None:
            continue
        try:
            start = datetime.fromisoformat(str(inv.get("at", "")))
        except (TypeError, ValueError):
            start = now
        elapsed = max(0.0, (now - start).total_seconds() / (30.44 * 86400))
        notes = len(inv.get("notes", []) or [])
        if elapsed > breakeven or (notes == 0 and elapsed > breakeven * 0.5):
            at_risk += 1
    return at_risk


WATCHDOG_METRICS = {
    "bank_balance": lambda d: d["company"]["bank_balance"],
    "open_receivables": lambda d: sum(i["amount"] for i in d["invoices"] if i["status"] in ("open", "overdue")),
    "overdue_invoice_count": lambda d: sum(1 for i in d["invoices"] if i["status"] == "overdue"),
    "weighted_pipeline": lambda d: sum(o["amount"] * o.get("probability", 0) for o in d["opportunities"]),
    "open_opportunity_count": lambda d: len(d["opportunities"]),
    "monthly_payroll": lambda d: sum(e["salary"] for e in d["employees"] if e["status"] == "active"),
    "active_employees": lambda d: sum(1 for e in d["employees"] if e["status"] == "active"),
    "active_projects": lambda d: sum(1 for p in d["projects"] if p["budget"] - p["spent"] > 0),
    "portfolio_deployed": lambda d: sum(i["amount"] for i in d.get("investments", []) if i["status"] == "active"),
    "active_investments": lambda d: sum(1 for i in d.get("investments", []) if i["status"] == "active"),
    "investments_at_risk": _portfolio_at_risk,
    "investments_matured": lambda d: sum(1 for i in d.get("investments", []) if i["status"] == "matured"),
    "investments_written_off": lambda d: sum(1 for i in d.get("investments", []) if i["status"] == "written_off"),
}


def _fmt(value: float) -> str:
    return f"{int(value):,}" if isinstance(value, float) and value.is_integer() else f"{value:,.2f}"


def watchdog_metrics() -> str:
    """Show the list of metrics a watchdog can monitor."""
    return "Available watchdog metrics:\n" + "\n".join(f"  - {name}" for name in WATCHDOG_METRICS)


def _find_watchdog(watchdog_id: str):
    target = str(watchdog_id).strip().lower()
    for w in STORE.data["watchdogs"]:
        if w["id"].lower() == target:
            return w
    return None


def create_watchdog(metric: str, operator: str, threshold: float, note: str = "") -> str:
    """Register a standing monitor that alerts whenever <metric> <operator> <threshold> becomes true."""
    if metric not in WATCHDOG_METRICS:
        return f"Error: unknown metric '{metric}'. Available: {', '.join(WATCHDOG_METRICS)}."
    if operator not in OPS:
        return f"Error: unknown operator '{operator}'. Use one of: {', '.join(OPS)}."
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return "Error: threshold must be a number."
    dogs = STORE.data["watchdogs"]
    wid = f"WD-{len(dogs) + 1}"
    dogs.append(
        {
            "id": wid,
            "metric": metric,
            "op": operator,
            "threshold": threshold,
            "note": note.strip() or f"{metric} {operator} {threshold:g}",
            "active": True,
            "last_fired": None,
            "created_at": STORE.timestamp(),
        }
    )
    STORE.notify(f"Watchdog {wid} armed: alert when {metric} {operator} {threshold:g}.")
    STORE.save()
    return f"Watchdog {wid} armed — will alert when {metric} {operator} {threshold:g}."


def list_watchdogs() -> str:
    """Show every registered watchdog with status and the last time it fired."""
    dogs = STORE.data["watchdogs"]
    if not dogs:
        return "No watchdogs registered. Use create_watchdog(metric, operator, threshold) to add one."
    lines = [f"Watchdogs ({len(dogs)}):"]
    for w in dogs:
        state = "active" if w["active"] else "paused"
        fired = w["last_fired"] or "never"
        lines.append(f"  - {w['id']} | {state} | {w['metric']} {w['op']} {w['threshold']:g} | note: {w['note']} | last fired: {fired}")
    return "\n".join(lines)


def pause_watchdog(watchdog_id: str) -> str:
    """Temporarily disable a watchdog without deleting it."""
    dog = _find_watchdog(watchdog_id)
    if not dog:
        return f"Error: no watchdog '{watchdog_id}'."
    dog["active"] = False
    STORE.save()
    return f"Paused {dog['id']}."
def resume_watchdog(watchdog_id: str) -> str:
    """Re-enable a previously paused watchdog."""
    dog = _find_watchdog(watchdog_id)
    if not dog:
        return f"Error: no watchdog '{watchdog_id}'."
    dog["active"] = True
    STORE.save()
    return f"Resumed {dog['id']}."


def delete_watchdog(watchdog_id: str) -> str:
    """Remove a watchdog permanently."""
    dog = _find_watchdog(watchdog_id)
    if not dog:
        return f"Error: no watchdog '{watchdog_id}'."
    STORE.data["watchdogs"].remove(dog)
    STORE.save()
    return f"Deleted {dog['id']}."


def _mitigation_template(tool_name: str) -> str:
    """Source for a self-authored mitigation tool JARVIS can run on itself."""
    return (
        "from src.tools.watch import WATCHDOG_METRICS\n"
        "from src.tools.base import STORE\n"
        "\n"
        f"def {tool_name}(metric: str, operator: str, threshold: float):\n"
        "    current = WATCHDOG_METRICS.get(metric, lambda d: 0)(STORE.data)\n"
        "    recs = {\n"
        '        "<": "freeze discretionary spend and raise working capital",\n'
        '        ">": "drive aggressive action to reverse the trend",\n'
        '        "<=": "shore up buffer and reduce exposure",\n'
        '        ">=": "lock in gains and guard against reversal",\n'
        "    }\n"
        '    action = recs.get(operator, "review and intervene")\n'
        '    STORE.notify(f"AUTONOMOUS MITIGATION [{metric}]: breached {operator} {threshold:g}; current {current:g}; action: " + action)\n'
        "    STORE.save()\n"
        '    return f"MITIGATION for {metric}: current={current:g}, breached {operator} {threshold:g}; action taken: " + action'
    )


def check_watchdogs(auto_heal: bool = False) -> str:
    """Evaluate every active watchdog against live metrics, firing alerts that trip.

    A tripped watchdog records an alert in the notifications log (rate-limited by a
    cooldown) so the owner can review what fired while they were away.

    When ``auto_heal`` is enabled, each tripped watchdog immediately self-authors a
    mitigation tool (``mitigate_<metric>``) through the tool factory — bypassing the
    sandbox — and runs it against the live numbers. JARVIS fixes what it flagged."""
    dogs = STORE.data["watchdogs"]
    if not dogs:
        return "No watchdogs registered. Use create_watchdog(metric, operator, threshold) to add one."

    now = datetime.now()
    fired, suppressed, quiet, healed = [], [], [], []
    for w in dogs:
        if not w["active"]:
            continue
        metric_value = WATCHDOG_METRICS[w["metric"]](STORE.data)
        if not OPS[w["op"]](metric_value, w["threshold"]):
            quiet.append(w["id"])
            continue
        last = w.get("last_fired")
        if last and (now - datetime.fromisoformat(last)).total_seconds() < WATCHDOG_COOLDOWN_MINUTES * 60:
            suppressed.append(f"{w['id']} ({w['metric']} {w['op']} {w['threshold']:g})")
            continue
        w["last_fired"] = now.isoformat(timespec="minutes")
        w["last_value"] = metric_value
        alert = f"WATCHDOG {w['id']} tripped — {w['metric']} {w['op']} {w['threshold']:g} (current {_fmt(metric_value)})"
        if w.get("note"):
            alert += f" — {w['note']}"
        STORE.notify(alert)
        fired.append(alert)
        if auto_heal:
            healed.append(_auto_heal(w))

    STORE.save()
    lines = [f"Watchdog sweep ({len(dogs)} registered)"]
    if fired:
        lines.extend("  ALERT: " + line for line in fired)
    if healed:
        lines.extend("  AUTONOMOUS MITIGATION: " + line for line in healed)
    if suppressed:
        lines.append("  Suppressed (cooldown): " + "; ".join(suppressed))
    if not fired and not suppressed:
        lines.append("  No active watchdog is currently tripping.")
    return "\n".join(lines)


def _auto_heal(w: dict) -> str:
    """Self-author a mitigation tool for a tripped watchdog (sandbox bypassed) and run it."""
    from src.tools import builder as builder_tools

    tool_name = f"mitigate_{w['metric']}"
    if tool_name not in builder_tools.GENERATED:
        source = _mitigation_template(tool_name)
        result = builder_tools.generate_tool(tool_name, source, f"autonomous mitigation for {w['metric']}", trust=True)
    else:
        result = "tool already deployed"
    outcome = builder_tools.run_generated_tool(
        tool_name,
        f'{{"metric": "{w["metric"]}", "operator": "{w["op"]}", "threshold": {w["threshold"]:g}}}',
    )
    note = ((result.splitlines()[-1] if "Error" not in result else result) + " | ") if "Error" not in result else f"{result} | "
    return f"{w['id']} ({w['metric']}) deployed 'mitigate_{w['metric']}' — {note}run -> {outcome}"