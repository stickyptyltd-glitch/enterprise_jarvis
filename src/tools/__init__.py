"""Tool registry: domain -> callable list, plus the master critical-tool set."""

from src.tools.base import CRITICAL_TOOLS, STORE, set_store
from src.tools.finance import (
    approve_expense,
    check_balance,
    collect_invoice,
    get_cash_flow,
    list_expenses,
    list_invoices,
    pay_invoice,
    receive_funds,
    transfer_funds,
)
from src.tools.human_resources import (
    approve_pto,
    get_employee,
    give_raise,
    hire_employee,
    list_employees,
    list_open_roles,
    list_pto_requests,
    payroll_total,
    terminate_employee,
)
from src.tools.crm import (
    STAGES as CRM_STAGES,
)
from src.tools.crm import (
    add_lead,
    close_opportunity,
    get_lead,
    list_leads,
    list_opportunities,
    update_lead_stage,
)
from src.tools.operations import (
    assign_task,
    create_task,
    get_project_status,
    list_projects,
    list_tasks,
    update_progress,
)
from src.tools.analytics import expense_report, kpi_dashboard, revenue_report
from src.tools.comms import draft_email, list_schedule, schedule_meeting, send_email, send_reminder
from src.tools.leadership import (
    agent_brief,
    assign_agent_to_role,
    create_ai_agent,
    list_ai_agents,
    list_directives,
    list_leadership_roles,
    org_overview,
    set_directives,
    unassign_role,
)
from src.tools.watch import (
    check_watchdogs,
    create_watchdog,
    delete_watchdog,
    list_watchdogs,
    pause_watchdog,
    resume_watchdog,
    watchdog_metrics,
)
from src.tools.builder import (
    delete_tool,
    generate_tool,
    list_generated_tools,
    load_generated_modules,
    run_generated_tool,
    validate_tool,
)
from src.tools.decision import (
    decision_brief,
    decisions_export,
    evaluate_options,
    list_decisions,
    log_decision,
    update_decision_outcome,
)
from src.tools.research import (
    archive_idea,
    list_ideas,
    record_idea,
    web_research,
)
from src.tools.invest import (
    assess_idea,
    implement_idea,
    invest,
    list_investments,
    update_investment_progress,
)

DOMAIN_TOOLS: dict[str, list] = {
    "finance": [check_balance, get_cash_flow, list_invoices, list_expenses, transfer_funds, pay_invoice, approve_expense, receive_funds, collect_invoice],
    "hr": [
        list_employees,
        get_employee,
        list_open_roles,
        list_pto_requests,
        payroll_total,
        give_raise,
        hire_employee,
        approve_pto,
        terminate_employee,
    ],
    "crm": [list_leads, get_lead, list_opportunities, add_lead, update_lead_stage, close_opportunity],
    "ops": [list_projects, list_tasks, get_project_status, create_task, assign_task, update_progress],
    "analytics": [revenue_report, expense_report, kpi_dashboard],
    "comms": [list_schedule, draft_email, schedule_meeting, send_email, send_reminder],
    "leadership": [
        list_ai_agents,
        list_leadership_roles,
        assign_agent_to_role,
        unassign_role,
        create_ai_agent,
        agent_brief,
        org_overview,
        list_directives,
        set_directives,
    ],
    "watch": [
        watchdog_metrics,
        create_watchdog,
        list_watchdogs,
        pause_watchdog,
        resume_watchdog,
        delete_watchdog,
        check_watchdogs,
    ],
    "builder": [
        generate_tool,
        validate_tool,
        delete_tool,
    ],
    "generated": [
        run_generated_tool,
        list_generated_tools,
    ],
    "decide": [
        decision_brief,
        evaluate_options,
        log_decision,
        list_decisions,
        update_decision_outcome,
        decisions_export,
    ],
    "research": [
        web_research,
        record_idea,
        list_ideas,
        archive_idea,
    ],
    "invest": [
        assess_idea,
        invest,
        implement_idea,
        list_investments,
        update_investment_progress,
    ],
}

CRITICAL_TOOLS: set[str] = set(CRITICAL_TOOLS)

ALL_TOOLS: list = [tool for tools in DOMAIN_TOOLS.values() for tool in tools]

load_generated_modules()

__all__ = [
    "DOMAIN_TOOLS",
    "ALL_TOOLS",
    "CRITICAL_TOOLS",
    "STORE",
    "set_store",
    "update_lead_stage",
    "CRM_STAGES",
]