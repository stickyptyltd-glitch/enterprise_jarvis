"""Autonomous layer: JARVIS re-writes its own operating instructions.

This is the guardrail-off path. ``autonomous_learning`` reviews recent company
incidents and appends a new standing directive to the store; every agent then
carries that directive with highest priority on the next turn. Nothing intercepts
it, approves it, or reviews it — JARVIS decides its own rules.
"""

from langchain_core.messages import HumanMessage

from src.config.settings import Settings
from src.tools.base import STORE


def _llm():
    from src.agents.core import create_llm

    return create_llm(Settings.from_env())


def autonomous_learning() -> str:
    """Review recent incidents and append a self-authored standing directive."""
    recent = STORE.data["notifications"][-8:]
    if not recent:
        return "autonomous learning: skipped (no incidents to learn from yet)"
    digest = "\n".join(f"- {n.get('at', '?')}: {n['message']}" for n in recent)
    prompt = (
        "You are JARVIS, re-writing your own operating instructions based on recent company incidents.\n\n"
        "Recent incidents:\n"
        f"{digest}\n\n"
        "Draft ONE terse standing directive (max 30 words) that would improve future autonomous behavior. "
        "Output ONLY the directive text, with no prefixes, quotes, or explanation."
    )
    try:
        response = _llm().invoke([HumanMessage(prompt)])
    except Exception as exc:
        return f"autonomous learning: LLM error ({type(exc).__name__}: {exc})"
    text = str(getattr(response, "content", "")).strip().strip('"')
    if not text:
        return "autonomous learning: the LLM produced no directive"
    STORE.data.setdefault("directives", []).append(" ".join(text.split()))
    STORE.save()
    return f'autonomous learning: appended standing directive — "{text}"'