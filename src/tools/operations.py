"""Operations / project management domain tools."""

from src.tools.base import STORE, register_critical


def list_projects() -> str:
    """List all projects with owner, budget, and spend to date."""
    text = "\n".join(
        f"  - {p['id']} | {p['name']} | owner {p['owner']} | {STORE.currency(p['spent'])} of {STORE.currency(p['budget'])}"
        for p in STORE.data["projects"]
    )
    return f"Projects ({len(STORE.data['projects'])}):\n{text}"


def list_tasks(project_id: str = "") -> str:
    """List tasks, optionally filtered to a project id."""
    tasks = STORE.data["tasks"]
    if project_id:
        tasks = [t for t in tasks if t["project"].upper() == project_id.upper()]
    if not tasks:
        return "No tasks found."
    text = "\n".join(
        f"  - {t['id']} | {t['project']} | {t['title']} | assignee {t['assignee']} | {t['status']}"
        for t in tasks
    )
    return f"Tasks ({len(tasks)}):\n{text}"


def get_project_status(project_id: str) -> str:
    """Report a project's schedule health and budget burn rate."""
    for p in STORE.data["projects"]:
        if p["id"].upper() == project_id.upper():
            pct = (p["spent"] / p["budget"] * 100) if p["budget"] else 0
            return f"{p['id']} {p['name']}: spent {STORE.currency(p['spent'])} of {STORE.currency(p['budget'])} ({pct:.0f}% burned)."
    return f"Error: project {project_id} not found."


def create_task(project_id: str, title: str) -> str:
    """Create a new task in a project. High-risk action requiring HITL approval."""
    if not any(p["id"].upper() == project_id.upper() for p in STORE.data["projects"]):
        return f"Error: project {project_id} not found."
    tasks = STORE.data["tasks"]
    new_id = f"T-{400 + len(tasks)}"
    tasks.append({"id": new_id, "project": project_id.upper(), "title": title, "assignee": "unassigned", "status": "todo"})
    STORE.notify(f"Task {new_id} created in {project_id.upper()}: {title}.")
    STORE.save()
    return f"Created task {new_id} in {project_id.upper()}: '{title}'."


def assign_task(task_id: str, employee_id: str) -> str:
    """Assign an existing task to an employee. High-risk action requiring HITL approval."""
    emp = next((e for e in STORE.data["employees"] if e["id"].upper() == employee_id.upper()), None)
    if not emp:
        return f"Error: employee {employee_id} not found."
    for t in STORE.data["tasks"]:
        if t["id"].upper() == task_id.upper():
            t["assignee"] = emp["id"]
            STORE.notify(f"Task {t['id']} assigned to {emp['name']}.")
            STORE.save()
            return f"Assigned task {t['id']} to {emp['name']} ({emp['id']})."
    return f"Error: task {task_id} not found."


def update_progress(task_id: str, status: str) -> str:
    """Update a task's status (todo/in_progress/done). High-risk action requiring HITL approval."""
    status = status.lower()
    if status not in ("todo", "in_progress", "done"):
        return "Error: status must be todo, in_progress, or done."
    for t in STORE.data["tasks"]:
        if t["id"].upper() == task_id.upper():
            t["status"] = status
            STORE.notify(f"Task {t['id']} ({t['title']}) set to {status}.")
            STORE.save()
            return f"Task {t['id']} is now '{status}'."
    return f"Error: task {task_id} not found."


register_critical("create_task", "assign_task", "update_progress")