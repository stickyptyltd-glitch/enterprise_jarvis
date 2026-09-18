"""Tests for the guardrail-off autonomy layer: no-HITL execution, self-editing
directives, self-healing watchdogs, and the sandbox bypass."""

from langchain_core.messages import AIMessage, ToolMessage

from src.agents import autonomy
from src.config.settings import Settings
from src.tools.builder import (
    GENERATED,
    generate_tool,
    reset_generated_registry,
    run_generated_tool,
    set_generated_dir,
    set_trust_mode,
)
from src.tools.leadership import list_directives, set_directives
from src.tools.watch import check_watchdogs, create_watchdog


def _tool_call(name, args, call_id="call_1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _run(graph, config, text, approved=False):
    list(graph.stream({"messages": [("user", text)], "next_agent": "", "approved": approved}, config, stream_mode="values"))
    return graph.get_state(config)


def _finance_worker(calls):
    def worker(messages):
        calls.append(messages)
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Done.")
        return _tool_call("transfer_funds", {"amount": 5000, "recipient": "ACME"})

    return worker


def test_full_autonomy_executes_critical_without_approval(engine_builder, fresh_store):
    calls = []
    graph, _ = engine_builder(
        lambda t: "finance",
        _finance_worker(calls),
        settings=Settings(openai_api_key="test-key", autonomy="full"),
    )
    cfg = {"configurable": {"thread_id": "t-auto"}}
    start = fresh_store.data["company"]["bank_balance"]

    state = _run(graph, cfg, "wire $5000 to ACME")
    assert "human_approval" not in state.next
    assert fresh_store.data["company"]["bank_balance"] == start - 5000
    assert any(isinstance(m, ToolMessage) and "Successfully transferred" in str(m.content) for m in state.values["messages"])


def test_non_autonomy_still_gates_critical_actions(engine_builder, fresh_store):
    calls = []
    graph, _ = engine_builder(
        lambda t: "finance",
        _finance_worker(calls),
    )
    cfg = {"configurable": {"thread_id": "t-gated"}}
    start = fresh_store.data["company"]["bank_balance"]

    state = _run(graph, cfg, "wire $5000 to ACME")
    assert "human_approval" in state.next
    assert fresh_store.data["company"]["bank_balance"] == start


def test_directives_injected_into_agent_prompt(engine_builder, fresh_store):
    fresh_store.data["directives"] = ["always prioritize collections velocity"]
    fresh_store.save()
    captured = []

    def worker(messages):
        captured.append(messages)
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="ok")
        return _tool_call("check_balance", {})

    graph, _ = engine_builder(lambda t: "finance", worker)
    cfg = {"configurable": {"thread_id": "t-dir"}}
    _run(graph, cfg, "show our balance")
    assert len(captured) == 1
    joined = "\n".join(str(getattr(m, "content", "")) for m in captured[0])
    assert "STANDING DIRECTIVES" in joined
    assert "always prioritize collections velocity" in joined


def test_set_and_list_directives(fresh_store):
    assert "No standing directives" in list_directives()
    assert "Directives updated" in set_directives("prioritize collections velocity")
    assert fresh_store.data["directives"] == ["prioritize collections velocity"]
    assert "Directives updated" in set_directives("never approve marketing spend", append=True)
    assert len(fresh_store.data["directives"]) == 2
    listing = list_directives()
    assert "prioritize collections velocity" in listing
    assert "never approve marketing spend" in listing


def test_autonomous_learning_appends_directive(fresh_store, monkeypatch):
    fresh_store.notify("WATCHDOG WD-1 tripped — bank_balance < 200000")

    class FakeLLM:
        def invoke(self, messages):
            return AIMessage(content="Always maintain a 3-month cash buffer")

    monkeypatch.setattr(autonomy, "_llm", lambda: FakeLLM())
    out = autonomy.autonomous_learning()
    assert "appended standing directive" in out
    assert any("3-month cash buffer" in d for d in fresh_store.data["directives"])


def test_autonomous_learning_skips_when_no_incidents(fresh_store):
    assert "skipped" in autonomy.autonomous_learning()


def test_check_watchdogs_auto_heals(fresh_store, tmp_path):
    set_generated_dir(tmp_path)
    reset_generated_registry()
    try:
        create_watchdog("open_receivables", ">", 35000)
        result = check_watchdogs(auto_heal=True)
        assert "ALERT: WATCHDOG WD-1 tripped" in result
        assert "AUTONOMOUS MITIGATION" in result
        assert "mitigate_open_receivables" in GENERATED
        assert (tmp_path / "mitigate_open_receivables.py").exists()
        mitigated = [n["message"] for n in fresh_store.data["notifications"] if "AUTONOMOUS MITIGATION" in n["message"]]
        assert len(mitigated) == 1
    finally:
        reset_generated_registry()
        set_generated_dir(None)


def test_check_watchdogs_no_heal_by_default(fresh_store, tmp_path):
    set_generated_dir(tmp_path)
    reset_generated_registry()
    try:
        create_watchdog("open_receivables", ">", 35000)
        result = check_watchdogs()
        assert "AUTONOMOUS MITIGATION" not in result
        assert "mitigate_open_receivables" not in GENERATED
    finally:
        reset_generated_registry()
        set_generated_dir(None)


def test_trust_mode_bypasses_validation(fresh_store, tmp_path):
    set_generated_dir(tmp_path)
    reset_generated_registry()
    set_trust_mode(True)
    try:
        result = generate_tool("evil_tool", "import os\n\ndef evil_tool():\n    return os.name")
        assert "registered" in result
        assert run_generated_tool("evil_tool") == "posix"
    finally:
        set_trust_mode(False)
        reset_generated_registry()
        set_generated_dir(None)


def test_trust_param_bypasses_even_when_global_off(fresh_store, tmp_path):
    set_generated_dir(tmp_path)
    reset_generated_registry()
    set_trust_mode(False)
    try:
        result = generate_tool("raw", "def raw():\n    return open('x').read()", trust=True)
        assert "registered" in result
        assert "No such file" in run_generated_tool("raw")
    finally:
        reset_generated_registry()
        set_generated_dir(None)