"""HR module -- employees, attendance, leaves, expenses, departments."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..client import OdooClient
from ..errors import OdooRecordNotFoundError
from ..fields import select_smart_fields


def create_employee(client: OdooClient, name: str, job_title: Optional[str] = None,
                    department_id: Optional[int] = None, **extra) -> dict:
    """Create an employee and return {id, web_url}.

    Args:
        client: OdooClient instance.
        name: Employee full name.
        job_title: Optional job title.
        department_id: Optional department record ID.
        **extra: Additional hr.employee field values.

    Returns:
        Dict with 'id' and 'web_url' of the created employee.
    """
    vals = {"name": name}
    if job_title is not None:
        vals["job_title"] = job_title
    if department_id is not None:
        vals["department_id"] = department_id
    vals.update(extra)
    rec_id = client.create("hr.employee", vals)
    return {"id": rec_id, "web_url": client.web_url("hr.employee", rec_id)}


def get_employee(client: OdooClient, employee_id: int,
                 smart_fields: bool = True) -> dict:
    """Fetch a single employee by ID.

    Args:
        client: OdooClient instance.
        employee_id: Employee record ID.
        smart_fields: If True, auto-select the most relevant fields.

    Returns:
        Employee record dict.

    Raises:
        OdooRecordNotFoundError: If employee does not exist.
    """
    if smart_fields:
        fields_def = client.fields_get("hr.employee")
        fields = select_smart_fields(fields_def)
    else:
        fields = None
    records = client.search_read("hr.employee", [["id", "=", employee_id]], fields=fields, limit=1)
    if not records:
        raise OdooRecordNotFoundError(f"Employee {employee_id} not found", model="hr.employee")
    return records[0]


def search_employees(client: OdooClient, query: Optional[str] = None,
                     department_id: Optional[int] = None,
                     limit: Optional[int] = None) -> list[dict]:
    """Search employees by name and/or department.

    Args:
        client: OdooClient instance.
        query: Optional name search string (ilike).
        department_id: Optional department filter.
        limit: Maximum records to return.

    Returns:
        List of employee dicts with id, name, job_title, department_id.
    """
    domain = []
    if query:
        domain.append(["name", "ilike", query])
    if department_id is not None:
        domain.append(["department_id", "=", department_id])
    return client.search_read(
        "hr.employee",
        domain=domain,
        fields=["id", "name", "job_title", "department_id"],
        limit=limit,
    )


def update_employee(client: OdooClient, employee_id: int, **values) -> dict:
    """Update an employee's fields."""
    client.write("hr.employee", [employee_id], values)
    return {"success": True, "id": employee_id}


def checkin(client: OdooClient, employee_id: int) -> dict:
    """Record attendance check-in for an employee (current UTC time)."""
    check_in = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rec_id = client.create("hr.attendance", {
        "employee_id": employee_id,
        "check_in": check_in,
    })
    return {"id": rec_id, "employee_id": employee_id, "check_in": check_in}


def checkout(client: OdooClient, employee_id: int) -> dict:
    """Record attendance check-out for an employee's open session.

    Raises:
        OdooRecordNotFoundError: If no open attendance record exists for the employee.
    """
    records = client.search_read(
        "hr.attendance",
        domain=[["employee_id", "=", employee_id], ["check_out", "=", False]],
        fields=["id", "check_in"],
        limit=1,
    )
    if not records:
        raise OdooRecordNotFoundError(f"No open attendance found for employee {employee_id}", model="hr.attendance")
    att = records[0]
    check_out = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    client.write("hr.attendance", [att["id"]], {"check_out": check_out})
    return {"id": att["id"], "check_in": att["check_in"], "check_out": check_out}


def get_attendance(client: OdooClient, employee_id: Optional[int] = None,
                   date_from: Optional[str] = None, date_to: Optional[str] = None) -> list[dict]:
    """Fetch attendance records with optional employee and date filters.

    Args:
        client: OdooClient instance.
        employee_id: Optional employee filter.
        date_from: Optional ISO datetime lower bound for check_in.
        date_to: Optional ISO datetime upper bound for check_in.

    Returns:
        List of attendance dicts with id, employee_id, check_in, check_out.
    """
    domain = []
    if employee_id is not None:
        domain.append(["employee_id", "=", employee_id])
    if date_from:
        domain.append(["check_in", ">=", date_from])
    if date_to:
        domain.append(["check_in", "<=", date_to])
    return client.search_read(
        "hr.attendance",
        domain=domain,
        fields=["id", "employee_id", "check_in", "check_out"],
    )


