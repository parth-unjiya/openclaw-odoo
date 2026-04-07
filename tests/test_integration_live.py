"""Integration tests -- run against a real Odoo 19 instance.

Set ODOO_INTEGRATION_TEST=true to enable.
Expects env vars: ODOO_URL, ODOO_DB, ODOO_API_KEY.
"""
import os
import pytest

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient

SKIP_MSG = "Set ODOO_INTEGRATION_TEST=true to run integration tests"
requires_odoo = pytest.mark.skipif(
    os.environ.get("ODOO_INTEGRATION_TEST") != "true",
    reason=SKIP_MSG,
)


@pytest.fixture(scope="module")
def live_config():
    return OdooClawConfig(
        odoo_url=os.environ.get("ODOO_URL", "http://localhost:8069"),
        odoo_db=os.environ.get("ODOO_DB", "odoo_test"),
        odoo_api_key=os.environ.get("ODOO_API_KEY", ""),
    )


@pytest.fixture(scope="module")
def client(live_config):
    return OdooClient(live_config)


@requires_odoo
class TestConnection:
    def test_basic_connection(self, client):
        """Verify we can reach Odoo and authenticate."""
        result = client.search_read("res.company", [], ["name"], limit=1)
        assert len(result) >= 1
        assert "name" in result[0]

    def test_fields_get(self, client):
        """Verify fields_get returns a non-empty schema."""
        fields = client.fields_get("res.partner")
        assert "name" in fields
        assert "email" in fields


@requires_odoo
class TestPartnerCRUD:
    """Create, read, update, archive a partner."""

    _created_id = None

    def test_create_partner(self, client):
        pid = client.create("res.partner", {
            "name": "openclaw-odoo Integration Test Partner",
            "email": "integration-test@openclaw-odoo.dev",
            "is_company": True,
        })
        assert isinstance(pid, int)
        TestPartnerCRUD._created_id = pid

    def test_read_partner(self, client):
        assert self._created_id is not None
        records = client.search_read(
            "res.partner",
            [("id", "=", self._created_id)],
            ["name", "email"],
        )
        assert len(records) == 1
        assert records[0]["name"] == "openclaw-odoo Integration Test Partner"

    def test_update_partner(self, client):
        assert self._created_id is not None
        client.write("res.partner", [self._created_id], {
            "phone": "+1-555-0199",
        })
        records = client.search_read(
            "res.partner",
            [("id", "=", self._created_id)],
            ["phone"],
        )
        assert records[0]["phone"] == "+1-555-0199"

    def test_archive_partner(self, client):
        assert self._created_id is not None
        client.write("res.partner", [self._created_id], {"active": False})
        records = client.search_read(
            "res.partner",
            [("id", "=", self._created_id), ("active", "=", False)],
            ["active"],
        )
        assert len(records) == 1
        assert records[0]["active"] is False


@requires_odoo
class TestSmartCreateQuotation:
    """Smart create with name resolution."""

    def test_smart_quotation(self, client):
        from openclaw_odoo.intelligence.smart_actions import SmartActionHandler

        handler = SmartActionHandler(client)
        result = handler.smart_create_quotation(
            partner="openclaw-odoo Integration Test Partner",
            lines=[{"product": "Desk Combination", "quantity": 1}],
        )
        assert "id" in result
        assert isinstance(result["id"], int)


@requires_odoo
class TestAnalyticsDashboard:
    """Run business dashboard analytics."""

    def test_full_dashboard(self, client):
        from openclaw_odoo.intelligence.analytics import full_business_dashboard

        dashboard = full_business_dashboard(client)
        assert isinstance(dashboard, dict)
        assert "sales" in dashboard or "summary" in dashboard


@requires_odoo
class TestChangeDetection:
    """Poller detects a record change."""

    def test_poll_once_detects_partners(self, client, live_config):
        from openclaw_odoo.realtime.poller import ChangePoller

        poller = ChangePoller(client, config=live_config, models_to_watch=["res.partner"])
        changes = []
        poller.on_change(lambda event, model, records: changes.append(
            (event, model, len(records))
        ))
        # First poll establishes baseline
        poller.poll_once()
        # Second poll should detect nothing (no real change between polls)
        poller.poll_once()
        # We just verify no crash; real change detection needs a write in between
