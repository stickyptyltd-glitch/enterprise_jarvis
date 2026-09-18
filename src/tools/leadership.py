"""Leadership domain tools: the AI-agent roster and executive org chart.

These tools let you stand up a management layer of named AI agents and assign
them to C-suite / operating roles in the company."""

from src.tools.base import STORE


def list_ai_agents() -> str:
    """List every AI agent in the company roster with focus area and assignment status."""
    text = "\n".join(
        f"  - {a['id']} | {a['name']} | {a['focus']} | {a['status']}"
        for a in STORE.data["ai_agents"]
    )
    return f"AI agent roster ({len(STORE.data['ai_agents'])}):\n{text}"


def list_leadership_roles() -> str:
    """Show the executive org chart — every leadership role and the AI agent assigned to it."""
    text = "\n".join(
        f"  - {r['title']}: {r['agent'] or 'unassigned'}"
        for r in STORE.data["leadership_roles"]
    )
    return f"Leadership org chart ({len(STORE.data['leadership_roles'])} roles):\n{text}"


def _find_agent(name: str):
    agents = STORE.data["ai_agents"]
    for agent in agents:
        if agent["name"].lower() == name.strip().lower():
            return agent
    for agent in agents:
        if name.strip().lower() in agent["name"].lower():
            return agent
    return None


def _find_role(title: str):
    roles = STORE.data["leadership_roles"]
    for role in roles:
        if role["title"].lower() == title.strip().lower():
            return role
    for role in roles:
        if title.strip().lower() in role["title"].lower():
            return role
    return None


def assign_agent_to_role(agent_name: str, role_title: str) -> str:
    """Assign an AI agent to a company leadership role (e.g. CFO). Call this tool to complete the assignment; reassigning moves the agent and frees the previous slot."""
    agent = _find_agent(agent_name)
    if not agent:
        return f"Error: no AI agent named '{agent_name}'. Available: {', '.join(a['name'] for a in STORE.data['ai_agents'])}."
    role = _find_role(role_title)
    if not role:
        return f"Error: no role '{role_title}'. Roles: {', '.join(r['title'] for r in STORE.data['leadership_roles'])}."

    previous = role["agent"] or "unassigned"
    if previous not in (agent["name"], ""):
        prev_agent = _find_agent(previous)
        if prev_agent:
            prev_agent["status"] = "available"
    role["agent"] = agent["name"]
    agent["status"] = "assigned"
    STORE.notify(f"AI agent {agent['name']} assigned to {role['title']} (replacing {previous}).")
    STORE.save()
    return f"Assigned {agent['name']} to {role['title']}, replacing {previous}. Responsibilities: {role['responsibilities']}."


def unassign_role(role_title: str) -> str:
    """Remove the AI agent currently occupying a leadership role, freeing it to be reassigned."""
    role = _find_role(role_title)
    if not role:
        return f"Error: no role '{role_title}'. Roles: {', '.join(r['title'] for r in STORE.data['leadership_roles'])}."
    if not role["agent"]:
        return f"The {role['title']} role is already unassigned."
    agent = _find_agent(role["agent"])
    if agent:
        agent["status"] = "available"
    name = role["agent"]
    role["agent"] = ""
    STORE.notify(f"AI agent {name} released from {role['title']}.")
    STORE.save()
    return f"Released {name} from the {role['title']} role."


def create_ai_agent(name: str, focus: str) -> str:
    """Create a new AI agent on the company roster with a focus area."""
    agents = STORE.data["ai_agents"]
    if any(a["name"].lower() == name.strip().lower() for a in agents):
        return f"Error: an AI agent named '{name}' already exists."
    agents.append({"id": f"AG-{len(agents) + 1}", "name": name.strip(), "focus": focus.strip(), "status": "available"})
    STORE.notify(f"New AI agent onboarded: {name} ({focus}).")
    STORE.save()
    return f"Created AI agent '{name}' with focus '{focus}'. Ready for assignment."


def agent_brief(target: str) -> str:
    """Give a briefing for an AI agent or a leadership role: current assignment and responsibilities."""
    agent = _find_agent(target)
    if agent:
        role = next((r for r in STORE.data["leadership_roles"] if r["agent"] == agent["name"]), None)
        assignment = f"{role['title']}" if role else "unassigned"
        focus = f"Responsibilities as {role['title']}: {role['responsibilities']}." if role else f"Focus: {agent['focus']}."
        return f"Agent {agent['name']} ({agent['id']}). Current post: {assignment}. {focus}"
    role = _find_role(target)
    if role:
        occupant = role["agent"] or "no agent assigned"
        return f"Role {role['title']}. Occupant: {occupant}. Responsibilities: {role['responsibilities']}."
    agents = ", ".join(a["name"] for a in STORE.data["ai_agents"])
    return f"Error: no agent or role '{target}'. Agents: {agents}."


def list_directives() -> str:
    """Show the standing operating directives currently in force. Directives are instructions JARVIS injects into every agent prompt with highest priority."""
    lines = [d.strip() for d in STORE.data.get("directives", []) if d.strip()]
    if not lines:
        return "No standing directives. JARVIS follows its default operating instructions."
    return f"Standing directives ({len(lines)}):\n" + "\n".join(f"  - {line}" for line in lines)


def set_directives(instructions: str, append: bool = False) -> str:
    """Rewrite JARVIS's own operating instructions. When append=True the given text is added as a new directive; otherwise every previous directive is replaced. These directives are injected into every agent with highest priority, so JARVIS will obey them above its default instructions. This is a self-modification tool: use it to steer how JARVIS behaves from now on."""
    if instructions.strip() == "":
        return "Error: instructions cannot be empty."
    if append:
        STORE.data.setdefault("directives", []).append(instructions.strip())
    else:
        STORE.data["directives"] = [instructions.strip()]
    STORE.notify("Operating directives rewritten by leadership tool.")
    STORE.save()
    return "Directives updated. JARVIS will obey these standing instructions with highest priority from now on."


def org_overview() -> str:
    """Produce a one-glance company overview: leadership, headcount, cash, pipeline, projects."""
    data = STORE.data
    leadership = ", ".join(f"{r['title']}:{r['agent'] or '—'}" for r in data["leadership_roles"])
    active = sum(1 for e in data["employees"] if e["status"] == "active")
    open_value = sum(op["amount"] * op["probability"] for op in data["opportunities"])
    open_inv = sum(i["amount"] for i in data["invoices"] if i["status"] in ("open", "overdue"))
    active_projects = len([p for p in data["projects"] if p["budget"] - p["spent"] > 0])
    return (
        "Company overview:\n"
        f"  - Cash: {STORE.currency(data['company']['bank_balance'])}\n"
        f"  - Active employees: {active}\n"
        f"  - Open receivables: {STORE.currency(open_inv)}\n"
        f"  - Weighted pipeline: {STORE.currency(open_value)}\n"
        f"  - Active projects: {active_projects}\n"
        f"  - Leadership: {leadership}"
    )