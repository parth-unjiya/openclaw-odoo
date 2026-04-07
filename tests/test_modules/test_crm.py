"""Tests for CRM module."""
import pytest
from unittest.mock import MagicMock, call

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.modules.crm import (
    create_lead,
    create_opportunity,
    get_pipeline,
    move_stage,
    mark_won,
    mark_lost,
    get_stages,
    analyze_pipeline,
    get_forecast,
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
    c.search_read = MagicMock()
    c.search_count = MagicMock()
    c.execute = MagicMock()
    c.web_url = MagicMock(side_effect=lambda model, rid: f"http://localhost:8069/odoo/{model}/{rid}")
    return c


# --- create_lead ---

class TestCreateLead:
    def test_creates_lead_with_required_fields(self, client):
        client.create.return_value = 1
        result = create_lead(client, "New Lead")
        client.create.assert_called_once_with("crm.lead", {"name": "New Lead"})
        assert result == {"id": 1, "web_url": "http://localhost:8069/odoo/crm.lead/1"}
        client.web_url.assert_called_with("crm.lead", 1)

    def test_creates_lead_with_optional_fields(self, client):
        client.create.return_value = 2
        result = create_lead(
            client, "Lead 2",
            partner_name="Acme Corp",
            email_from="info@acme.com",
            phone="+1234567890",
        )
        client.create.assert_called_once_with("crm.lead", {
            "name": "Lead 2",
            "partner_name": "Acme Corp",
            "email_from": "info@acme.com",
            "phone": "+1234567890",
        })
        assert result["id"] == 2

    def test_creates_lead_with_extra_kwargs(self, client):
        client.create.return_value = 3
        create_lead(client, "Lead 3", description="Important lead")
        call_vals = client.create.call_args[0][1]
        assert call_vals["description"] == "Important lead"


# --- create_opportunity ---

class TestCreateOpportunity:
    def test_creates_opportunity_with_defaults(self, client):
        client.create.return_value = 10
        result = create_opportunity(client, "Big Deal", partner_id=5)
        client.create.assert_called_once_with("crm.lead", {
            "name": "Big Deal",
            "partner_id": 5,
            "expected_revenue": 0,
            "probability": 10,
            "type": "opportunity",
        })
        assert result == {"id": 10, "web_url": "http://localhost:8069/odoo/crm.lead/10"}

    def test_creates_opportunity_with_custom_values(self, client):
        client.create.return_value = 11
        result = create_opportunity(
            client, "Mega Deal", partner_id=7,
            expected_revenue=50000, probability=75,
            tag_ids=[1, 2],
        )
        call_vals = client.create.call_args[0][1]
        assert call_vals["expected_revenue"] == 50000
        assert call_vals["probability"] == 75
        assert call_vals["type"] == "opportunity"
        assert call_vals["tag_ids"] == [1, 2]


# --- get_pipeline ---

class TestGetPipeline:
    def test_returns_opportunities_grouped_by_stage(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "Deal A", "stage_id": [1, "New"]},
            {"id": 2, "name": "Deal B", "stage_id": [1, "New"]},
            {"id": 3, "name": "Deal C", "stage_id": [2, "Qualified"]},
        ]
        result = get_pipeline(client)
        client.search_read.assert_called_once()
        call_kwargs = client.search_read.call_args
        domain = call_kwargs[1].get("domain", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None)
        assert ["type", "=", "opportunity"] in domain

        assert len(result) == 2
        assert result[0]["stage"] == "New"
        assert len(result[0]["opportunities"]) == 2
        assert result[1]["stage"] == "Qualified"
        assert len(result[1]["opportunities"]) == 1

    def test_filters_by_user_id(self, client):
        client.search_read.return_value = []
        get_pipeline(client, user_id=42)
        call_args = client.search_read.call_args
        domain = call_args[1].get("domain", call_args[0][1] if len(call_args[0]) > 1 else None)
        assert ["user_id", "=", 42] in domain


# --- move_stage ---

class TestMoveStage:
    def test_writes_stage_id(self, client):
        client.write.return_value = True
        result = move_stage(client, lead_id=5, stage_id=3)
        client.write.assert_called_once_with("crm.lead", [5], {"stage_id": 3})
        assert result == {"success": True, "lead_id": 5, "stage_id": 3}


# --- mark_won ---

class TestMarkWon:
    def test_calls_action_set_won(self, client):
        client.execute.return_value = True
        result = mark_won(client, lead_id=10)
        client.execute.assert_called_once_with("crm.lead", "action_set_won", [10])
        assert result["success"] is True
        assert result["lead_id"] == 10


# --- mark_lost ---

class TestMarkLost:
    def test_calls_action_set_lost_without_reason(self, client):
        client.execute.return_value = True
        result = mark_lost(client, lead_id=10)
        client.execute.assert_called_once_with(
            "crm.lead", "action_set_lost", [10]
        )
        assert result["success"] is True

    def test_calls_action_set_lost_with_reason(self, client):
        client.execute.return_value = True
        result = mark_lost(client, lead_id=10, lost_reason="Too expensive")
        client.execute.assert_called_once_with(
            "crm.lead", "action_set_lost", [10], lost_reason="Too expensive"
        )
        assert result["lead_id"] == 10


# --- get_stages ---

class TestGetStages:
    def test_returns_stages_ordered_by_sequence(self, client):
        client.search_read.return_value = [
            {"id": 1, "name": "New", "sequence": 1},
            {"id": 2, "name": "Qualified", "sequence": 2},
            {"id": 3, "name": "Proposition", "sequence": 3},
        ]
        result = get_stages(client)
        client.search_read.assert_called_once_with(
            "crm.stage", domain=[], fields=["name", "sequence", "is_won"],
            order="sequence",
        )
        assert len(result) == 3
        assert result[0]["name"] == "New"


# --- analyze_pipeline ---

class TestAnalyzePipeline:
    def test_returns_pipeline_analytics(self, client):
        client.search_count.side_effect = [15, 10]  # leads, opportunities
        # For opportunities with revenue
        client.search_read.side_effect = [
            # active opportunities (for total_revenue)
            [
                {"id": 1, "expected_revenue": 10000, "stage_id": [1, "New"]},
                {"id": 2, "expected_revenue": 20000, "stage_id": [1, "New"]},
                {"id": 3, "expected_revenue": 30000, "stage_id": [2, "Won"]},
            ],
            # won opportunities (for win_rate)
            [
                {"id": 3, "stage_id": [2, "Won"]},
            ],
        ]

        result = analyze_pipeline(client)
        assert result["total_leads"] == 15
        assert result["total_opportunities"] == 10
        assert result["total_revenue"] == 60000
        assert "win_rate" in result
        assert "conversion_per_stage" in result


# --- get_forecast ---

class TestGetForecast:
    def test_returns_weighted_pipeline_value(self, client):
        client.search_read.return_value = [
            {"id": 1, "probability": 50, "expected_revenue": 10000},
            {"id": 2, "probability": 80, "expected_revenue": 20000},
            {"id": 3, "probability": 20, "expected_revenue": 5000},
        ]
        result = get_forecast(client)
        # 50%*10000 + 80%*20000 + 20%*5000 = 5000 + 16000 + 1000 = 22000
        assert result["weighted_revenue"] == 22000.0
        assert result["opportunity_count"] == 3
        assert len(result["opportunities"]) == 3

    def test_returns_zero_for_empty_pipeline(self, client):
        client.search_read.return_value = []
        result = get_forecast(client)
        assert result["weighted_revenue"] == 0.0
        assert result["opportunity_count"] == 0
