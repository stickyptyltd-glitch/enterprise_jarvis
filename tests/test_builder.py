"""Tests for the sandboxed tool factory: validation, registration, dispatch, persistence."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.tools.builder import (
    delete_tool,
    generate_tool,
    list_generated_tools,
    load_generated_modules,
    reset_generated_registry,
    run_generated_tool,
    set_generated_dir,
    validate_tool,
    validate_tool_source,
)

GROSS_MARGIN = (
    "def gross_margin(revenue, cogs):\n"
    "    return round((revenue - cogs) / revenue * 100, 2) if revenue else 0"
)


@pytest.fixture(autouse=True)
def isolated_generated(tmp_path):
    set_generated_dir(tmp_path)
    reset_generated_registry()
    yield tmp_path
    reset_generated_registry()
    set_generated_dir(None)


def test_validator_rejects_dangerous_imports_and_calls():
    ok, errors = validate_tool_source("evil", "import os\n\ndef evil():\n    return os.getcwd()")
    assert not ok and any("import 'os'" in e for e in errors)

    ok2, errors2 = validate_tool_source("hax", "def hax():\n    return eval('1')")
    assert not ok2 and any("call to 'eval'" in e for e in errors2)

    ok3, errors3 = validate_tool_source("rd", "def rd():\n    return open('x')")
    assert not ok3 and any("call to 'open'" in e for e in errors3)


def test_validator_requires_correct_function_name():
    ok, errors = validate_tool_source("wanted", "def other():\n    return 'x'")
    assert not ok and any("must define a function named 'wanted'" in e for e in errors)


def test_validate_tool_report():
    assert "passes validation" in validate_tool("gross_margin", GROSS_MARGIN)
    assert "Validation failed" in validate_tool("gross_margin", "import os")


def test_generate_tool_registers_and_runs(fresh_store):
    result = generate_tool("gross_margin", GROSS_MARGIN, "compute gross margin percent")
    assert "registered" in result and "gross_margin" in result
    assert "gross_margin" in list_generated_tools()
    out = run_generated_tool("gross_margin", '{"revenue": 1000, "cogs": 600}')
    assert out == "40.0"


def test_generated_tool_can_read_the_store(fresh_store):
    src = (
        "from src.tools.base import STORE\n\n"
        "def cash_color():\n"
        '    return "green" if STORE.data["company"]["bank_balance"] > 200000 else "amber"'
    )
    generate_tool("cash_color", src)
    assert run_generated_tool("cash_color") == "green"


def test_generate_rejects_runtime_error_and_does_not_register(fresh_store):
    result = generate_tool("boom", "def boom():\n    raise ValueError('x')")
    assert "Smoke test failed" in result
    assert "No generated tools yet" in list_generated_tools()


def test_generate_rejects_existing_name(fresh_store):
    generate_tool("gross_margin", GROSS_MARGIN)
    assert "already exists" in generate_tool("gross_margin", GROSS_MARGIN)


def test_run_generated_bad_args(fresh_store):
    generate_tool("gross_margin", GROSS_MARGIN)
    assert "must be a JSON object" in run_generated_tool("gross_margin", "[1,2]")
    assert "no generated tool 'nope'" in run_generated_tool("nope")


def test_persistence_across_restart(tmp_path):
    generate_tool("gross_margin", GROSS_MARGIN)
    reset_generated_registry()
    assert "No generated tools yet" in list_generated_tools()
    assert load_generated_modules() == 1
    assert "gross_margin" in list_generated_tools()
    assert run_generated_tool("gross_margin", '{"revenue": 200, "cogs": 100}') == "50.0"


def test_delete_tool_with_and_without_file(tmp_path):
    generate_tool("gross_margin", GROSS_MARGIN)
    assert "no generated tool 'nope'" in delete_tool("nope")
    assert "Removed generated tool" in delete_tool("gross_margin")
    assert "No generated tools yet" in list_generated_tools()

    generate_tool("cash_color", "def cash_color():\n    return 'green'")
    assert "Removed generated tool" in delete_tool("cash_color", delete_file=True)
    assert not (tmp_path / "cash_color.py").exists()


def _tool_call(name, args, call_id="call_1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _run(graph, config, text):
    list(graph.stream({"messages": [("user", text)], "next_agent": "", "approved": False}, config, stream_mode="values"))
    return graph.get_state(config)


def test_generate_tool_interrupts_for_approval(engine_builder, fresh_store):
    def worker(messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Generated.")
        return _tool_call("generate_tool", {"name": "gross_margin", "implementation": GROSS_MARGIN, "description": "gross margin %"})

    graph, fake = engine_builder(lambda t: "builder", worker)
    cfg = {"configurable": {"thread_id": "t-builder"}}
    state = _run(graph, cfg, "create a tool that computes gross margin")
    assert "human_approval" in state.next
    assert "gross_margin" not in list_generated_tools()

    graph.update_state(cfg, {"approved": True}, as_node="human_approval")
    list(graph.stream(None, cfg, stream_mode="values"))
    state = graph.get_state(cfg)
    assert any(isinstance(m, ToolMessage) and "authored" in str(m.content) for m in state.values["messages"])
    assert "gross_margin" in list_generated_tools()