"""End-to-end engine tests: routing, safe tool execution, and HITL approval/denial."""

from langchain_core.messages import AIMessage, ToolMessage


def _tool_call(name, args, call_id="call_1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _last_ai(messages):
    for m in reversed(messages):
        if getattr(m, "type", "") == "ai":
            return m
    return None


def _fund(store, amount=245000):
    store.data["company"]["bank_balance"] = amount
    store.save()


def _run(graph, config, text, approved=False):
    list(graph.stream({"messages": [("user", text)], "next_agent": "", "approved": approved}, config, stream_mode="values"))
    return graph.get_state(config)


def _finance_worker(calls):
    def worker(messages):
        calls.append(len(messages))
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Worker final.")
        texts = " ".join(str(getattr(m, "content", "")) for m in messages if getattr(m, "type", "") == "human")
        if "balance" in texts.lower():
            return _tool_call("check_balance", {})
        if "transfer" in texts.lower() or "wire" in texts.lower():
            return _tool_call("transfer_funds", {"amount": 5000, "recipient": "ACME"})
        return AIMessage(content="Worker final.")
    return worker


def _finance_classifier(text, calls):
    calls.append(text)
    return "finance" if any(k in text.lower() for k in ("balance", "transfer", "wire", "pay")) else "end"


def test_safe_tool_executes_once_and_answers(engine_builder, fresh_store):
    agent_calls, cls_calls = [], []
    graph, fake = engine_builder(
        lambda t: _finance_classifier(t, cls_calls),
        _finance_worker(agent_calls),
    )
    cfg = {"configurable": {"thread_id": "t-safe"}}
    state = _run(graph, cfg, "what is our balance?")
    msgs = state.values["messages"]
    assert any("Current cash reserve" in str(m.content) for m in msgs if isinstance(m, ToolMessage))
    last = _last_ai(msgs)
    assert last and last.content.startswith("Summary:")
    assert "human_approval" not in state.next
    assert len(agent_calls) == 1, "agent must be invoked exactly once per turn"


def test_direct_answer_when_no_domain_hit(engine_builder):
    agent_calls, cls_calls = [], []
    graph, fake = engine_builder(
        lambda t: _finance_classifier(t, cls_calls),
        _finance_worker(agent_calls),
    )
    cfg = {"configurable": {"thread_id": "t-direct"}}
    state = _run(graph, cfg, "tell me a joke")
    last = _last_ai(state.values["messages"])
    assert last and last.content.startswith("Direct:")
    assert not any(isinstance(m, ToolMessage) for m in state.values["messages"])


def test_critical_wire_transfer_interrupts_for_approval(engine_builder, fresh_store):
    agent_calls, cls_calls = [], []
    graph, fake = engine_builder(
        lambda t: _finance_classifier(t, cls_calls),
        _finance_worker(agent_calls),
    )
    cfg = {"configurable": {"thread_id": "t-wire"}}
    _fund(fresh_store)
    start = fresh_store.data["company"]["bank_balance"]

    state = _run(graph, cfg, "transfer $5000 to ACME")
    assert "human_approval" in state.next
    assert any(isinstance(m, ToolMessage) for m in state.values["messages"]) is False
    assert fresh_store.data["company"]["bank_balance"] == start

    graph.update_state(cfg, {"approved": True}, as_node="human_approval")
    finished = graph.get_state(cfg).next
    list(graph.stream(None, cfg, stream_mode="values"))
    state = graph.get_state(cfg)
    assert [m.type for m in state.values["messages"]][-1] == "ai"
    assert any(isinstance(m, ToolMessage) and "Successfully transferred" in str(m.content) for m in state.values["messages"])
    assert fresh_store.data["company"]["bank_balance"] == start - 5000


def test_critical_transfer_denied_executes_nothing(engine_builder, fresh_store):
    agent_calls, cls_calls = [], []
    graph, fake = engine_builder(
        lambda t: _finance_classifier(t, cls_calls),
        _finance_worker(agent_calls),
    )
    cfg = {"configurable": {"thread_id": "t-deny"}}
    _fund(fresh_store)
    start = fresh_store.data["company"]["bank_balance"]

    state = _run(graph, cfg, "wire $5000 to ACME")
    assert "human_approval" in state.next

    graph.update_state(cfg, {"approved": False}, as_node="human_approval")
    list(graph.stream(None, cfg, stream_mode="values"))
    state = graph.get_state(cfg)
    assert any(isinstance(m, AIMessage) and "Access denied" in str(m.content) for m in state.values["messages"])
    assert fresh_store.data["company"]["bank_balance"] == start
    assert not any(isinstance(m, ToolMessage) and "transfer" in str(m.content).lower() for m in state.values["messages"])


def test_transfers_require_approval_every_turn(engine_builder, fresh_store):
    agent_calls, cls_calls = [], []
    graph, fake = engine_builder(
        lambda t: _finance_classifier(t, cls_calls),
        _finance_worker(agent_calls),
    )
    cfg = {"configurable": {"thread_id": "t-twice"}, "recursion_limit": 10}
    state = _run(graph, cfg, "wire $5000 to ACME")
    assert "human_approval" in state.next
    graph.update_state(cfg, {"approved": True}, as_node="human_approval")
    list(graph.stream(None, cfg, stream_mode="values"))

    state = _run(graph, cfg, "wire $9000 to Contoso")
    assert "human_approval" in state.next, "a fresh turn must always re-require approval"
    graph.update_state(cfg, {"approved": False}, as_node="human_approval")
    list(graph.stream(None, cfg, stream_mode="values"))
    state = graph.get_state(cfg)
    assert any(isinstance(m, AIMessage) and "Access denied" in str(m.content) for m in state.values["messages"])


def _leadership_worker(calls):
    def worker(messages):
        calls.append(len(messages))
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Assignments updated.")
        return _tool_call("assign_agent_to_role", {"agent_name": "Nova", "role_title": "CFO"})

    return worker


def _leadership_classifier(text, calls):
    calls.append(text)
    return "leadership" if any(k in text.lower() for k in ("assign", "org chart", "cfo", "agent")) else "end"


def test_leadership_assignment_runs_without_approval(engine_builder, fresh_store):
    agent_calls, cls_calls = [], []
    graph, fake = engine_builder(
        lambda t: _leadership_classifier(t, cls_calls),
        _leadership_worker(agent_calls),
    )
    cfg = {"configurable": {"thread_id": "t-lead"}}
    state = _run(graph, cfg, "assign an AI agent to the CFO role")
    msgs = state.values["messages"]
    assert "human_approval" not in state.next
    assert any(isinstance(m, ToolMessage) and "Assigned Nova to CFO" in str(m.content) for m in msgs)
    assert fresh_store.data["leadership_roles"][0]["agent"] == "Nova"