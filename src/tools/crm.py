"""CRM and sales domain tools: pipeline visibility and deal-moving actions."""

from src.tools.base import STORE, register_critical


def list_leads() -> str:
    """List all sales leads with their stage and estimated value."""
    text = "\n".join(
        f"  - {lead['id']} | {lead['company']} ({lead['contact']}) | {lead['stage']} | {STORE.currency(lead['value'])}"
        for lead in STORE.data["leads"]
    )
    return f"Leads ({len(STORE.data['leads'])}):\n{text}"


def get_lead(company: str) -> str:
    """Look up a lead by company name."""
    for lead in STORE.data["leads"]:
        if company.lower() in lead["company"].lower():
            return f"{lead['id']} {lead['company']} — contact {lead['contact']}, stage {lead['stage']}, value {STORE.currency(lead['value'])}."
    return f"Error: no lead found matching '{company}'."


def list_opportunities() -> str:
    """List open opportunities with deal value and win probability."""
    text = "\n".join(
        f"  - {op['id']} | {op['account']} | {op['stage']} | {STORE.currency(op['amount'])} | {int(op['probability'] * 100)}%"
        for op in STORE.data["opportunities"]
    )
    return f"Opportunities ({len(STORE.data['opportunities'])}):\n{text}"


def add_lead(company: str, contact: str, value: float) -> str:
    """Add a new sales lead at the 'contacted' stage."""
    if value <= 0:
        return "Error: lead value must be positive."
    leads = STORE.data["leads"]
    new_id = f"L-{len(leads) + 1:02d}"
    leads.append({"id": new_id, "company": company, "contact": contact, "stage": "contacted", "value": value})
    STORE.notify(f"New lead {new_id}: {company} valued at {STORE.currency(value)}.")
    STORE.save()
    return f"Logged lead {new_id} for {company} ({contact}) at {STORE.currency(value)}."


STAGES = ("contacted", "qualified", "proposal", "negotiation", "won", "lost")


def update_lead_stage(lead_id: str, stage: str) -> str:
    """Move a lead to a new pipeline stage (contacted/qualified/proposal/negotiation/won/lost)."""
    stage = stage.lower()
    if stage not in STAGES:
        return f"Error: stage must be one of {', '.join(STAGES)}."
    for lead in STORE.data["leads"]:
        if lead["id"].upper() == lead_id.upper():
            lead["stage"] = stage
            STORE.notify(f"Lead {lead['id']} ({lead['company']}) moved to {stage}.")
            STORE.save()
            return f"Moved lead {lead['id']} to '{stage}'."
    return f"Error: lead {lead_id} not found."


def close_opportunity(opportunity_id: str, won: bool = True) -> str:
    """Close an opportunity as won or lost. High-risk action requiring HITL approval."""
    for op in STORE.data["opportunities"]:
        if op["id"].upper() == opportunity_id.upper():
            op["stage"] = "won" if won else "lost"
            op["probability"] = 1.0 if won else 0.0
            STORE.notify(f"Opportunity {op['id']} ({op['account']}) closed {'won' if won else 'lost'} for {STORE.currency(op['amount'])}.")
            STORE.save()
            return f"Closed opportunity {op['id']} as {'WON' if won else 'LOST'}."
    return f"Error: opportunity {opportunity_id} not found."


register_critical("close_opportunity")