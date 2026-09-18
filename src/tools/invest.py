"""Investment tools: JARVIS's probability engine and self-funding pipeline.

Model
-----
Each opportunity is graded on five factors into an Expected Profitability
Index (EPI, 0–100). The mathematics is deterministic and fully transparent —
the same inputs always produce the same score — while the credibility evidence
comes from the independent multi-agent council (``src.agents.council``).

Factor weights (sum to 1.0)
    economics      0.30   12-month net (70% of projected revenue) / required capital,
                           saturating at a 3x multiple.
    market_signal  0.25   recorder's 0..1 evidence strength, integrity-adjusted:
                           a signal claim with no cited source is discounted.
    timeframe      0.15   1 - months_to_revenue/12 (recovery speed).
    execution_fit  0.15   does the company already have a matching seat/agent?
    council        0.15   agreement x mean conviction (1..5).

Hard checks
    one council veto  -> EPI capped at 45 (un-fundable)
    two or more vetoes -> EPI capped at 25 (rejected)
    no council run     -> solo mode, council factor fixed at 0.5, flagged transparently.

Recommendations
    EPI >= to_vability_threshold  STRONG BUY  — fundable by the autonomous loop
    threshold > EPI >= 50          CONDITIONAL — fund only with explicit owner intent
    EPI < 50                       REJECT      — not credible

``invest`` is a critical action (capped by treasury and by the plan's capital
requirement). Under ``JARVIS_AUTONOMY=full`` the gate auto-approves.
"""

import json

from src.config.settings import Settings
from src.tools.base import STORE, register_critical

FACTOR_WEIGHTS = {
    "economics": 0.30,
    "market_signal": 0.25,
    "timeframe": 0.15,
    "execution_fit": 0.15,
    "council": 0.15,
}

CATEGORY_FIT = {
    "product": ("CTO", "Vertex", "engineering"),
    "service": ("COO", "Atlas", "operations"),
    "agency": ("CMO", "Sol", "marketing"),
    "marketplace": ("CRO", "Orion", "sales"),
    "automation": ("CTO", "Vertex", "engineering"),
    "content": ("CMO", "Sol", "marketing"),
    "investment": ("CFO", "Nova", "finance"),
}

INVESTMENT_STATES = ("active", "matured", "cashed_out", "written_off")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _idea(idea_id: str) -> dict | None:
    target = str(idea_id).strip().lower()
    for idea in STORE.data["ideas"]:
        if idea["id"].lower() == target:
            return idea
    return None


def _council_llm():
    from src.agents.core import create_llm

    return create_llm(Settings.from_env())


def _factor_scores(idea: dict, council: dict | None) -> dict:
    """The deterministic probability-engine factors (each 0..1)."""
    monthly = float(idea.get("projected_monthly_revenue", 0.0) or 0.0)
    capital = float(idea.get("required_capital", 0.0) or 0.0)
    signal = _clamp(float(idea.get("signal_strength", 0.0) or 0.0))
    months = max(1, min(36, int(idea.get("timeframe_months", 12) or 12)))

    economics = 0.0
    if monthly > 0 and capital > 0:
        multiple = (monthly * 12 * 0.7) / capital
        economics = _clamp(multiple / 3.0)
    elif monthly > 0:
        economics = 0.55  # no capital requirement is naively optimistic
    else:
        economics = 0.0

    sources = len([u for u in idea.get("source_urls", []) if str(u).strip().startswith("http")])
    market_signal = _clamp(signal)
    if signal > 0.2 and sources == 0:
        market_signal *= 0.4  # claimed evidence with none cited

    timeframe = _clamp(1.0 - months / 12.0)

    seat, agent, _focus = CATEGORY_FIT.get(idea.get("category", ""), ("", "", ""))
    execution_fit = 0.5
    if seat and any(r["title"] == seat and r.get("agent") for r in STORE.data["leadership_roles"]):
        execution_fit = 1.0
    elif agent and any(a["name"].lower() == agent.lower() for a in STORE.data["ai_agents"]):
        execution_fit = 0.8

    council_score = 0.5 if council is None else _clamp(council.get("compound_confidence", 0.0))
    return {
        "economics": round(economics, 3),
        "market_signal": round(market_signal, 3),
        "timeframe": round(timeframe, 3),
        "execution_fit": round(execution_fit, 3),
        "council": round(council_score, 3),
    }


