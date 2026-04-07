import pytest
from unittest.mock import MagicMock, patch
from openclaw_odoo.client import OdooClient
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.errors import OdooRecordNotFoundError
from openclaw_odoo.modules.calendar_mod import (
    create_event, get_event, search_events, update_event,
    delete_event, get_today_events, get_upcoming_events,
    MODEL,
)

FAKE_FIELDS_DEF = {
    "id": {"type": "integer"},
    "name": {"type": "char", "required": True},
    "start": {"type": "datetime", "required": True},
    "stop": {"type": "datetime", "required": True},
    "allday": {"type": "boolean"},
    "user_id": {"type": "many2one", "relation": "res.users"},
    "partner_ids": {"type": "many2many", "relation": "res.partner"},
    "event_tz": {"type": "selection"},
    "active": {"type": "boolean"},
    "state": {"type": "selection"},
    "display_name": {"type": "char"},
}


@pytest.fixture
def config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )


@pytest.fixture
def client(config):
    c = OdooClient(config)
    c.create = MagicMock()
    c.write = MagicMock()
    c.search_read = MagicMock()
    c.search_count = MagicMock()
    c.fields_get = MagicMock(return_value=FAKE_FIELDS_DEF)
    c.read = MagicMock()
    c.web_url = MagicMock(return_value="http://localhost:8069/odoo/calendar.event/1")
    return c


# -- create_event --

class TestCreateEvent:
    def test_create_event(self, client):
        """Basic creation with name, start, stop."""
        client.create.return_value = 1
        result = create_event(client, "Team Meeting", "2026-03-10 09:00:00", "2026-03-10 10:00:00")
        client.create.assert_called_once_with(MODEL, {
            "name": "Team Meeting",
            "start": "2026-03-10 09:00:00",
            "stop": "2026-03-10 10:00:00",
        })
        assert result["id"] == 1
        assert "web_url" in result

    def test_create_event_with_attendees(self, client):
        """Verify partner_ids are formatted as [(6, 0, [...])]."""
        client.create.return_value = 2
        client.web_url.return_value = "http://localhost:8069/odoo/calendar.event/2"
        result = create_event(
            client, "Sprint Review",
            "2026-03-10 14:00:00", "2026-03-10 15:00:00",
            partner_ids=[10, 20, 30],
        )
        call_args = client.create.call_args[0]
        values = call_args[1]
        assert values["partner_ids"] == [(6, 0, [10, 20, 30])]
        assert values["name"] == "Sprint Review"
        assert result["id"] == 2


# -- get_event --

class TestGetEvent:
    def test_get_event(self, client):
        """Verify search_read is called with correct domain."""
        client.search_read.return_value = [
            {"id": 5, "name": "Standup", "start": "2026-03-10 09:00:00"},
        ]
        result = get_event(client, 5)
        client.search_read.assert_called_once()
        call_kwargs = client.search_read.call_args
        # domain should filter by id
        domain = call_kwargs[1].get("domain") or call_kwargs[0][1]
        assert ["id", "=", 5] in domain
        assert result["id"] == 5
        assert result["name"] == "Standup"

    def test_get_event_not_found(self, client):
        """Verify OdooRecordNotFoundError is raised when event doesn't exist."""
        client.search_read.return_value = []
        with pytest.raises(OdooRecordNotFoundError):
            get_event(client, 999)


# -- search_events --

class TestSearchEvents:
    def test_search_events(self, client):
        """Basic search with default empty domain."""
        client.search_read.return_value = [
            {"id": 1, "name": "Event A"},
            {"id": 2, "name": "Event B"},
        ]
        result = search_events(client)
        client.fields_get.assert_called_once_with(MODEL)
        assert len(result) == 2

    def test_search_events_with_domain(self, client):
        """Verify custom domain is passed through to search_read."""
        client.search_read.return_value = [{"id": 3, "name": "All Day"}]
        domain = [["allday", "=", True]]
        result = search_events(client, domain=domain, limit=5)
        call_kwargs = client.search_read.call_args
        passed_domain = call_kwargs[1].get("domain") or call_kwargs[0][1]
        assert passed_domain == [["allday", "=", True]]
        passed_limit = call_kwargs[1].get("limit")
        assert passed_limit == 5
        assert len(result) == 1


