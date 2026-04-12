"""Projects module -- project, task, timesheet, and helpdesk ticket operations."""
from __future__ import annotations

from typing import Any, Optional

from ..client import OdooClient
from ..errors import OdooClawError, OdooRecordNotFoundError, OdooAccessError


def create_project(client: OdooClient, name: str, **extra) -> dict:
    """Create a project and return {id, web_url}."""
    vals = {"name": name, **extra}
    record_id = client.create("project.project", vals)
    return {"id": record_id, "web_url": client.web_url("project.project", record_id)}


def get_project(client: OdooClient, project_id: int) -> dict:
    """Fetch a single project by ID.

    Raises:
        OdooRecordNotFoundError: If project does not exist.
    """
    records = client.search_read("project.project", [["id", "=", project_id]], limit=1)
    if not records:
        raise OdooRecordNotFoundError(f"Project {project_id} not found", model="project.project")
    return records[0]


def create_task(client: OdooClient, project_id: int, name: str,
                user_ids: Optional[list[int]] = None, **extra) -> dict:
    """Create a task within a project and return {id, web_url}.

    Args:
        client: OdooClient instance.
        project_id: Parent project record ID.
        name: Task title.
        user_ids: Optional list of assignee user IDs.
        **extra: Additional project.task field values.

    Returns:
        Dict with 'id' and 'web_url' of the created task.
    """
    vals: dict[str, Any] = {"project_id": project_id, "name": name}
    if user_ids is not None:
        vals["user_ids"] = user_ids
    vals.update(extra)
    record_id = client.create("project.task", vals)
    return {"id": record_id, "web_url": client.web_url("project.task", record_id)}


def update_task(client: OdooClient, task_id: int, **values) -> dict:
    """Update a task's fields."""
    client.write("project.task", [task_id], values)
    return {"success": True, "id": task_id}


def assign_task(client: OdooClient, task_id: int, user_ids: list[int]) -> dict:
    """Assign a task to one or more users."""
    client.write("project.task", [task_id], {"user_ids": user_ids})
    return {"success": True, "id": task_id}


def set_task_stage(client: OdooClient, task_id: int, stage_id: int) -> dict:
    """Move a task to a different kanban stage."""
    client.write("project.task", [task_id], {"stage_id": stage_id})
    return {"success": True, "id": task_id}


def search_tasks(client: OdooClient, project_id: Optional[int] = None,
                 user_id: Optional[int] = None, stage_id: Optional[int] = None,
                 domain: Optional[list] = None, limit: Optional[int] = None) -> list[dict]:
    """Search tasks with optional project, user, stage, and domain filters.

    Args:
        client: OdooClient instance.
        project_id: Optional project filter.
        user_id: Optional assignee user filter.
        stage_id: Optional stage filter.
        domain: Optional additional Odoo domain filter.
        limit: Maximum records to return.

    Returns:
        List of matching task dicts.
    """
    filters: list = []
    if project_id is not None:
        filters.append(["project_id", "=", project_id])
    if user_id is not None:
        filters.append(["user_ids", "in", [user_id]])
    if stage_id is not None:
        filters.append(["stage_id", "=", stage_id])
    if domain:
        filters.extend(domain)
    return client.search_read("project.task", domain=filters, limit=limit)


def log_timesheet(client: OdooClient, task_id: int, hours: float,
                  description: str, employee_id: Optional[int] = None,
                  date: Optional[str] = None) -> dict:
    """Log timesheet hours against a task.

    Args:
        client: OdooClient instance.
        task_id: Task record ID.
        hours: Number of hours worked.
        description: Work description.
        employee_id: Optional employee ID (defaults to current user's employee).
        date: Optional ISO date (defaults to today).

    Returns:
        Dict with 'id' and 'web_url' of the created timesheet entry.
    """
    task = client.read("project.task", [task_id], ["project_id"])[0]
    project_id = task["project_id"]
    if isinstance(project_id, (list, tuple)):
        project_id = project_id[0]
    vals: dict[str, Any] = {
        "task_id": task_id,
        "project_id": project_id,
        "unit_amount": hours,
        "name": description,
    }
    if employee_id is not None:
        vals["employee_id"] = employee_id
    if date is not None:
        vals["date"] = date
    record_id = client.create("account.analytic.line", vals)
    return {"id": record_id, "web_url": client.web_url("account.analytic.line", record_id)}


