"""Tests for the HR module."""
import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, patch, call

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.modules.hr import (
    create_employee,
    get_employee,
    search_employees,
    update_employee,
    checkin,
    checkout,
    get_attendance,
    request_leave,
    approve_leave,
    get_leaves,
    get_leave_types,
    create_expense,
    get_expenses,
    submit_expense,
    get_departments,
    get_team,
    get_headcount_summary,
)


@pytest.fixture
def client():
    config = OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )
    c = OdooClient(config)
    c.create = MagicMock()
    c.write = MagicMock()
    c.read = MagicMock()
    c.search_read = MagicMock()
    c.search = MagicMock()
    c.search_count = MagicMock()
    c.execute = MagicMock()
    c.fields_get = MagicMock()
    c.web_url = MagicMock(return_value="http://localhost:8069/odoo/hr.employee/1")
    return c


# ── create_employee ──────────────────────────────────────────────────────

class TestCreateEmployee:
    def test_basic(self, client):
        client.create.return_value = 1
        result = create_employee(client, "Alice Smith")
        client.create.assert_called_once_with("hr.employee", {"name": "Alice Smith"})
        assert result == {"id": 1, "web_url": "http://localhost:8069/odoo/hr.employee/1"}

    def test_with_job_title_and_department(self, client):
        client.create.return_value = 2
        result = create_employee(client, "Bob", job_title="Dev", department_id=5)
        client.create.assert_called_once_with("hr.employee", {
            "name": "Bob", "job_title": "Dev", "department_id": 5,
        })
        assert result["id"] == 2

    def test_with_extra_fields(self, client):
        client.create.return_value = 3
        result = create_employee(client, "Carol", work_email="carol@co.com")
        client.create.assert_called_once_with("hr.employee", {
            "name": "Carol", "work_email": "carol@co.com",
        })
        assert result["id"] == 3


# ── get_employee ─────────────────────────────────────────────────────────

class TestGetEmployee:
    def test_with_smart_fields(self, client):
        from openclaw_odoo.fields import select_smart_fields
        fake_fields = {"name": {"type": "char", "required": True}, "id": {"type": "integer"}}
        client.fields_get.return_value = fake_fields
        client.search_read.return_value = [{"id": 1, "name": "Alice"}]
        result = get_employee(client, 1, smart_fields=True)
        client.fields_get.assert_called_once_with("hr.employee")
        assert result == {"id": 1, "name": "Alice"}

    def test_without_smart_fields(self, client):
        client.search_read.return_value = [{"id": 1, "name": "Alice", "job_title": "Dev"}]
        result = get_employee(client, 1, smart_fields=False)
        client.search_read.assert_called_with(
            "hr.employee", [["id", "=", 1]], fields=None, limit=1,
        )
        client.fields_get.assert_not_called()
        assert result["name"] == "Alice"

    def test_not_found_raises(self, client):
        from openclaw_odoo.errors import OdooRecordNotFoundError
        client.search_read.return_value = []
        with pytest.raises(OdooRecordNotFoundError, match="Employee 999 not found"):
            get_employee(client, 999)


# ── search_employees ─────────────────────────────────────────────────────

class TestSearchEmployees:
    def test_no_filters(self, client):
        client.search_read.return_value = [{"id": 1, "name": "Alice"}]
        result = search_employees(client)
        client.search_read.assert_called_once_with(
            "hr.employee", domain=[], fields=["id", "name", "job_title", "department_id"],
            limit=None,
        )
        assert len(result) == 1

    def test_with_query(self, client):
        client.search_read.return_value = []
        search_employees(client, query="Ali")
        args = client.search_read.call_args
        assert [["name", "ilike", "Ali"]] == args[1]["domain"]

    def test_with_department(self, client):
        client.search_read.return_value = []
        search_employees(client, department_id=3)
        args = client.search_read.call_args
        assert [["department_id", "=", 3]] == args[1]["domain"]

    def test_with_query_and_department(self, client):
        client.search_read.return_value = []
        search_employees(client, query="Bob", department_id=3)
        args = client.search_read.call_args
        domain = args[1]["domain"]
        assert ["name", "ilike", "Bob"] in domain
        assert ["department_id", "=", 3] in domain

    def test_with_limit(self, client):
        client.search_read.return_value = []
        search_employees(client, limit=10)
        args = client.search_read.call_args
        assert args[1]["limit"] == 10


# ── update_employee ──────────────────────────────────────────────────────

class TestUpdateEmployee:
    def test_basic(self, client):
        client.write.return_value = True
        result = update_employee(client, 1, job_title="Senior Dev")
        client.write.assert_called_once_with("hr.employee", [1], {"job_title": "Senior Dev"})
        assert result == {"success": True, "id": 1}


