"""HR domain tools: workforce visibility and people-critical actions."""

from src.tools.base import STORE, register_critical


def list_employees() -> str:
    """List all employees with role, salary, and employment status."""
    text = "\n".join(
        f"  - {emp['id']} | {emp['name']} | {emp['role']} | {STORE.currency(emp['salary'])} | {emp['status']}"
        for emp in STORE.data["employees"]
    )
    return f"Employees ({len(STORE.data['employees'])}):\n{text}"


def get_employee(name: str) -> str:
    """Look up a single employee by name."""
    for emp in STORE.data["employees"]:
        if name.lower() in emp["name"].lower():
            return f"{emp['id']} {emp['name']} ({emp['role']}) — {STORE.currency(emp['salary'])}/yr, status {emp['status']}."
    return f"Error: no employee found matching '{name}'."


def list_open_roles() -> str:
    """List open recruitment roles and headcount needs."""
    roles = [r for r in STORE.data["roles"] if r["status"] == "open"]
    text = "\n".join(f"  - {r['id']} | {r['title']} | headcount {r['headcount']}" for r in roles)
    return f"Open roles ({len(roles)}):\n{text}" if roles else "No open roles."


def payroll_total() -> str:
    """Report total annual payroll cost across all active employees."""
    active = [e for e in STORE.data["employees"] if e["status"] == "active"]
    total = sum(e["salary"] for e in active)
    return f"Total annual payroll ({len(active)} active employees): {STORE.currency(total)}/yr."


def list_pto_requests() -> str:
    """List paid-time-off requests awaiting approval."""
    pto = STORE.data.get("pto_requests", [])
    if not pto:
        return "No pending PTO requests."
    text = "\n".join(f"  - {p['id']} | {p['employee']} | {p['days']} days | {p['status']}" for p in pto)
    return f"PTO requests:\n{text}"


def give_raise(employee_id: str, amount: float) -> str:
    """Give an employee an annual salary raise. High-risk action requiring HITL approval."""
    for emp in STORE.data["employees"]:
        if emp["id"].upper() == employee_id.upper():
            if amount <= 0:
                return "Error: raise must be a positive annual amount."
            emp["salary"] = int(emp["salary"] + amount)
            STORE.notify(f"Raise of {STORE.currency(amount)}/yr approved for {emp['name']}.")
            STORE.save()
            return f"Raised {emp['name']}'s salary to {STORE.currency(emp['salary'])}/yr."
    return f"Error: employee {employee_id} not found."


def hire_employee(title: str, salary: float) -> str:
    """Create a new employee record for a hire. High-risk action requiring HITL approval."""
    if salary <= 0:
        return "Error: salary must be positive."
    employees = STORE.data["employees"]
    new_id = f"E-{100 + len(employees):03d}"
    employees.append({"id": new_id, "name": f"New hire ({title})", "role": title, "salary": int(salary), "status": "active"})
    STORE.notify(f"New hire onboarded: {new_id} as {title} at {STORE.currency(salary)}/yr.")
    STORE.save()
    return f"Created employee {new_id} ({title}) at {STORE.currency(salary)}/yr."


def approve_pto(employee_id: str, days: float) -> str:
    """Approve paid time off for an employee. High-risk action requiring HITL approval."""
    if days <= 0:
        return "Error: PTO days must be positive."
    emp = next((e for e in STORE.data["employees"] if e["id"].upper() == employee_id.upper()), None)
    if not emp:
        return f"Error: employee {employee_id} not found."
    req = {"id": f"PTO-{len(STORE.data.get('pto_requests', [])) + 1}", "employee": emp["name"], "days": days, "status": "approved"}
    STORE.data.setdefault("pto_requests", []).append(req)
    STORE.notify(f"PTO of {days} days approved for {emp['name']}.")
    STORE.save()
    return f"Approved {days} days PTO for {emp['name']}."


def terminate_employee(employee_id: str) -> str:
    """Mark an employee as terminated. High-risk action requiring HITL approval."""
    for emp in STORE.data["employees"]:
        if emp["id"].upper() == employee_id.upper():
            if emp["status"] == "terminated":
                return f"Employee {emp['id']} is already terminated."
            emp["status"] = "terminated"
            STORE.notify(f"Employment ended for {emp['name']} ({emp['id']}).")
            STORE.save()
            return f"Employee {emp['name']} ({emp['id']}) has been terminated."
    return f"Error: employee {employee_id} not found."


register_critical("give_raise", "hire_employee", "approve_pto", "terminate_employee")