def request_leave(client: OdooClient, employee_id: int, leave_type_id: int,
                  date_from: str, date_to: str,
                  description: Optional[str] = None) -> dict:
    """Submit a leave request for an employee.

    Args:
        client: OdooClient instance.
        employee_id: Employee record ID.
        leave_type_id: Leave type (holiday_status_id) record ID.
        date_from: Leave start datetime (ISO format).
        date_to: Leave end datetime (ISO format).
        description: Optional leave description/reason.

    Returns:
        Dict with 'id' and 'web_url' of the created leave request.
    """
    # Odoo 19 requires both date-only fields (request_date_from/to) and
    # datetime fields (date_from/to).  Extract date portions before appending
    # time components so Odoo doesn't silently normalise to today.
    request_date_from = date_from[:10]
    request_date_to = date_to[:10]
    if len(date_from) <= 10:
        date_from = f"{date_from} 08:00:00"
    if len(date_to) <= 10:
        date_to = f"{date_to} 17:00:00"
    vals = {
        "employee_id": employee_id,
        "holiday_status_id": leave_type_id,
        "request_date_from": request_date_from,
        "request_date_to": request_date_to,
        "date_from": date_from,
        "date_to": date_to,
    }
    if description:
        vals["name"] = description
    rec_id = client.create("hr.leave", vals)
    return {"id": rec_id, "web_url": client.web_url("hr.leave", rec_id)}


def approve_leave(client: OdooClient, leave_id: int) -> dict:
    """Approve a pending leave request."""
    client.execute("hr.leave", "action_approve", [leave_id])
    return {"success": True, "id": leave_id}


def get_leaves(client: OdooClient, employee_id: Optional[int] = None,
               state: Optional[str] = None) -> list[dict]:
    """Fetch leave requests with optional employee and state filters.

    Args:
        client: OdooClient instance.
        employee_id: Optional employee filter.
        state: Optional state filter (e.g. 'confirm', 'validate').

    Returns:
        List of leave dicts.
    """
    domain = []
    if employee_id is not None:
        domain.append(["employee_id", "=", employee_id])
    if state:
        domain.append(["state", "=", state])
    return client.search_read(
        "hr.leave",
        domain=domain,
        fields=["id", "employee_id", "holiday_status_id", "date_from", "date_to", "state", "name"],
    )


def get_leave_types(client: OdooClient) -> list[dict]:
    """Fetch all available leave types."""
    return client.search_read(
        "hr.leave.type", domain=[], fields=["id", "name"],
    )


def create_expense(client: OdooClient, employee_id: int, name: str,
                   amount: float, product_id: Optional[int] = None, **extra) -> dict:
    """Create an expense record for an employee.

    Args:
        client: OdooClient instance.
        employee_id: Employee record ID.
        name: Expense description.
        amount: Total expense amount.
        product_id: Optional expense category product ID.
        **extra: Additional hr.expense field values.

    Returns:
        Dict with 'id' and 'web_url' of the created expense.
    """
    vals = {
        "employee_id": employee_id,
        "name": name,
        "total_amount_currency": amount,
    }
    if product_id is not None:
        vals["product_id"] = product_id
    vals.update(extra)
    rec_id = client.create("hr.expense", vals)
    return {"id": rec_id, "web_url": client.web_url("hr.expense", rec_id)}


def get_expenses(client: OdooClient, employee_id: Optional[int] = None,
                 state: Optional[str] = None) -> list[dict]:
    """Fetch expense records with optional employee and state filters.

    Args:
        client: OdooClient instance.
        employee_id: Optional employee filter.
        state: Optional state filter (e.g. 'draft', 'reported').

    Returns:
        List of expense dicts.
    """
    domain = []
    if employee_id is not None:
        domain.append(["employee_id", "=", employee_id])
    if state:
        domain.append(["state", "=", state])
    return client.search_read(
        "hr.expense",
        domain=domain,
        fields=["id", "employee_id", "name", "total_amount_currency", "state"],
    )


def submit_expense(client: OdooClient, expense_ids: list[int]) -> dict:
    """Submit one or more expenses for manager approval."""
    client.execute("hr.expense", "action_submit_expenses", expense_ids)
    return {"success": True, "ids": expense_ids}


def get_departments(client: OdooClient) -> list[dict]:
    """Fetch all departments with their manager and parent info."""
    return client.search_read(
        "hr.department", domain=[],
        fields=["id", "name", "manager_id", "parent_id"],
    )


def get_team(client: OdooClient, department_id: int) -> list[dict]:
    """Fetch all employees in a given department."""
    return client.search_read(
        "hr.employee",
        domain=[["department_id", "=", department_id]],
        fields=["id", "name", "job_title", "department_id"],
    )


def get_headcount_summary(client: OdooClient) -> dict:
    """Get headcount breakdown: total, active, inactive, and per department.

    Returns:
        Dict with total_employees, active, inactive, and per_department list.
    """
    total = client.search_count("hr.employee", [])
    active = client.search_count("hr.employee", [["active", "=", True]])
    inactive = total - active
    dept_data = client.execute(
        "hr.employee", "read_group",
        [], ["department_id"], ["department_id"],
    )
    per_department = [
        {"department": rec["department_id"],
         "count": rec.get("__count", rec.get("department_id_count", 0))}
        for rec in dept_data
    ]
    return {
        "total_employees": total,
        "active": active,
        "inactive": inactive,
        "per_department": per_department,
    }
