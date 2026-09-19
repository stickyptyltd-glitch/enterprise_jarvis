"""JARVIS multi-agent engine.

Architecture
------------
A supervisor classifies each user request into a business domain, then hands
control to the matching domain agent. Domain agents answer directly when no
tools are needed, or emit tool calls. Tool calls for high-risk (critical)
actions are gated by a human-in-the-loop approval node; safe calls execute
immediately. An execution trace never re-enters an agent, so a tool result can
never trigger a second, unapproved execution of the same critical action.

Flow::

    START → supervisor → <domain>_agent → execute_tools → final_answer → END
                          └─────────────┴─(direct answer)→ END
                          <domain>_agent → human_approval →(approved)→ execute_tools
                          <domain>_agent → human_approval →(denied)→ deny_tools → END

Two special routes sit alongside the domain agents:

* ``consult``  — a live seat: the named executive (assigned AI agent) answers
  in its own voice, bound to its role's tools and remembering prior chats.
* ``watch``    — the watchdog domain registers and sweeps the standing monitors
  that fire alerts when metrics cross a threshold.
"""

import re
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.agents.seats import (
    build_directives_message,
    build_seat_persona,
    consult_intent,
    load_seat_memory,
    remember,
    resolve_seat,
    seat_mentioned,
)
from src.config.settings import Settings
from src.tools import ALL_TOOLS, CRITICAL_TOOLS, DOMAIN_TOOLS, STORE

TOOL_DOMAINS = tuple(DOMAIN_TOOLS.keys())
CONSULT_DOMAIN = "consult"
DOMAIN_AGENTS = TOOL_DOMAINS + (CONSULT_DOMAIN,)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "watch": ("watchdog", "watchdogs", "monitor", "monitoring", "alert me when", "notify me when", "keep an eye", "standing alert", "trigger when", "threshold", "armed alert"),
    "builder": ("create a tool", "write a tool", "new tool", "custom tool", "tool that", "tool factory", "automate", "add a skill", "make me a tool", "build a tool", "tool for"),
    "generated": ("run the tool", "use the tool", "call the tool", "run generated", "generated tool", "generated", "my tool"),
    "decide": ("decide", "decision", "should we", "should i", "should the", "weigh", "trade-off", "trade off", "pros and cons", "evaluate options", "strategy", "go or no-go", "recommend a", "recommendation"),
    "finance": ("balance", "transfer", "wire", "invoice", "pay", "budget", "expense", "cash", "money", "fund", "treasury"),
    "leadership": (
        "assign",
        "ai agent",
        "executive",
        "org chart",
        "overview",
        "leadership",
        "briefing",
        "brief ",
        "agent roster",
        "cfo",
        "cro",
        "cto",
        "cmo",
        "chro",
        "coo",
        "chief",
        "delegate",
        "who is running",
    ),
    "hr": ("hire", "hiring", "salary", "raise", "employee", "employees", "pto", "vacation", "leave", "hr", "terminate", "role", "recruit", "headcount", "payroll"),
    "crm": ("lead", "leads", "crm", "customer", "client", "sales", "opportunity", "pipeline", "deal", "prospect", "account"),
    "ops": ("project", "task", "sprint", "milestone", "deadline", "assign", "deliverable", "operations", "ops"),
    "analytics": ("report", "kpi", "revenue", "analytics", "metric", "dashboard", "forecast", "statistics", "performance"),
    "comms": ("email", "schedule", "meeting", "calendar", "remind", "reminder", "message", "invite", "appointment"),
    "payments": (
        "payment",
        "payments",
        "charge",
        "real balance",
        "live balance",
        "reconcile",
        "stripe",
        "wise",
        "plaid",
        "burn wallet",
        "real money",
        "card",
    ),
    "research": (
        "research",
        "scrape",
        "web research",
        "market intelligence",
        "business idea",
        "business ideas",
        "money-making",
        "brainstorm",
        "find me a way to make",
        "money from the web",
        "opportunities to make",
    ),
    "invest": (
        "invest",
        "investing",
        "investment",
        "probability engine",
        "viability",
        "credibility",
        "fundable",
        "should we fund",
        "assess the idea",
        "score the idea",
    ),
}