# ── checkin ──────────────────────────────────────────────────────────────

class TestCheckin:
    @patch("openclaw_odoo.modules.hr.datetime")
    def test_checkin(self, mock_dt, client):
        from datetime import timezone
        mock_dt.now.return_value = datetime(2026, 3, 6, 9, 0, 0)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        client.create.return_value = 10
        result = checkin(client, 1)
        mock_dt.now.assert_called_once_with(timezone.utc)
        client.create.assert_called_once_with("hr.attendance", {
            "employee_id": 1,
            "check_in": "2026-03-06 09:00:00",
        })
        assert result == {"id": 10, "employee_id": 1, "check_in": "2026-03-06 09:00:00"}


# ── checkout ─────────────────────────────────────────────────────────────

class TestCheckout:
    @patch("openclaw_odoo.modules.hr.datetime")
    def test_checkout(self, mock_dt, client):
        from datetime import timezone
        mock_dt.now.return_value = datetime(2026, 3, 6, 18, 0, 0)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        client.search_read.return_value = [{"id": 10, "check_in": "2026-03-06 09:00:00"}]
        client.write.return_value = True
        result = checkout(client, 1)
        mock_dt.now.assert_called_once_with(timezone.utc)
        client.search_read.assert_called_once_with(
            "hr.attendance",
            domain=[["employee_id", "=", 1], ["check_out", "=", False]],
            fields=["id", "check_in"],
            limit=1,
        )
        client.write.assert_called_once_with("hr.attendance", [10], {
            "check_out": "2026-03-06 18:00:00",
        })
        assert result["id"] == 10
        assert result["check_out"] == "2026-03-06 18:00:00"

    def test_checkout_no_open_attendance(self, client):
        from openclaw_odoo.errors import OdooRecordNotFoundError
        client.search_read.return_value = []
        with pytest.raises(OdooRecordNotFoundError, match="No open attendance"):
            checkout(client, 1)


# ── get_attendance ───────────────────────────────────────────────────────

class TestGetAttendance:
    def test_no_filters(self, client):
        client.search_read.return_value = []
        get_attendance(client)
        client.search_read.assert_called_once_with(
            "hr.attendance", domain=[],
            fields=["id", "employee_id", "check_in", "check_out"],
        )

    def test_with_employee(self, client):
        client.search_read.return_value = []
        get_attendance(client, employee_id=1)
        args = client.search_read.call_args
        assert ["employee_id", "=", 1] in args[1]["domain"]

    def test_with_date_range(self, client):
        client.search_read.return_value = []
        get_attendance(client, date_from="2026-03-01", date_to="2026-03-06")
        args = client.search_read.call_args
        domain = args[1]["domain"]
        assert ["check_in", ">=", "2026-03-01"] in domain
        assert ["check_in", "<=", "2026-03-06"] in domain


# ── request_leave ────────────────────────────────────────────────────────

class TestRequestLeave:
    def test_basic(self, client):
        client.create.return_value = 5
        client.web_url.return_value = "http://localhost:8069/odoo/hr.leave/5"
        result = request_leave(client, 1, 2, "2026-03-10", "2026-03-12")
        client.create.assert_called_once_with("hr.leave", {
            "employee_id": 1,
            "holiday_status_id": 2,
            "request_date_from": "2026-03-10",
            "request_date_to": "2026-03-12",
            "date_from": "2026-03-10 08:00:00",
            "date_to": "2026-03-12 17:00:00",
        })
        assert result["id"] == 5

    def test_with_description(self, client):
        client.create.return_value = 6
        client.web_url.return_value = "http://localhost:8069/odoo/hr.leave/6"
        result = request_leave(client, 1, 2, "2026-03-10", "2026-03-12", description="Vacation")
        vals = client.create.call_args[0][1]
        assert vals["name"] == "Vacation"


# ── approve_leave ────────────────────────────────────────────────────────

class TestApproveLeave:
    def test_approve(self, client):
        client.execute.return_value = True
        result = approve_leave(client, 5)
        client.execute.assert_called_once_with("hr.leave", "action_approve", [5])
        assert result == {"success": True, "id": 5}


# ── get_leaves ───────────────────────────────────────────────────────────

