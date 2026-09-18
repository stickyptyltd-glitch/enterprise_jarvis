"""Tests for live executive seats: resolution, routing, persona, memory, tools."""

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.agents.core import DOMAIN_AGENTS, classify
from src.agents.seats import build_seat_persona, consult_intent, load_seat_memory, resolve_seat
from src.tools.leadership import assign_agent_to_role


class _StubClassifyLLM:
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages):
        return AIMessage(content=self.reply)


def _tool_call(name, args, call_id="call_1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _last_ai(messages):
    for m in reversed(messages):
        if getattr(m, "type", "") == "ai":
            return m
    return None


def _run(graph, config, text):
    list(graph.stream({"messages": [("user", text)], "next_agent": "", "approved": False}, config, stream_mode="values"))
    return graph.get_state(config)


def test_consult_domain_is_registered():
    assert "consult" in DOMAIN_AGENTS
    assert "watch" in DOMAIN_AGENTS


def test_resolve_seat_by_agent_name_and_role(fresh_store):
    assign_agent_to_role("Nova", "CFO")
    seat = resolve_seat("what does Nova think about the runway")
    assert seat["agent"]["name"] == "Nova"
    assert seat["role"]["title"] == "CFO"
    assert seat["domain"] == "finance"
    assert seat["matched"] is True

    seat2 = resolve_seat("consult the CFO about expenses")
    assert seat2["agent"]["name"] == "Nova" and seat2["domain"] == "finance"

    seat3 = resolve_seat("consult the CMO about brand")
    assert seat3["matched"] is True and seat3["agent"] is None and seat3["role"]["title"] == "CMO"

    seat4 = resolve_seat("show the org chart")
    assert seat4["matched"] is False


def test_consult_intent_phrases():
    assert consult_intent("what does Nova think about cash?")
    assert consult_intent("talk to Orion about the pipeline")
    assert consult_intent("consult the CTO on the platform")
    assert not consult_intent("assign Nova to the CFO role")
    assert not consult_intent("show the org chart")


def test_classify_seat_routed_before_llm_and_keywords():
    llm = _StubClassifyLLM('{"agent": "end"}')
    assert classify(llm, "what does Nova think about our cash runway") == "consult"
    assert classify(llm, "what does the CFO recommend for payroll") == "consult"
    assert classify(llm, "assign Nova to the CFO role") == "leadership"
    assert classify(llm, "show the org chart") == "leadership"
    assert classify(llm, "wire $10k to vendor") == "finance"
    assert classify(llm, "alert me when balance drops below $200k") == "watch"


def test_seat_persona_and_memory(fresh_store):
    assign_agent_to_role("Nova", "CFO")
    persona = build_seat_persona(fresh_store.data["ai_agents"][0], fresh_store.data["leadership_roles"][0], has_tools=True)
    assert "Nova" in persona and "CFO" in persona and "capital allocation" in persona
    assert fresh_store.data["seat_memories"] == {}


def test_consult_node_answers_and_remembers(engine_builder, fresh_store):
    assign_agent_to_role("Nova", "CFO")
    seen_personas = []
    call_count = []

    def worker(messages):
        call_count.append(1)
        persona = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
        seen_personas.append(persona)
        return AIMessage(content="Nova says: conserve the runway.")

    graph, fake = engine_builder(lambda t: "consult", worker)
    cfg = {"configurable": {"thread_id": "t-consult-1"}}
    state = _run(graph, cfg, "what does Nova think about cash?")
    last = _last_ai(state.values["messages"])
    assert last and last.content == "Nova says: conserve the runway."
    assert any("Nova" in p and "CFO" in p for p in seen_personas)
    memory = fresh_store.data["seat_memories"]["Nova"]
    assert memory[-1]["content"] == "Nova says: conserve the runway."


def test_consult_recalls_prior_seat_memory(engine_builder, fresh_store):
    assign_agent_to_role("Nova", "CFO")
    observed = []

    def worker(messages):
        body = "\n".join(str(getattr(m, "content", "")) for m in messages if not isinstance(m, SystemMessage))
        observed.append(body)
        return AIMessage(content="Noted.")

    graph, fake = engine_builder(lambda t: "consult", worker)
    cfg = {"configurable": {"thread_id": "t-consult-2"}}
    _run(graph, cfg, "what does Nova think about cash?")
    _run(graph, cfg, "what does Nova think now?")
    assert any("what does Nova think about cash?" in body for body in observed)


def test_consult_seat_can_pull_live_data(engine_builder, fresh_store):
    assign_agent_to_role("Nova", "CFO")

    def worker(messages):
        texts = " ".join(str(getattr(m, "content", "")) for m in messages if not isinstance(m, SystemMessage))
        if "balance" in texts.lower():
            return _tool_call("check_balance", {})
        return AIMessage(content="Done.")

    graph, fake = engine_builder(lambda t: "consult", worker)
    cfg = {"configurable": {"thread_id": "t-consult-3"}}
    state = _run(graph, cfg, "what does Nova think about the balance?")
    assert any("Current cash reserve" in str(m.content) for m in state.values["messages"] if isinstance(m, ToolMessage))
    last = _last_ai(state.values["messages"])
    assert last and last.content.startswith("Summary:")


def test_consult_unassigned_role_and_no_seat(engine_builder, fresh_store):
    graph, fake = engine_builder(lambda t: "consult", lambda m: AIMessage(content="unused"))
    cfg = {"configurable": {"thread_id": "t-consult-4"}}

    state = _run(graph, cfg, "consult the CTO about the platform")
    assert "unassigned" in _last_ai(state.values["messages"]).content

    state2 = _run(graph, cfg, "what does your gut say, jarvis?")
    last2 = _last_ai(state2.values["messages"])
    assert "seat" in last2.content.lower() or "assign" in last2.content.lower()