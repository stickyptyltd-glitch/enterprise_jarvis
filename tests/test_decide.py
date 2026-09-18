"""Tests for the decision engine: metric brief, weighted evaluation, and ledger."""

from langchain_core.messages import AIMessage

from src.agents.core import classify
from src.tools.decision import (
    decision_brief,
    decisions_export,
    evaluate_options,
    list_decisions,
    log_decision,
    update_decision_outcome,
)


class _StubClassifyLLM:
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages):
        return AIMessage(content=self.reply)


def test_decision_brief_grounds_in_live_metrics(fresh_store):
    brief = decision_brief("expand sales team")
    assert "Decision brief — expand sales team" in brief
    assert "Cash balance" in brief and "0.00" in brief
    assert "Monthly payroll" in brief
    assert "runway" in brief
    assert "Open receivables" in brief and "0.00" in brief
    assert "Active watchdogs" in brief


def test_evaluate_options_ranks_by_weighted_score(fresh_store):
    options = ["Hire sales team", "Invest in product", "Cut spend"]
    scores = {
        "Hire sales team": {"cost": 2, "risk": 3, "time_to_impact": 2, "upside": 5, "strategic_fit": 4},
        "Invest in product": {"cost": 3, "risk": 4, "time_to_impact": 4, "upside": 4, "strategic_fit": 5},
        "Cut spend": {"cost": 5, "risk": 2, "time_to_impact": 5, "upside": 1, "strategic_fit": 2},
    }
    result = evaluate_options("resource allocation", options, scores)
    assert "Recommended: Invest in product" in result
    assert result.index("1. Invest in product") < result.index("2. Hire sales team") < result.index("3. Cut spend")


def test_evaluate_options_bad_input(fresh_store):
    assert "missing scores for: A" in evaluate_options("x", ["A"], {})
    assert "unknown criteria ['magic']" in evaluate_options("x", ["A"], {"A": {"magic": 5}})
    assert "must be integers 1" in evaluate_options("x", ["A"], {"A": {"cost": 9}})


def test_decision_ledger_lifecycle(fresh_store):
    logged = log_decision("resource allocation", "Invest in product", "best weighted score and runway fit")
    assert "D-1" in logged
    assert fresh_store.data["decisions"][0]["id"] == "D-1"

    assert "Invest in product" in list_decisions(outcome="pending")
    assert "resource allocation" in list_decisions(topic="resource")
    assert "no decision 'D-99'" in update_decision_outcome("D-99", "success")
    assert "D-1 outcome set to 'success'" in update_decision_outcome("d-1", "success")
    resolved = list_decisions(outcome="success")
    assert "D-1" in resolved and "Invest in product" in resolved
    assert "D-1" in decisions_export()


def test_classify_decision_and_builder_routing():
    llm = _StubClassifyLLM('{"agent": "end"}')
    assert classify(llm, "should we expand into Europe?") == "decide"
    assert classify(llm, "weigh the pros and cons of hiring two engineers") == "decide"
    assert classify(llm, "create a tool that computes gross margin") == "builder"
    assert classify(llm, "make me a tool to flag low margins") == "builder"
    assert classify(llm, "use my new generated tool gross_margin") == "generated"
    assert classify(llm, "what does Nova think about the runway?") == "consult"
    assert classify(llm, "tell me a joke") == "end"