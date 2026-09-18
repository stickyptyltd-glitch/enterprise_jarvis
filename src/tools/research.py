"""Market-intelligence tools: scrape the web for money-making ideas and record
them as structured, vettable opportunities.

``web_research`` pulls real, current public signals from several no-auth sources
(Hacker News, Wikipedia, DuckDuckGo, Reddit) so an idea is grounded in external
evidence rather than invented. The fetcher is a thin seam (``_run_sources``) so
tests run fully offline while production hits the live web.

``record_idea`` persists a structured opportunity the agents synthesize from
that research. Assessment and funding live in ``src.tools.invest``.
"""

import json
import re
import time
from html import unescape
from urllib.parse import unquote

from src.tools.base import STORE

USER_AGENT = "JARVIS-market-intel/1.0"
FETCH_TIMEOUT = 6
MAX_PER_SOURCE = 5

CATEGORIES = ("product", "service", "agency", "marketplace", "automation", "content", "investment")
REVENUE_MODELS = ("recurring", "transactional", "project", "ads", "arbitrage", "hybrid")


def _get(url: str, params: dict | None = None) -> str | None:
    """HTTP GET returning text, or None when the source is unreachable."""
    try:
        import requests  # local import so the module imports cleanly offline

        resp = requests.get(
            url,
            params=params,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return None
        return resp.text
    except Exception:
        return None


def _clean(text: str, limit: int = 260) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _hn(query: str) -> list[dict]:
    body = _get("https://hn.algolia.com/api/v1/search", {"query": query, "tags": "story", "hitsPerPage": MAX_PER_SOURCE})
    if not body:
        return []
    import json

    try:
        hits = json.loads(body).get("hits", [])
    except Exception:
        return []
    return [
        {
            "title": unescape(h.get("title", "")),
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID','')}",
            "snippet": (h.get("title") or "")[:160],
            "points": h.get("points", 0),
        }
        for h in hits
        if h.get("title")
    ]


def _wikipedia(query: str) -> list[dict]:
    body = _get(
        "https://en.wikipedia.org/w/api.php",
        {"action": "opensearch", "search": query, "limit": MAX_PER_SOURCE, "namespace": "0", "format": "json"},
    )
    if not body:
        return []
    import json

    try:
        titles, links, descs, _urls = json.loads(body)
        if not titles or not links:
            return []
        while len(descs) < len(links):
            descs.append("")
    except Exception:
        return []
    return [
        {"title": t, "url": u, "snippet": (d or t)}
        for t, u, d in list(zip(titles, links, descs))[:MAX_PER_SOURCE]
    ]


def _duckduckgo(query: str) -> list[dict]:
    body = _get("https://html.duckduckgo.com/html/", {"q": query})
    if not body:
        return []
    results = []
    for block in re.findall(r'<div class="result results_links.*?>(.*?)</div>\s*</div>', body, re.S)[:MAX_PER_SOURCE]:
        url_m = re.search(r'href="([^"]+)"', block)
        a_m = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.S)
        snip_m = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        if not url_m:
            continue
        href = unescape(url_m.group(1))
        if "y.js" in href or "ad_provider" in href:
            continue  # duckduckgo sponsored links are not market signals
        uddg = re.search(r"[?&]uddg=([^&]+)", href)
        url = unquote(unescape(uddg.group(1))) if uddg else href
        results.append(
            {
                "title": _clean(a_m.group(1)) if a_m else url,
                "url": url,
                "snippet": _clean(snip_m.group(1)) if snip_m else "",
            }
        )
    return results


def _reddit(query: str) -> list[dict]:
    body = _get("https://www.reddit.com/search.json", {"q": query, "limit": MAX_PER_SOURCE, "sort": "relevance"})
    if not body:
        return []
    import json

    try:
        children = json.loads(body)["data"]["children"]
    except Exception:
        return []
    rows = []
    for child in children:
        data = child.get("data", {})
        if data.get("over_18"):
            continue
        rows.append(
            {
                "title": data.get("title", ""),
                "url": f"https://www.reddit.com{data.get('permalink','')}" if data.get("permalink") else "",
                "snippet": _clean(data.get("selftext", "") or data.get("title", "")),
            }
        )
    return rows


_SOURCES = (("hacker_news", _hn), ("wikipedia", _wikipedia), ("duckduckgo", _duckduckgo), ("reddit", _reddit))


def _run_sources(query: str) -> list[dict]:
    """Call every source and flatten their signals into one list."""
    out = []
    for source_name, fetch in _SOURCES:
        try:
            hits = fetch(query)
        except Exception:
            hits = []
        for hit in hits:
            hit = dict(hit)
            hit["source"] = source_name
            out.append(hit)
        time.sleep(0.15)
    return out


def _dedupe(signals: list[dict]) -> list[dict]:
    seen, kept = set(), []
    for sig in signals:
        key = (sig.get("url") or sig.get("title", "")).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(sig)
    return kept