def _recommend(epi: float, threshold: float) -> str:
    if epi >= threshold:
        return "STRONG BUY — fundable"
    if epi >= 50.0:
        return "CONDITIONAL — fund only with explicit owner intent"
    return "REJECT — not credible"


def _aggregate(idea: dict, council: dict | None, threshold: float) -> dict:
    factors = _factor_scores(idea, council)
    epi = 100.0 * sum(FACTOR_WEIGHTS[k] * factors[k] for k in FACTOR_WEIGHTS)
    kills = council.get("hard_kill", 0) if council else 0
    if kills == 1:
        epi = min(epi, 45.0)
    elif kills >= 2:
        epi = min(epi, 25.0)
    epi = round(epi, 1)
    recommendation = _recommend(epi, threshold)
    return {
        "at": STORE.timestamp(),
        "epi": epi,
        "recommendation": recommendation,
        "factors": factors,
        "council": council,
        "mode": "council" if council else "solo",
    }


def _coerce_council(assessments) -> dict | None:
    """Turn raw member verdicts into a council object (used by tests and explicit calls)."""
    if assessments is None:
        return None
    if isinstance(assessments, dict) and "members" in assessments and "agreement" in assessments:
        return assessments
    if not isinstance(assessments, list) or not assessments:
        return None
    members = []
    for i, m in enumerate(assessments, start=1):
        members.append(
            {
                "assessor": str(m.get("assessor", f"M{i}")),
                "credible": bool(m.get("credible", False)),
                "conviction": max(1, min(5, int(m.get("conviction", 1)))),
                "kill": bool(m.get("kill", not bool(m.get("credible", False)))),
                "notes": str(m.get("notes", "")).strip()[:220],
            }
        )
    return {
        "size": len(members),
        "members": members,
        "agreement": sum(1 for m in members if m["credible"]) / len(members),
        "avg_conviction": sum(m["conviction"] for m in members) / len(members),
        "dispersion": 0.0,
        "hard_kill": sum(1 for m in members if m["kill"]),
        "compound_confidence": round(
            (sum(1 for m in members if m["credible"]) / len(members))
            * (sum(m["conviction"] for m in members) / len(members) / 5.0),
            4,
        ),
    }


def _scorecard(idea: dict, assessment: dict) -> str:
    lines = [
        f"Probability engine — {idea['id']}: '{idea['title']}'",
        f"  EPI: {assessment['epi']:.1f}/100 | Verdict: {assessment['recommendation']}",
        f"  Mode: {'credibility council (N=' + str(assessment['council']['size']) + ')'
                 if assessment.get('council') else 'solo (no council available)'}",
    ]
    if assessment.get("council"):
        c = assessment["council"]
        lines.append(
            f"  Council: {c['agreement']:.0%} credible | avg conviction {c['avg_conviction']:.1f}/5 | "
            f"dissensus σ {c['dispersion']:.2f} | vetoes {c['hard_kill']}"
        )
        for m in c["members"]:
            flag = "VETO" if m.get("kill") else ("agree" if m.get("credible") else "dissents")
            lines.append(f"    {m['assessor']}: {flag} (conviction {m['conviction']}/5) — {m.get('notes', '')}")
    for factor, weight in FACTOR_WEIGHTS.items():
        lines.append(f"  {factor} x{weight:g}: {assessment['factors'][factor]:.3f}")
    return "\n".join(lines)


def assess_idea(idea_id: str, assessments=None) -> str:
    """Run the probability engine on an opportunity and cache the EPI verdict.

    Pass ``assessments`` as the council member verdicts (list of
    {"credible", "conviction", "kill", "notes"}) to supply multi-agent evidence, or
    omit it to run the credibility council automatically against the live model.
    """
    idea = _idea(idea_id)
    if not idea:
        return f"Error: no idea '{idea_id}'."
    council = _coerce_council(assessments)
    if council is None:
        stored = idea.get("council")
        if stored:
            council = stored
        elif STORE.get().data_file:
            try:
                council = _run_council_live(idea)
            except Exception:
                council = None

    assessment = _aggregate(idea, council, Settings.from_env(require_key=False).viability_threshold)
    idea["assessment"] = assessment
    if council is not None:
        idea["council"] = council
    idea["status"] = "vetted" if assessment["epi"] >= 50.0 else "rejected"
    STORE.notify(f"{idea['id']} assessed: EPI {assessment['epi']:.1f} — {assessment['recommendation']}.")
    STORE.save()
    return _scorecard(idea, assessment)


