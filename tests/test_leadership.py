"""Tests for the AI-agent roster and leadership role assignment tools."""

from src.tools.leadership import (
    agent_brief,
    assign_agent_to_role,
    create_ai_agent,
    list_ai_agents,
    list_leadership_roles,
    org_overview,
    unassign_role,
)


def test_initial_org_chart_unassigned(fresh_store):
    chart = list_leadership_roles()
    assert "CFO" in chart and "unassigned" in chart
    assert "Head of AI Operations" in chart
    roster = list_ai_agents()
    assert "Nova" in roster and "Orion" in roster and "available" in roster


def test_assign_agent_to_role(fresh_store):
    result = assign_agent_to_role("Nova", "CFO")
    assert "Assigned Nova to CFO" in result
    assert "capital allocation" in result
    assert fresh_store.data["leadership_roles"][0]["agent"] == "Nova"
    assert fresh_store.data["ai_agents"][0]["status"] == "assigned"
    assert "CFO:Nova" in org_overview()


def test_reassign_frees_previous_occupant(fresh_store):
    assign_agent_to_role("Nova", "CFO")
    assign_agent_to_role("Atlas", "COO")
    result = assign_agent_to_role("Vertex", "CFO")
    assert "replacing Nova" in result
    assert fresh_store.data["leadership_roles"][0]["agent"] == "Vertex"
    assert any(a["name"] == "Nova" and a["status"] == "available" for a in fresh_store.data["ai_agents"])


def test_unassign_role(fresh_store):
    assign_agent_to_role("Pulse", "CHRO")
    result = unassign_role("CHRO")
    assert "Released Pulse" in result
    assert fresh_store.data["leadership_roles"][4]["agent"] == ""
    assert any(a["name"] == "Pulse" and a["status"] == "available" for a in fresh_store.data["ai_agents"])


def test_create_ai_agent_and_prevent_duplicates(fresh_store):
    created = create_ai_agent("Echo", "customer success")
    assert "Created AI agent 'Echo'" in created
    assert any(a["name"] == "Echo" for a in fresh_store.data["ai_agents"])
    assert "already exists" in create_ai_agent("echo", "duplicate")


def test_assign_rejects_unknown_agent_or_role(fresh_store):
    assert "no AI agent named 'Ghost'" in assign_agent_to_role("Ghost", "CFO")
    assert "no role 'Dictator'" in assign_agent_to_role("Nova", "Dictator")


def test_agent_brief_for_agent_and_role(fresh_store):
    assign_agent_to_role("Orion", "CRO")
    assert "Orion" in agent_brief("orion") and "CRO" in agent_brief("orion")
    assert "no agent assigned" in agent_brief("CMO")
    assert "no agent or role" in agent_brief("Zorp")