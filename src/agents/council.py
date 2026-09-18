"""Credibility council: an independent panel of AI assessors that vets an idea.

Each member is a *separate* LLM turn with its own adversarial brief — demand,
executability, or risk — so the verdict is a genuine multi-agent suffrage rather
than a single opinion. The council returns a consensus object:

* ``agreement``   — fraction of members who found the idea credible
* ``avg_conviction`` — mean 1–5 confidence
* ``dispersion``  — standard deviation of confidence (dissensus penalty)
* ``hard_kill``   — how many members tabled a veto

The aggregation into an Expected Profitability Index happens deterministically
in ``src.tools.invest.assess_idea``; the council only produces the evidence.
"""

import json
import re
import statistics

from langchain_core.messages import HumanMessage

from src.agents.seats import _company_name

MEMBER_BRIEFS = (
    ("market analyst", "Evaluate real external demand: is there evidence customers want this, is the space crowded, is differentiation real? Penalize invented demand."),
    ("operational lead", "Evaluate executable reality: needed skills, people, workflow, and whether the projected unit economics could actually be achieved. Penalize hand-waved numbers."),
    ("risk & compliance", "Evaluate downside: failure modes, legal/regulatory exposure, sunk-cost traps, and whether the required capital could be lost outright. Default to skeptical."),
    ("unit economist", "Stress-test the numbers themselves: is the projected monthly revenue achievable at realistic price, volume, and margin relative to the capital required? Penalize fantasy multiples."),
    ("moat & strategy", "Evaluate defensibility: switching costs, network effects, distribution edges, or is this trivially copyable by a bigger player the moment it works?"),
)

FALLBACK_MEMBER = {"credible": False, "conviction": 1, "kill": True, "notes": "council member produced no parseable verdict"}


def _idea_block(idea: dict) -> str:
    sources = " | ".join(idea.get("source_urls", [])[:6]) or "none cited"
    return (
        f"Opportunity {idea['id']} — {idea['title']}\n"
        f"  Summary: {idea.get('summary', '')}\n"
        f"  Category: {idea.get('category')} | Revenue model: {idea.get('revenue_model')}\n"
        f"  Signal strength (0..1): {idea.get('signal_strength')}\n"
        f"  Evidence sources: {sources}\n"
        f"  Required capital: {idea.get('required_capital')}\n"
        f"  Projected monthly revenue: {idea.get('projected_monthly_revenue')}\n"
        f"  Timeframe: {idea.get('timeframe_months')} months"
    )


def _prompt(brief_name: str, brief: str, idea: dict) -> list:
    return [
        HumanMessage(
            "You are one independent member of a corporate opportunity council at "
            f"{_company_name()}. Your only role: {brief_name}. Do not defer to other "
            "members, do not be agreeable — rule on the evidence in front of you.\n\n"
            f"{_idea_block(idea)}\n\n"
            f"Your brief — {brief}\n\n"
            'Return STRICTLY one JSON object: {"credible": true/false, "conviction": 1..5, "kill": false, "notes": "one sentence"}.'
        )
    ]


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", str(text), re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "credible": bool(payload.get("credible", False)),
        "conviction": int(payload.get("conviction", 1)),
        "kill": bool(payload.get("kill", not payload.get("credible", False))),
        "notes": str(payload.get("notes", "")).strip()[:220],
    }


def run_council(idea: dict, llm, size: int = 3) -> dict:
    """Run a panel of `size` independent assessors against an idea.

    Each member is an independent LLM turn; a member that fails to produce a
    parseable verdict defaults to a hard veto so silence never reads as consent.
    """
    members = []
    for i in range(size):
        brief_name, brief = MEMBER_BRIEFS[i % len(MEMBER_BRIEFS)]
        try:
            response = llm.invoke(_prompt(brief_name, brief, idea))
            verdict = _extract_json(getattr(response, "content", "")) or dict(FALLBACK_MEMBER)
        except Exception:
            verdict = dict(FALLBACK_MEMBER)
        verdict["assessor"] = f"M{i + 1} ({brief_name})"
        verdict["conviction"] = max(1, min(5, int(verdict.get("conviction", 1))))
        members.append(verdict)

    credible = [m for m in members if m["credible"]]
    kills = sum(1 for m in members if m.get("kill"))
    convictions = [m["conviction"] for m in members]
    return {
        "size": size,
        "members": members,
        "agreement": len(credible) / size,
        "avg_conviction": statistics.mean(convictions) if convictions else 0.0,
        "dispersion": statistics.pstdev(convictions) if len(convictions) > 1 else 0.0,
        "hard_kill": kills,
        "compound_confidence": round((len(credible) / size) * (statistics.mean(convictions) / 5.0), 4),
    }