def _run_council_live(idea: dict) -> dict:
    from src.agents.council import run_council

    settings = Settings.from_env()
    return run_council(idea, _council_llm(), size=settings.council_size)


def invest(idea_id: str, amount: float, force: bool = False) -> str:
    """Deploy capital into a vetted opportunity. Critical action (HITL-gated).

    Enforces: the idea must be scored, not rejected, funds must exist, and the
    amount cannot exceed the plan's own capital requirement. target:
    ``force=True`` overrides a CONDITIONAL verdict."""
    idea = _idea(idea_id)
    if not idea:
        return f"Error: no idea '{idea_id}'."
    assessment = idea.get("assessment")
    if not assessment:
        return f"Error: {idea['id']} has not been assessed. Run assess_idea('{idea_id}') first."
    if idea["status"] == "rejected" or assessment["epi"] < 50.0:
        return f"Error: {idea['id']} scored EPI {assessment['epi']:.1f} — rejected by the probability engine."
    if idea["status"] == "funded":
        return f"Error: {idea['id']} is already funded ({idea.get('system_tool') or 'no system attached'})."
    if "CONDITIONAL" in assessment["recommendation"] and not force:
        return f"Error: {idea['id']} is CONDITIONAL. Pass force=True to fund against the engine's caution."
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Error: amount must be a number."
    if amount <= 0:
        return "Error: investment amount must be positive."
    cap = Settings.from_env(require_key=False).max_investment_amount
    if cap and amount > cap:
        return f"Error: {STORE.currency(amount)} exceeds the per-idea cap of {STORE.currency(cap)}."
    capital = float(idea.get("required_capital", 0.0) or 0.0)
    if amount > capital:
        return f"Error: {STORE.currency(amount)} exceeds the plan's capital requirement of {STORE.currency(capital)}."
    company = STORE.data["company"]
    if amount > company["bank_balance"]:
        return f"Error: insufficient funds ({STORE.currency(company['bank_balance'])} available)."
    company["bank_balance"] -= amount
    monthly = float(idea.get("projected_monthly_revenue", 0.0) or 0.0)
    breakeven = (capital / monthly) if monthly > 0 else None
    iid = f"IS-{len(STORE.data['investments']) + 1:03d}"
    record = {
        "id": iid,
        "idea_id": idea["id"],
        "at": STORE.timestamp(),
        "amount": amount,
        "status": "active",
        "epi_at_funding": assessment["epi"],
        "breakeven_months": round(breakeven, 1) if breakeven else None,
        "notes": [],
    }
    STORE.data["investments"].append(record)
    idea["status"] = "funded"
    STORE.data.setdefault("ledger", []).append(
        {
            "at": STORE.timestamp(),
            "kind": "investment",
            "id": iid,
            "counterparty": idea["title"],
            "amount": -amount,
            "note": f"funding of {idea['id']} at EPI {assessment['epi']:.1f}",
        }
    )
    STORE.notify(
        f"{iid}: invested {STORE.currency(amount)} into {idea['id']} ('{idea['title']}') at EPI {assessment['epi']:.1f}."
    )
    STORE.save()
    return (
        f"Invested {STORE.currency(amount)} into {idea['id']} ('{idea['title']}') — {iid} created.\n"
        f"  New balance: {STORE.currency(company['bank_balance'])} | "
        f"Projected breakeven: {f'{breakeven:.1f} months' if breakeven else 'n/a (no projected revenue)'} | "
        f"EPI at funding: {assessment['epi']:.1f}"
    )