def web_research(query: str) -> str:
    """Scrape public web sources (Hacker News, Wikipedia, DuckDuckGo, Reddit) for
    current signals on a topic and return consolidated, deduplicated findings."""
    query = query.strip()
    if not query:
        return "Error: give a research topic to scrape for."
    signals = _dedupe(_run_sources(query))
    if not signals:
        return f"No usable signals found for '{query}' (all sources unreachable or empty)."
    lines = [
        f"WEB RESEARCH — '{query}': {len(signals)} signals from {len({s['source'] for s in signals})} sources",
    ]
    by_source: dict[str, list] = {}
    for sig in signals:
        by_source.setdefault(sig["source"], []).append(sig)
    for source in ("hacker_news", "wikipedia", "duckduckgo", "reddit"):
        for sig in by_source.get(source, []):
            points = f" (+{sig['points']} votes)" if sig.get("points") else ""
            lines.append(f"  [{source}] {sig['title']}{points}")
            if sig.get("snippet"):
                lines.append(f"      {sig['snippet']}")
            if sig.get("url"):
                lines.append(f"      {sig['url']}")
    lines.append(f"Record this as an idea with record_idea(title=..., summary=..., source_urls={json.dumps([s['url'] for s in signals if s.get('url')][:6])}).")
    return "\n".join(lines)


def _idea_id() -> str:
    return f"IV-{len(STORE.data['ideas']) + 1:03d}"


def record_idea(
    title: str,
    summary: str,
    category: str,
    revenue_model: str,
    source_urls: list,
    signal_strength: float,
    required_capital: float,
    projected_monthly_revenue: float,
    timeframe_months: int,
) -> str:
    """Record a proposed money-making idea distilled from web research so the
    credibility council and probability engine can assess it. The LLM fills this
    from its scraped findings; signal_strength (0..1) is how strong the external
    evidence is, and source_urls must cite where the signal came from."""
    title = title.strip()
    summary = summary.strip()
    if not title or not summary:
        return "Error: title and summary are required."
    if category not in CATEGORIES:
        return f"Error: category must be one of: {', '.join(CATEGORIES)}."
    if revenue_model not in REVENUE_MODELS:
        return f"Error: revenue_model must be one of: {', '.join(REVENUE_MODELS)}."
    urls = [str(u).strip() for u in (source_urls or []) if str(u).strip()]
    try:
        signal = float(signal_strength)
        capital = float(required_capital)
        monthly = float(projected_monthly_revenue)
        months = int(timeframe_months)
    except (TypeError, ValueError):
        return "Error: signal_strength, required_capital, projected_monthly_revenue and timeframe_months must be numbers."
    if not 0.0 <= signal <= 1.0:
        return "Error: signal_strength must be between 0 and 1."
    if capital < 0 or monthly < 0 or not 1 <= months <= 36:
        return "Error: required_capital and projected_monthly_revenue must be >= 0; timeframe_months must be 1..36."
    aid = _idea_id()
    idea = {
        "id": aid,
        "at": STORE.timestamp(),
        "title": title,
        "summary": summary,
        "category": category,
        "revenue_model": revenue_model,
        "source_urls": urls,
        "signal_strength": signal,
        "required_capital": capital,
        "projected_monthly_revenue": monthly,
        "timeframe_months": months,
        "status": "proposed",
        "assessment": None,
        "council": None,
    }
    STORE.data["ideas"].append(idea)
    STORE.notify(f"Opportunity {aid} recorded — '{title}' (signal {signal:.2f}, capital {STORE.currency(capital)}).")
    STORE.save()
    return (
        f"Recorded opportunity {aid}: '{title}' — {summary}\n"
        f"  Category: {category} | revenue model: {revenue_model}\n"
        f"  Signal strength: {signal:.2f} | Sources: {len(urls)} cited\n"
        f"  Required capital: {STORE.currency(capital)} | Projected monthly revenue: {STORE.currency(monthly)} | Timeframe: {months} mo\n"
        f"  Next: assess_idea('{aid}') to run the credibility council and probability engine."
    )


def _idea(idea_id: str) -> dict | None:
    target = str(idea_id).strip().lower()
    for idea in STORE.data["ideas"]:
        if idea["id"].lower() == target:
            return idea
    return None


def list_ideas(status: str = "") -> str:
    """List recorded opportunities, optionally filtered by status (proposed, vetted, funded, implemented, rejected, archived)."""
    entries = STORE.data["ideas"]
    if status:
        entries = [e for e in entries if e["status"].lower() == status.strip().lower()]
    if not entries:
        return "No opportunities recorded yet. Scrape with web_research(query) then record an idea."
    lines = [f"Opportunities ({len(entries)}):"]
    for e in entries:
        epi = e["assessment"]["epi"] if e.get("assessment") else "--"
        lines.append(
            f"  {e['id']} | {e['status']} | EPI {epi} | {e['title']} | capital {STORE.currency(e['required_capital'])} | rev/mo {STORE.currency(e['projected_monthly_revenue'])}"
        )
    return "\n".join(lines)


def archive_idea(idea_id: str) -> str:
    """Remove a proposed opportunity from contention without deleting it."""
    idea = _idea(idea_id)
    if not idea:
        return f"Error: no idea '{idea_id}'."
    if idea["status"] == "funded":
        return f"Error: {idea['id']} has been funded; archive the investment instead."
    idea["status"] = "archived"
    STORE.notify(f"Opportunity {idea['id']} archived.")
    STORE.save()
    return f"Archived {idea['id']}."