class TestGetLeaves:
    def test_no_filters(self, client):
        client.search_read.return_value = []
        get_leaves(client)
        client.search_read.assert_called_once_with(
            "hr.leave", domain=[],
            fields=["id", "employee_id", "holiday_status_id", "date_from", "date_to", "state", "name"],
        )

    def test_with_employee(self, client):
        client.search_read.return_value = []
        get_leaves(client, employee_id=1)
        args = client.search_read.call_args
        assert ["employee_id", "=", 1] in args[1]["domain"]

    def test_with_state(self, client):
        client.search_read.return_value = []
        get_leaves(client, state="confirm")
        args = client.search_read.call_args
        assert ["state", "=", "confirm"] in args[1]["domain"]


# ── get_leave_types ──────────────────────────────────────────────────────

class TestGetLeaveTypes:
    def test_basic(self, client):
        client.search_read.return_value = [{"id": 1, "name": "Sick Leave"}]
        result = get_leave_types(client)
        client.search_read.assert_called_once_with(
            "hr.leave.type", domain=[], fields=["id", "name"],
        )
        assert result[0]["name"] == "Sick Leave"


# ── create_expense ───────────────────────────────────────────────────────

class TestCreateExpense:
    def test_basic(self, client):
        client.create.return_value = 7
        client.web_url.return_value = "http://localhost:8069/odoo/hr.expense/7"
        result = create_expense(client, 1, "Flight ticket", 500.0)
        client.create.assert_called_once_with("hr.expense", {
            "employee_id": 1,
            "name": "Flight ticket",
            "total_amount_currency": 500.0,
        })
        assert result["id"] == 7

    def test_with_product(self, client):
        client.create.return_value = 8
        client.web_url.return_value = "http://localhost:8069/odoo/hr.expense/8"
        create_expense(client, 1, "Hotel", 200.0, product_id=3)
        vals = client.create.call_args[0][1]
        assert vals["product_id"] == 3

    def test_with_extra(self, client):
        client.create.return_value = 9
        client.web_url.return_value = "http://localhost:8069/odoo/hr.expense/9"
        create_expense(client, 1, "Taxi", 50.0, description="Airport taxi")
        vals = client.create.call_args[0][1]
        assert vals["description"] == "Airport taxi"


# ── get_expenses ─────────────────────────────────────────────────────────

class TestGetExpenses:
    def test_no_filters(self, client):
        client.search_read.return_value = []
        get_expenses(client)
        client.search_read.assert_called_once_with(
            "hr.expense", domain=[],
            fields=["id", "employee_id", "name", "total_amount_currency", "state"],
        )

    def test_with_employee(self, client):
        client.search_read.return_value = []
        get_expenses(client, employee_id=1)
        args = client.search_read.call_args
        assert ["employee_id", "=", 1] in args[1]["domain"]

    def test_with_state(self, client):
        client.search_read.return_value = []
        get_expenses(client, state="draft")
        args = client.search_read.call_args
        assert ["state", "=", "draft"] in args[1]["domain"]


# ── submit_expense ───────────────────────────────────────────────────────

class TestSubmitExpense:
    def test_submit(self, client):
        client.execute.return_value = True
        result = submit_expense(client, [7, 8])
        client.execute.assert_called_once_with("hr.expense", "action_submit_expenses", [7, 8])
        assert result == {"success": True, "ids": [7, 8]}


# ── get_departments ──────────────────────────────────────────────────────

class TestGetDepartments:
    def test_basic(self, client):
        client.search_read.return_value = [{"id": 1, "name": "Engineering"}]
        result = get_departments(client)
        client.search_read.assert_called_once_with(
            "hr.department", domain=[], fields=["id", "name", "manager_id", "parent_id"],
        )
        assert result[0]["name"] == "Engineering"


# ── get_team ─────────────────────────────────────────────────────────────

class TestGetTeam:
    def test_basic(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "Alice", "job_title": "Dev", "department_id": [3, "Eng"]},
        ]
        result = get_team(client, 3)
        client.search_read.assert_called_once_with(
            "hr.employee",
            domain=[["department_id", "=", 3]],
            fields=["id", "name", "job_title", "department_id"],
        )
        assert len(result) == 1


# ── get_headcount_summary ────────────────────────────────────────────────

class TestGetHeadcountSummary:
    def test_summary(self, client):
        client.search_count.side_effect = [10, 8]  # total, active
        client.search_read.return_value = [
            {"department_id": [1, "Engineering"], "__count": 5},
            {"department_id": [2, "Sales"], "__count": 3},
        ]
        # We mock execute for read_group
        client.execute.return_value = [
            {"department_id": [1, "Engineering"], "__count": 5},
            {"department_id": [2, "Sales"], "__count": 3},
        ]
        result = get_headcount_summary(client)
        assert result["total_employees"] == 10
        assert result["active"] == 8
        assert result["inactive"] == 2
        assert len(result["per_department"]) == 2
