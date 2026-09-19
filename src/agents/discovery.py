"""Autonomous opportunity discovery.

JARVIS cannot keep finding money-making ideas if nothing ever hunts for them,
so this module turns live market signals into structured candidates the
credibility council and probability engine (``src.tools.invest``) can then
diligenze and — under full autonomy — fund.

Flow for every configured market query:

1. ``web_research`` scrapes real, current no-auth sources (Hacker News,
   DuckDuckGo, Reddit, Wikipedia) and returns cited signals.
2. The model distills the report into 1..N ``record_idea`` payloads (strict
   JSON) — a separate, scoped LLM turn per query, like the council's membership.
3. Each candidate is persisted via ``record_idea`` only if it clears the tool's
   own validation and does not duplicate an idea already on record.

Discovery never deploys capital; it only feeds the pipeline. The autonomy gate
still decides whether anything gets funded afterwards.
"""

import json
import re

from langchain_core.messages import HumanMessage

from src.config.settings import Settings
from src.tools.base import STORE
from src.tools.research import CATEGORIES, REVENUE_MODELS, record_idea, web_research

DEFAULT_QUERIES = (
    "profitable niche SaaS and automation micro-business ideas with proven willingness to pay",
    "high-margin digital product opportunities for a one-person AI company",
    "small-business service niches with measurable demand in 2026",
)
MAX_CITATIONS = 6


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.strip().lower()).strip()


def _prompt(query: str, report: str) -> list:
    categories = ", ".join(CATEGORIES)
    models = ", ".join(REVENUE_MODELS)
    return [
        HumanMessage(
            "You are the discovery analyst for a one-person AI business engine. The "
            "market-research report below was scraped from live public sources. Distill "
            f"up to {MAX_CITATIONS} concrete, money-making opportunity ideas from it. "
            "Inference is expected, but every idea must be grounded in at least one "
            "cited http source_url from the report, and the numbers should be realistic "
            "for a small operator.\n\n"
            f"Allowed categories: {categories}\n"
            f"Allowed revenue models: {models}\n\n"
            'Return STRICTLY a JSON array (possibly []) with each object shaped:\n'
            '{"title": "<concise name>", "summary": "<2-3 sentence case>", '
            '"category": "<one of the allowed>", "revenue_model": "<one of the allowed>", '
            '"source_urls": ["https://..."], "signal_strength": <0..1, evidence strength>, '
            '"required_capital": <number >= 0>, "projected_monthly_revenue": <number >= 0>, '
            '"timeframe_months": <int 1..36>}\n\n'
            f'MARKET RESEARCH FOR QUERY "{query}":\n{report}'
        )
    ]


def _extract_json(text) -> list:
    """Pull the JSON array out of an LLM reply, tolerating code fences."""
    body = str(text)
    block = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", body)
    if block:
        body = block.group(1)
    else:
        match = re.search(r"\[[\s\S]*\]", body)
        body = match.group(0) if match else ""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return []
    return payload if isinstance(payload, list) else [payload]


def discover(settings: Settings | None = None, llm=None, queries: list | None = None, per_run: int = 2) -> list[str]:
    """Hunt for new money-making ideas and record them for the council.

    Returns the list of new ``IV-xxx`` idea ids actually recorded this run.
    ``queries`` and ``per_run`` override the settings/env floor for tests and
    callers who want a different cadence.
    """
    settings = settings or Settings.from_env(require_key=False)
    if llm is None:
        from src.agents.core import create_llm

        llm = create_llm(settings)
    targets = [q for q in (queries or settings.discovery_queries or DEFAULT_QUERIES) if q.strip()]
    per_run = max(1, min(5, int(per_run)))

    recorded: list[str] = []
    seen: set[str] = set()
    for query in targets:
        if len(recorded) >= per_run:
            break
        try:
            report = web_research(query)
        except Exception:
            continue
        if not report or not report.strip():
            continue
        try:
            response = llm.invoke(_prompt(query, report))
        except Exception:
            continue
        for item in _extract_json(getattr(response, "content", "")):
            if len(recorded) >= per_run:
                break
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            key = _norm(title)
            if not key or not title or key in seen:
                continue
            existing = {_norm(i.get("title", "")) for i in STORE.data.get("ideas", [])}
            if key in existing:
                continue
            before = len(STORE.data.get("ideas", []))
            outcome = record_idea(
                title=title,
                summary=str(item.get("summary", "")).strip(),
                category=str(item.get("category", "")).strip(),
                revenue_model=str(item.get("revenue_model", "")).strip(),
                source_urls=[u for u in (item.get("source_urls") or []) if str(u).strip().startswith("http")][:MAX_CITATIONS],
                signal_strength=float(item.get("signal_strength") or 0.0),
                required_capital=float(item.get("required_capital") or 0.0),
                projected_monthly_revenue=float(item.get("projected_monthly_revenue") or 0.0),
                timeframe_months=int(item.get("timeframe_months") or 12),
            )
            if outcome.startswith("Error:") or not STORE.data.get("ideas") or len(STORE.data["ideas"]) == before:
                continue
            seen.add(key)
            recorded.append(STORE.data["ideas"][-1]["id"])
    return recorded