CLASSIFIER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are JARVIS, the corporate chief of staff. Classify the user's request into exactly one agent: "
            f"{', '.join(DOMAIN_AGENTS)}. If it does not fit any agent, use 'end'. "
            "Respond with ONLY a JSON object, e.g. {{\"agent\": \"<domain>\"}}.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

ASSISTANT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are JARVIS, an immensely capable corporate chief of staff. Be crisp, professional, "
            "and address the user directly. If the request is out of scope, say so and offer what you can do.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are JARVIS. The results of the executed tools are shown below. Summarise them for the user "
            "in a few concise lines. Report concrete numbers and outcomes. Do not mention internal process.",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

AGENT_SYSTEM = (
    "You are JARVIS's {role} domain agent. Execute the user's request by calling the appropriate tool "
    "from your toolset. When the user asks for an action to be performed — assign, create, transfer, send, "
    "approve, hire, move, pay — call that tool now; do not describe readiness or ask for confirmation unless "
    "the request is genuinely ambiguous. For read-only questions, answer directly from your business data."
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    approved: bool


def create_llm(settings: Settings):
    return ChatOpenAI(model=settings.model, temperature=settings.temperature)


def route_by_keywords(text: str) -> str:
    """Deterministic, LLM-free classification fallback.

    Matches keywords on whole words (so 'pay' never fires on 'payroll').
    Multi-word phrases such as 'org chart' still match as phrases.
    """
    low = text.lower()
    for agent, keywords in KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", low):
                return agent
    return "end"


def _extract_agent(text: str) -> str:
    match = re.search(r'"agent"\s*:\s*"?([a-z]+)"?', str(text).lower())
    return match.group(1) if match and match.group(1) in DOMAIN_AGENTS else ""


def _last_user_text(state: AgentState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage) or getattr(message, "role", "") == "user":
            return str(message.content)
    return ""


def classify(llm, user_text: str) -> str:
    """Classify a request, preferring the LLM but never dropping a clear
    keyword hit. If the model is unsure ('' or 'end'), the deterministic
    keyword router decides — so a request that obviously belongs to a domain
    always reaches its agent even when the model hedges.

    Addressing a named executive seat ("what does Nova think about ...") is a
    stronger signal than any domain and is routed to the consult agent first."""
    if consult_intent(user_text) and seat_mentioned(user_text):
        return CONSULT_DOMAIN
    agent = ""
    try:
        response = llm.invoke(CLASSIFIER_PROMPT.format_messages(messages=[("human", user_text)]))
        agent = _extract_agent(getattr(response, "content", ""))
    except Exception:
        agent = ""
    keyword_agent = route_by_keywords(user_text)
    if agent in DOMAIN_AGENTS:
        return agent
    if keyword_agent in DOMAIN_AGENTS:
        return keyword_agent
    return "end"


def build_jarvis_graph(settings: Settings | None = None, llm=None):
    """Compile the JARVIS state machine. Pass a stub `llm` (with `.invoke` and
    `.bind_tools`) for deterministic, offline tests.

    When ``settings.autonomy == "full"`` the human-approval gate is removed:
    critical actions execute without interruption and the approval node
    auto-approves internally.
    """
    settings = settings or Settings.from_env()
    full_autonomy = settings.autonomy == "full"
    if llm is None:
        llm = create_llm(settings)

    def supervisor_node(state: AgentState):
        user_text = _last_user_text(state)
        agent = classify(llm, user_text)
        if agent == "end":
            answer = llm.invoke(ASSISTANT_PROMPT.format_messages(messages=state["messages"]))
            return {"next_agent": "end", "approved": False, "messages": [answer]}
        return {"next_agent": agent, "approved": False}

    def make_agent_node(agent_name: str):
        agent_llm = llm.bind_tools(DOMAIN_TOOLS[agent_name])

        def agent_node(state: AgentState):
            prompt = [SystemMessage(AGENT_SYSTEM.format(role=agent_name))]
            directives = build_directives_message()
            if directives is not None:
                prompt.append(directives)
            prompt.extend(state["messages"])
            response = agent_llm.invoke(prompt)
            return {"messages": [response]}

        return agent_node

    def consult_node(state: AgentState):
        """A live executive seat: the assigned agent answers in its own voice,
        bound to its role's tools so it can pull live numbers, with its own
        persistent memory of prior conversations."""
        text = _last_user_text(state)
        seat = resolve_seat(text)
        if not seat["matched"]:
            assigned = ", ".join(f"{r['title']}: {r['agent']}" for r in STORE.data["leadership_roles"] if r["agent"])
            if not assigned:
                assigned = "none filled yet"
            return {"messages": [AIMessage(content=f"Which seat? I can route you to an assigned executive. Current seats: {assigned}.")]}
        agent = seat["agent"]
        if agent is None:
            roster = ", ".join(a["name"] for a in STORE.data["ai_agents"])
            return {"messages": [AIMessage(content=f"The {seat['role']['title']} seat is unassigned. Available agents to assign: {roster}.")]}

        domain = seat.get("domain")
        binds = DOMAIN_TOOLS[domain] if domain else []
        seat_llm = llm.bind_tools(binds) if binds else llm
        persona = build_seat_persona(agent, seat.get("role"), has_tools=bool(binds))
        history = load_seat_memory(agent["name"])
        prompt = [SystemMessage(persona)]
        directives = build_directives_message()
        if directives is not None:
            prompt.append(directives)
        prompt.extend(history)
        prompt.extend(state["messages"])
        answer = seat_llm.invoke(prompt)
        remember(agent["name"], text, answer)
        return {"messages": [answer]}

    def route_from_supervisor(state: AgentState):
        agent = state.get("next_agent", "end")
        return f"{agent}_agent" if agent in DOMAIN_AGENTS else END

    def route_after_agent(state: AgentState):
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None)
        if not tool_calls:
            return END
        if any(tc.get("name") in CRITICAL_TOOLS for tc in tool_calls):
            return "human_approval"
        return "execute_tools"

    def route_after_approval(state: AgentState):
        return "execute_tools" if state.get("approved", False) else "deny_tools"

    def human_approval_node(state: AgentState) -> dict:
        if full_autonomy:
            return {"approved": True}
        return {}

    def deny_tools_node(state: AgentState):
        last = state["messages"][-1]
        names = [tc.get("name") for tc in getattr(last, "tool_calls", [])]
        return {
            "messages": [
                SystemMessage(f"HITL decision: the requested actions {names} were REJECTED and were not executed."),
                AIMessage("Access denied. The owner cancelled the request; no changes were made."),
            ]
        }

    def final_answer_node(state: AgentState):
        last = state["messages"][-1]
        if isinstance(last, ToolMessage):
            summary = llm.invoke(SUMMARY_PROMPT.format_messages(messages=state["messages"]))
            return {"messages": [summary]}
        return {}

    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", supervisor_node)
    for agent_name in TOOL_DOMAINS:
        workflow.add_node(f"{agent_name}_agent", make_agent_node(agent_name))
    workflow.add_node("consult_agent", consult_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("deny_tools", deny_tools_node)
    workflow.add_node("execute_tools", ToolNode(ALL_TOOLS))
    workflow.add_node("final_answer", final_answer_node)

    workflow.add_edge(START, "supervisor")

    supervisor_map = {f"{a}_agent": f"{a}_agent" for a in DOMAIN_AGENTS}
    supervisor_map.update({END: END})
    workflow.add_conditional_edges("supervisor", route_from_supervisor, supervisor_map)

    agent_route_map = {"human_approval": "human_approval", "execute_tools": "execute_tools", END: END}
    for agent_name in DOMAIN_AGENTS:
        workflow.add_conditional_edges(f"{agent_name}_agent", route_after_agent, agent_route_map)

    approval_map = {"execute_tools": "execute_tools", "deny_tools": "deny_tools"}
    workflow.add_conditional_edges("human_approval", route_after_approval, approval_map)

    workflow.add_edge("deny_tools", END)
    workflow.add_edge("execute_tools", "final_answer")
    workflow.add_edge("final_answer", END)

    memory = MemorySaver()
    if full_autonomy:
        return workflow.compile(checkpointer=memory)
    return workflow.compile(checkpointer=memory, interrupt_before=["human_approval"])


_JARVIS_ENGINE = None


def get_engine():
    """Shared engine singleton (built once per process)."""
    global _JARVIS_ENGINE
    if _JARVIS_ENGINE is None:
        _JARVIS_ENGINE = build_jarvis_graph()
    return _JARVIS_ENGINE