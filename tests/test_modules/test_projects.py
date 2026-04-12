"""Tests for the projects module -- tasks, timesheets, helpdesk tickets."""
import pytest
from datetime import date
from unittest.mock import MagicMock, call, patch

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.modules.projects import (
    create_project,
    get_project,
    create_task,
    update_task,
    assign_task,
    set_task_stage,
    search_tasks,
    log_timesheet,
    get_project_summary,
    create_ticket,
    get_tickets,
    update_ticket_stage,
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
    c.write = MagicMock(return_value=True)
    c.read = MagicMock()
    c.search_read = MagicMock(return_value=[])
    c.search_count = MagicMock(return_value=0)
    c.web_url = MagicMock(side_effect=lambda model, rid: f"http://localhost:8069/odoo/{model}/{rid}")
    return c


# ---- create_project ----

class TestCreateProject:
    def test_creates_project_and_returns_id_and_url(self, client):
        client.create.return_value = 10
        result = create_project(client, "My Project")
        client.create.assert_called_once_with("project.project", {"name": "My Project"})
        assert result == {"id": 10, "web_url": "http://localhost:8069/odoo/project.project/10"}

    def test_passes_extra_kwargs(self, client):
        client.create.return_value = 11
        result = create_project(client, "P2", description="desc", partner_id=5)
        client.create.assert_called_once_with(
            "project.project",
            {"name": "P2", "description": "desc", "partner_id": 5},
        )
        assert result["id"] == 11


# ---- get_project ----

class TestGetProject:
    def test_reads_project(self, client):
        client.search_read.return_value = [{"id": 10, "name": "My Project", "partner_id": [1, "Acme"]}]
        result = get_project(client, 10)
        client.search_read.assert_called_with(
            "project.project", [["id", "=", 10]], limit=1,
        )
        assert result == {"id": 10, "name": "My Project", "partner_id": [1, "Acme"]}

    def test_not_found_raises(self, client):
        from openclaw_odoo.errors import OdooRecordNotFoundError
        client.search_read.return_value = []
        with pytest.raises(OdooRecordNotFoundError, match="Project 999 not found"):
            get_project(client, 999)


# ---- create_task ----

class TestCreateTask:
    def test_creates_task_with_project(self, client):
        client.create.return_value = 20
        result = create_task(client, 10, "Fix bug")
        client.create.assert_called_once_with(
            "project.task",
            {"project_id": 10, "name": "Fix bug"},
        )
        assert result == {"id": 20, "web_url": "http://localhost:8069/odoo/project.task/20"}

    def test_creates_task_with_user_ids(self, client):
        client.create.return_value = 21
        result = create_task(client, 10, "Deploy", user_ids=[3, 4])
        client.create.assert_called_once_with(
            "project.task",
            {"project_id": 10, "name": "Deploy", "user_ids": [3, 4]},
        )
        assert result["id"] == 21

    def test_creates_task_with_extra_fields(self, client):
        client.create.return_value = 22
        create_task(client, 10, "Task", priority="1", description="urgent")
        client.create.assert_called_once_with(
            "project.task",
            {"project_id": 10, "name": "Task", "priority": "1", "description": "urgent"},
        )


# ---- update_task ----

class TestUpdateTask:
    def test_writes_values_on_task(self, client):
        result = update_task(client, 20, name="Renamed", priority="1")
        client.write.assert_called_once_with("project.task", [20], {"name": "Renamed", "priority": "1"})
        assert result == {"success": True, "id": 20}


# ---- assign_task ----

class TestAssignTask:
    def test_writes_user_ids(self, client):
        result = assign_task(client, 20, [3, 4])
        client.write.assert_called_once_with("project.task", [20], {"user_ids": [3, 4]})
        assert result == {"success": True, "id": 20}


# ---- set_task_stage ----

class TestSetTaskStage:
    def test_writes_stage_id(self, client):
        result = set_task_stage(client, 20, 5)
        client.write.assert_called_once_with("project.task", [20], {"stage_id": 5})
        assert result == {"success": True, "id": 20}


# ---- search_tasks ----

class TestSearchTasks:
    def test_search_no_filters(self, client):
        client.search_read.return_value = [{"id": 1}, {"id": 2}]
        result = search_tasks(client)
        client.search_read.assert_called_once_with("project.task", domain=[], limit=None)
        assert len(result) == 2

    def test_search_by_project(self, client):
        search_tasks(client, project_id=10)
        args = client.search_read.call_args
        assert ["project_id", "=", 10] in args[1]["domain"]

    def test_search_by_user(self, client):
        search_tasks(client, user_id=3)
        args = client.search_read.call_args
        assert ["user_ids", "in", [3]] in args[1]["domain"]

    def test_search_by_stage(self, client):
        search_tasks(client, stage_id=5)
        args = client.search_read.call_args
        assert ["stage_id", "=", 5] in args[1]["domain"]

    def test_search_with_extra_domain(self, client):
        search_tasks(client, domain=[["priority", "=", "1"]])
        args = client.search_read.call_args
        assert ["priority", "=", "1"] in args[1]["domain"]

    def test_search_with_limit(self, client):
        search_tasks(client, limit=5)
        args = client.search_read.call_args
        assert args[1]["limit"] == 5

    def test_search_combines_all_filters(self, client):
        search_tasks(client, project_id=10, user_id=3, stage_id=5, domain=[["priority", "=", "1"]], limit=10)
        args = client.search_read.call_args
        domain = args[1]["domain"]
        assert ["project_id", "=", 10] in domain
        assert ["user_ids", "in", [3]] in domain
        assert ["stage_id", "=", 5] in domain
        assert ["priority", "=", "1"] in domain
        assert args[1]["limit"] == 10


# ---- log_timesheet ----

class TestLogTimesheet:
    def test_creates_timesheet_entry(self, client):
        client.read.return_value = [{"id": 20, "project_id": [10, "My Project"]}]
        client.create.return_value = 100
        result = log_timesheet(client, 20, 2.5, "Code review")
        # Should read task to get project_id
        client.read.assert_called_once_with("project.task", [20], ["project_id"])
        client.create.assert_called_once_with(
            "account.analytic.line",
            {
                "task_id": 20,
                "project_id": 10,
                "unit_amount": 2.5,
                "name": "Code review",
            },
        )
        assert result["id"] == 100

    def test_with_employee_and_date(self, client):
        client.read.return_value = [{"id": 20, "project_id": [10, "My Project"]}]
        client.create.return_value = 101
        result = log_timesheet(client, 20, 1.0, "Meeting", employee_id=7, date="2026-03-06")
        vals = client.create.call_args[0][1]
        assert vals["employee_id"] == 7
        assert vals["date"] == "2026-03-06"


# ---- get_project_summary ----

class TestGetProjectSummary:
    def test_returns_summary(self, client):
        # tasks with stage info and user_ids (single search_read call now)
        client.search_read.side_effect = [
            [
                {"id": 1, "stage_id": [1, "New"], "user_ids": [1, 3]},
                {"id": 2, "stage_id": [1, "New"], "user_ids": [2]},
                {"id": 3, "stage_id": [2, "In Progress"], "user_ids": [1]},
                {"id": 4, "stage_id": [2, "In Progress"], "user_ids": []},
                {"id": 5, "stage_id": [3, "Done"], "user_ids": []},
            ],
            # timesheets for total_hours
            [
                {"unit_amount": 2.0},
                {"unit_amount": 3.5},
            ],
        ]
        result = get_project_summary(client, 10)
        assert result["task_count"] == 5
        assert result["tasks_by_stage"] == {"New": 2, "In Progress": 2, "Done": 1}
        assert result["total_hours"] == 5.5
        assert result["team_members"] == [1, 2, 3]


# ---- create_ticket ----

class TestCreateTicket:
    def test_creates_helpdesk_ticket(self, client):
        client.create.return_value = 50
        result = create_ticket(client, "Login broken")
        client.create.assert_called_once_with(
            "helpdesk.ticket",
            {"name": "Login broken"},
        )
        assert result["id"] == 50

    def test_creates_ticket_with_project_and_partner(self, client):
        client.create.return_value = 51
        create_ticket(client, "Bug", project_id=10, partner_id=3, priority="2")
        client.create.assert_called_once_with(
            "helpdesk.ticket",
            {"name": "Bug", "project_id": 10, "partner_id": 3, "priority": "2"},
        )

    def test_fallback_to_task_on_error(self, client):
        from openclaw_odoo.errors import OdooAccessError
        client.create.side_effect = [
            OdooAccessError("Model not found: helpdesk.ticket"),
            30,  # fallback project.task create
        ]
        result = create_ticket(client, "Bug report", project_id=10)
        # Second call should be to project.task
        second_call = client.create.call_args_list[1]
        assert second_call[0][0] == "project.task"
        assert "Bug report" in second_call[0][1]["name"]
        assert result["id"] == 30
        assert result.get("fallback") is True

    def test_fallback_on_generic_odoo_claw_error(self, client):
        """When helpdesk.ticket model doesn't exist, Odoo raises OdooClawError
        (not OdooAccessError). The fallback must still trigger."""
        from openclaw_odoo.errors import OdooClawError
        client.create.side_effect = [
            OdooClawError("Object helpdesk.ticket doesn't exist"),
            31,  # fallback project.task create
        ]
        result = create_ticket(client, "Missing model ticket", project_id=5)
        second_call = client.create.call_args_list[1]
        assert second_call[0][0] == "project.task"
        assert result["id"] == 31
        assert result.get("fallback") is True


# ---- get_tickets ----

class TestGetTickets:
    def test_search_tickets(self, client):
        client.search_read.return_value = [{"id": 50, "name": "Ticket 1"}]
        result = get_tickets(client)
        client.search_read.assert_called_once_with("helpdesk.ticket", domain=[], limit=None)
        assert len(result) == 1

    def test_search_tickets_with_filters(self, client):
        get_tickets(client, project_id=10, stage_id=2, limit=5)
        args = client.search_read.call_args
        assert ["project_id", "=", 10] in args[1]["domain"]
        assert ["stage_id", "=", 2] in args[1]["domain"]
        assert args[1]["limit"] == 5


# ---- update_ticket_stage ----

class TestUpdateTicketStage:
    def test_writes_stage_on_ticket(self, client):
        result = update_ticket_stage(client, 50, 3)
        client.write.assert_called_once_with("helpdesk.ticket", [50], {"stage_id": 3})
        assert result == {"success": True, "id": 50}