def get_project_summary(client: OdooClient, project_id: int) -> dict:
    """Get a project overview: task count, tasks by stage, total hours, team members.

    Args:
        client: OdooClient instance.
        project_id: Project record ID.

    Returns:
        Dict with task_count, tasks_by_stage, total_hours, team_members.
    """
    tasks = client.search_read("project.task",
                               domain=[["project_id", "=", project_id]],
                               limit=None)
    task_count = len(tasks)

    tasks_by_stage: dict[str, int] = {}
    members: set = set()
    for t in tasks:
        stage = t.get("stage_id")
        if isinstance(stage, (list, tuple)):
            stage_name = stage[1]
        else:
            stage_name = str(stage)
        tasks_by_stage[stage_name] = tasks_by_stage.get(stage_name, 0) + 1

        user_ids = t.get("user_ids", [])
        if isinstance(user_ids, list):
            for uid in user_ids:
                if isinstance(uid, int):
                    members.add(uid)
                elif isinstance(uid, (list, tuple)) and len(uid) >= 1:
                    members.add(uid[0])

    timesheets = client.search_read("account.analytic.line",
                                    domain=[["project_id", "=", project_id]],
                                    limit=None)
    total_hours = sum(ts.get("unit_amount", 0) for ts in timesheets)

    return {
        "task_count": task_count,
        "tasks_by_stage": tasks_by_stage,
        "total_hours": total_hours,
        "team_members": sorted(members),
    }


def create_ticket(client: OdooClient, name: str, project_id: Optional[int] = None,
                  partner_id: Optional[int] = None, **extra) -> dict:
    """Create a helpdesk ticket (falls back to project.task if helpdesk unavailable).

    Args:
        client: OdooClient instance.
        name: Ticket title.
        project_id: Optional helpdesk project ID.
        partner_id: Optional customer partner ID.
        **extra: Additional field values.

    Returns:
        Dict with 'id', 'web_url', and optional 'fallback' flag.
    """
    vals: dict[str, Any] = {"name": name}
    if project_id is not None:
        vals["project_id"] = project_id
    if partner_id is not None:
        vals["partner_id"] = partner_id
    vals.update(extra)

    try:
        record_id = client.create("helpdesk.ticket", vals)
        return {"id": record_id, "web_url": client.web_url("helpdesk.ticket", record_id)}
    except OdooClawError:
        # Helpdesk module not available -- fall back to project.task with tag
        task_vals: dict[str, Any] = {"name": name}
        if project_id is not None:
            task_vals["project_id"] = project_id
        record_id = client.create("project.task", task_vals)
        return {
            "id": record_id,
            "web_url": client.web_url("project.task", record_id),
            "fallback": True,
        }


def get_tickets(client: OdooClient, project_id: Optional[int] = None,
                stage_id: Optional[int] = None, limit: Optional[int] = None) -> list[dict]:
    """Fetch helpdesk tickets with optional project and stage filters."""
    domain: list = []
    if project_id is not None:
        domain.append(["project_id", "=", project_id])
    if stage_id is not None:
        domain.append(["stage_id", "=", stage_id])
    return client.search_read("helpdesk.ticket", domain=domain, limit=limit)


def update_ticket_stage(client: OdooClient, ticket_id: int, stage_id: int) -> dict:
    """Move a helpdesk ticket to a different stage."""
    client.write("helpdesk.ticket", [ticket_id], {"stage_id": stage_id})
    return {"success": True, "id": ticket_id}
