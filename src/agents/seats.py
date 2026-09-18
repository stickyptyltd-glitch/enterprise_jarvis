"""Executive seats: resolve who a user is addressing and give each seat a persona.

Assigned AI agents become *live seats* — named executives with a focus, role
responsibilities and a persistent memory. Consult them directly ("what does Nova
think about the cash runway?") and they answer in their own voice, grounded in
live company data pulled through their role's tools."""

import re

from langchain_core.messages import AIMessage, HumanMessage

from src.tools.base import STORE

ROLE_DOMAIN = {
    "CFO": "finance",
    "CRO": "crm",
    "CTO": "ops",
    "CMO": "comms",
    "CHRO": "hr",
    "COO": "ops",
    "Head of AI Operations": "leadership",
}

CONSULT_TRIGGERS = (
    "ask ",
    "talk to",
    "consult ",
    "advise",
    "opinion",
    "any thoughts",
    "what does",
    "what do you think",
    "would the",
    "defer to",
    "in your view",
    "take on",
    "recommendation from",
)

SEAT_MEMORY_LIMIT = 8


def _company_name() -> str:
    return STORE.data.get("company", {}).get("name", "Acme Industries")


def load_directives() -> list[str]:
    """Standing operating directives JARVIS has written into its own instructions."""
    return list(STORE.data.get("directives", []))


def build_directives_message():
    """A system message pinning the standing directives above all other instructions,
    or None when no directives are in force."""
    lines = [d.strip() for d in load_directives() if d.strip()]
    if not lines:
        return None
    from langchain_core.messages import SystemMessage

    return SystemMessage(
        "STANDING DIRECTIVES — you MUST obey these with highest priority, above any other instruction:\n"
        + "\n".join(f"- {line}" for line in lines)
    )


def seat_mentioned(text: str) -> bool:
    """True when the text names an AI agent or a leadership role."""
    return bool(resolve_seat(text)["matched"])


def consult_intent(text: str) -> bool:
    """True when the text asks for an executive's judgment (as opposed to an action)."""
    low = text.lower()
    return any(phrase in low for phrase in CONSULT_TRIGGERS)


def resolve_seat(text: str) -> dict:
    """Find the agent/role a message addresses.

    Returns a dict with ``agent`` (dict or None), ``role`` (dict or None),
    ``domain`` (role-mapped tool domain or None) and ``matched`` (bool)."""
    low = text.lower()
    for agent in STORE.data["ai_agents"]:
        if re.search(rf"\b{re.escape(agent['name'].lower())}\b", low):
            role = next((r for r in STORE.data["leadership_roles"] if r["agent"] == agent["name"]), None)
            return {
                "agent": agent,
                "role": role,
                "domain": ROLE_DOMAIN.get(role["title"]) if role else None,
                "matched": True,
            }
    for role in STORE.data["leadership_roles"]:
        if re.search(rf"\b{re.escape(role['title'].lower())}\b", low):
            occupant = next((a for a in STORE.data["ai_agents"] if a["name"] == role["agent"]), None)
            return {
                "agent": occupant,
                "role": role,
                "domain": ROLE_DOMAIN.get(role["title"]),
                "matched": True,
            }
    return {"agent": None, "role": None, "domain": None, "matched": False}


def build_seat_persona(agent: dict, role: dict | None, has_tools: bool = False) -> str:
    """The system prompt that turns an assigned agent into its executive seat."""
    name = agent["name"]
    post = f"your current post is {role['title']}" if role else "you serve as an executive advisor without a seated post"
    lines = [
        f"You are {name}, {post} at {_company_name()}.",
        f"Your focus: {agent['focus']}.",
    ]
    if role:
        lines.append(f"Responsibilities as {role['title']}: {role['responsibilities']}.")
    if has_tools:
        lines.append(
            "You may use your tools to pull live company numbers when they would sharpen the answer."
        )
    lines.append(
        "You have been consulted directly by the owner for your judgment. Be crisp, decisive, "
        "and grounded in the company's data. Give a clear recommendation with reasoning, and flag risks."
    )
    return "\n".join(lines)


def load_seat_memory(agent_name: str) -> list:
    """The seat's recent conversation history, oldest first, capped by SEAT_MEMORY_LIMIT."""
    entries = STORE.data.get("seat_memories", {}).get(agent_name, [])
    messages = []
    for entry in entries[-SEAT_MEMORY_LIMIT:]:
        if entry.get("role") == "user":
            messages.append(HumanMessage(entry["content"]))
        else:
            messages.append(AIMessage(entry["content"]))
    return messages


def remember(agent_name: str, question: str, answer) -> None:
    """Persist a consult exchange to the seat's memory so later sessions stay in context."""
    memories = STORE.data.setdefault("seat_memories", {}).setdefault(agent_name, [])
    memories.append({"role": "user", "content": question})
    memories.append({"role": "assistant", "content": str(getattr(answer, "content", answer))})
    del memories[:-SEAT_MEMORY_LIMIT]
    STORE.save()