# -- update_event --

class TestUpdateEvent:
    def test_update_event(self, client):
        """Verify write is called with correct args."""
        client.write.return_value = True
        result = update_event(client, 5, {"name": "Updated Meeting", "allday": True})
        client.write.assert_called_once_with(
            MODEL, [5], {"name": "Updated Meeting", "allday": True},
        )
        assert result["id"] == 5
        assert "web_url" in result


# -- delete_event --

class TestDeleteEvent:
    def test_delete_event(self, client):
        """Verify archive sets active=False."""
        client.write.return_value = True
        result = delete_event(client, 5)
        client.write.assert_called_once_with(MODEL, [5], {"active": False})
        assert result["id"] == 5
        assert result["archived"] is True


# -- get_today_events --

class TestGetTodayEvents:
    @patch("openclaw_odoo.modules.calendar_mod.datetime")
    def test_get_today_events(self, mock_datetime, client):
        """Verify domain has today's date range."""
        from datetime import date as real_date, datetime as real_datetime, timezone as real_tz
        mock_datetime.now.return_value = real_datetime(2026, 3, 10, 8, 0, 0, tzinfo=real_tz.utc)
        client.search_read.return_value = [
            {"id": 1, "name": "Morning Standup", "start": "2026-03-10 09:00:00"},
        ]
        result = get_today_events(client)
        call_kwargs = client.search_read.call_args
        domain = call_kwargs[1].get("domain") or call_kwargs[0][1]
        # Should have start >= today 00:00:00 and start <= today 23:59:59
        assert ["start", ">=", "2026-03-10 00:00:00"] in domain
        assert ["start", "<=", "2026-03-10 23:59:59"] in domain
        assert len(result) == 1


# -- get_upcoming_events --

class TestGetUpcomingEvents:
    @patch("openclaw_odoo.modules.calendar_mod.datetime")
    def test_get_upcoming_events(self, mock_datetime, client):
        """Verify domain covers next N days."""
        from datetime import datetime as real_datetime, timedelta as real_timedelta, timezone as real_tz
        fake_now = real_datetime(2026, 3, 10, 12, 0, 0, tzinfo=real_tz.utc)
        mock_datetime.now.return_value = fake_now
        mock_datetime.side_effect = lambda *a, **k: real_datetime(*a, **k)
        client.search_read.return_value = [
            {"id": 1, "name": "Event A", "start": "2026-03-11 09:00:00"},
            {"id": 2, "name": "Event B", "start": "2026-03-12 14:00:00"},
        ]
        result = get_upcoming_events(client, days=3)
        call_kwargs = client.search_read.call_args
        domain = call_kwargs[1].get("domain") or call_kwargs[0][1]
        # start should be >= now
        assert ["start", ">=", "2026-03-10 12:00:00"] in domain
        # end should be now + 3 days
        end_dt = fake_now + real_timedelta(days=3)
        assert ["start", "<=", end_dt.strftime("%Y-%m-%d %H:%M:%S")] in domain
        # Should request order
        order = call_kwargs[1].get("order")
        assert order == "start asc"
        assert len(result) == 2

    @patch("openclaw_odoo.modules.calendar_mod.datetime")
    def test_get_upcoming_events_default_days(self, mock_datetime, client):
        """Verify 7-day default when days not specified."""
        from datetime import datetime as real_datetime, timedelta as real_timedelta, timezone as real_tz
        fake_now = real_datetime(2026, 3, 10, 8, 0, 0, tzinfo=real_tz.utc)
        mock_datetime.now.return_value = fake_now
        mock_datetime.side_effect = lambda *a, **k: real_datetime(*a, **k)
        client.search_read.return_value = []
        result = get_upcoming_events(client)
        call_kwargs = client.search_read.call_args
        domain = call_kwargs[1].get("domain") or call_kwargs[0][1]
        end_dt = fake_now + real_timedelta(days=7)
        assert ["start", ">=", "2026-03-10 08:00:00"] in domain
        assert ["start", "<=", end_dt.strftime("%Y-%m-%d %H:%M:%S")] in domain