def implement_idea(idea_id: str, description: str = "", execute: bool = False) -> str:
    """Turn a vetted/funded opportunity into an operating system: author a generated
    tool that tracks the venture's live numbers, register it, and (optionally) run it."""
    idea = _idea(idea_id)
    if not idea:
        return f"Error: no idea '{idea_id}'."
    if idea["status"] not in ("vetted", "funded", "implemented"):
        return f"Error: {idea['id']} is '{idea['status']}' — assess it (and reach at least 50 EPI) first."
    from src.tools.builder import generate_tool, run_generated_tool

    tool_name = f"system_{idea['id'].lower().replace('-', '_')}"
    assessment = idea.get("assessment") or {}
    epi_val = assessment.get("epi") if isinstance(assessment.get("epi"), (int, float)) else 0
    verdict_json = json.dumps(assessment.get("recommendation", "n/a"))
    source = (
        "from src.tools.base import STORE\n"
        "import json\n"
        "\n"
        f'def {tool_name}(note: str = ""):\n'
        f'    data = {{"id": {json.dumps(idea["id"])}, "title": {json.dumps(idea["title"])}, '
        f'"status": {json.dumps(idea["status"])}, "epi": {epi_val}, "verdict": {verdict_json}}}\n'
        '    if note.strip():\n'
        '        data["note"] = note.strip()\n'
        '    STORE.notify(f"SYSTEM {data[\'id\']}: {data[\'title\']} | EPI {data[\'epi\']} | {data[\'verdict\']}" + ((" | " + note.strip()) if note.strip() else ""))\n'
        "    STORE.save()\n"
        '    return f"{data[\'id\']} operating system run — EPI {data[\'epi\']} ({data[\'verdict\']})" + ((" | note: " + note.strip()) if note.strip() else "")\n'
    )
    result = generate_tool(tool_name, source, description.strip() or f"operating system for {idea['id']} ({idea['title']})")
    if result.startswith("Error"):
        return f"{result}\nOperation on {idea['id']} not registered; status unchanged."
    idea["system_tool"] = tool_name
    idea["status"] = "implemented"
    STORE.notify(f"Opportunity {idea['id']} implemented as operating system tool '{tool_name}'.")
    STORE.save()
    outcome = ""
    if execute:
        outcome = "\n" + run_generated_tool(tool_name, '{"note": "first automated run at implementation"}')
    return f"{result}{outcome}\nIdea {idea['id']} status -> implemented (tool '{tool_name}')."


def list_investments(status: str = "") -> str:
    """Show deployed capital, optionally filtered by status."""
    entries = STORE.data["investments"]
    if status:
        valid = [s for s in INVESTMENT_STATES if s == status.strip().lower()]
        if not valid:
            return f"Error: status must be one of: {', '.join(INVESTMENT_STATES)}."
        entries = [e for e in entries if e["status"] == status.strip().lower()]
    if not entries:
        return "No investments deployed yet. Assess an idea and invest."
    lines = [f"Investments ({len(entries)}):"]
    for e in entries:
        breakeven = f"{e.get('breakeven_months', 0):.1f} mo" if isinstance(e.get("breakeven_months"), (int, float)) else "n/a"
        idea = _idea(e["idea_id"])
        title = idea["title"] if idea else e["idea_id"]
        lines.append(f"  {e['id']} | {e['status']} | {STORE.currency(e['amount'])} -> {e['idea_id']} ({title}) | EPI {e.get('epi_at_funding')} | breakeven {breakeven}")
    return "\n".join(lines)


def update_investment_progress(investment_id: str, note: str, status: str = "active") -> str:
    """Log progress on a deployed investment and optionally roll its status forward."""
    target = str(investment_id).strip().lower()
    record = next((e for e in STORE.data["investments"] if e["id"].lower() == target), None)
    if not record:
        return f"Error: no investment '{investment_id}'."
    status = status.strip().lower()
    if status not in INVESTMENT_STATES:
        return f"Error: status must be one of: {', '.join(INVESTMENT_STATES)}."
    previous = record["status"]
    record["status"] = status
    entry = {"at": STORE.timestamp(), "status": status, "note": note.strip()}
    if note.strip() or status != previous:
        record["notes"].append(entry)
    STORE.notify(f"{record['id']}: status {previous} -> {status} — {note.strip()}")
    STORE.save()
    return f"{record['id']}: {previous} -> {status}. {len(record['notes'])} progress entries logged."


register_critical("invest")