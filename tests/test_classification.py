"""Route classification tests (LLM-free fallback path and JSON extraction)."""

from src.agents.core import _extract_agent, classify, route_by_keywords


class _StubClassifyLLM:
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self.reply)


def test_route_by_keywords_finance():
    assert route_by_keywords("please transfer 5000 to ACME") == "finance"
    assert route_by_keywords("what is our cash balance") == "finance"


def test_route_by_keywords_each_domain():
    assert route_by_keywords("hire a new engineer") == "hr"
    assert route_by_keywords("show open sales leads") == "crm"
    assert route_by_keywords("list project tasks") == "ops"
    assert route_by_keywords("give me the kpi dashboard") == "analytics"
    assert route_by_keywords("schedule a meeting Tuesday") == "comms"
    assert route_by_keywords("assign Nova to the CFO role") == "leadership"
    assert route_by_keywords("show me the org chart") == "leadership"
    assert route_by_keywords("create an ai agent for go-to-market") == "leadership"


def test_route_by_keywords_fallback_to_end():
    assert route_by_keywords("tell me a joke") == "end"


def test_extract_agent_parses_json():
    assert _extract_agent('{"agent": "finance"}') == "finance"
    assert _extract_agent('{"agent": "hr", "note": "ok"}') == "hr"
    assert _extract_agent("finance") == ""


def test_classify_uses_llm_then_falls_back():
    llm = _StubClassifyLLM("I cannot classify that.")
    assert classify(llm, "wire $10k to vendor") == "finance"


def test_classify_keeps_domain_when_llm_hedges_to_end():
    # The model says "end", but the request clearly mentions payroll -> must hit hr.
    llm = _StubClassifyLLM('{"agent": "end"}')
    assert classify(llm, "how much is our annual payroll") == "hr"
    assert classify(llm, "give me the full company overview") == "leadership"


def test_classify_parses_llm_json():
    llm = _StubClassifyLLM('{"agent": "crm"}')
    assert classify(llm, "update our top lead") == "crm"


def test_classify_rejects_unknown_agent():
    llm = _StubClassifyLLM('{"agent": "quantum"}')
    assert classify(llm, "do something exotic") == "end"