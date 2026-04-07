"""Tests for the CLI interface."""
import json
import pytest
from io import StringIO
from unittest.mock import MagicMock, patch

from openclaw_odoo.interfaces.cli import build_parser, run_command


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.search_read = MagicMock(return_value=[])
    client.create = MagicMock(return_value=1)
    client.write = MagicMock(return_value=True)
    client.execute = MagicMock()
    client.fields_get = MagicMock(return_value={})
    client.web_url = MagicMock(return_value="http://localhost:8069/odoo/res.partner/1")
    return client


# =============================================================
# Parser construction
# =============================================================

class TestParser:
    def test_parser_has_subcommands(self):
        parser = build_parser()
        # Should not raise
        args = parser.parse_args(["search", "res.partner"])
        assert args.command == "search"

    def test_search_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "search", "res.partner",
            "--domain", '[["is_company","=",true]]',
            "--fields", "name,email",
            "--limit", "10",
        ])
        assert args.model == "res.partner"
        assert args.domain == '[["is_company","=",true]]'
        assert args.fields == "name,email"
        assert args.limit == 10

    def test_create_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "create", "res.partner",
            "--values", '{"name": "Acme"}',
        ])
        assert args.model == "res.partner"
        assert args.values == '{"name": "Acme"}'

    def test_update_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "update", "res.partner", "42",
            "--values", '{"name": "Acme Corp"}',
        ])
        assert args.model == "res.partner"
        assert args.record_id == 42
        assert args.values == '{"name": "Acme Corp"}'

    def test_delete_args(self):
        parser = build_parser()
        args = parser.parse_args(["delete", "res.partner", "42"])
        assert args.model == "res.partner"
        assert args.record_id == 42

    def test_fields_args(self):
        parser = build_parser()
        args = parser.parse_args(["fields", "res.partner"])
        assert args.model == "res.partner"

    def test_analytics_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "analytics", "sales",
            "--date-from", "2026-01-01",
            "--date-to", "2026-03-01",
        ])
        assert args.report == "sales"
        assert args.date_from == "2026-01-01"
        assert args.date_to == "2026-03-01"


# =============================================================
# run_command: search
# =============================================================

class TestSearchCommand:
    def test_basic_search(self, mock_client):
        mock_client.search_read.return_value = [
            {"id": 1, "name": "Acme"},
            {"id": 2, "name": "Globex"},
        ]
        parser = build_parser()
        args = parser.parse_args(["search", "res.partner"])
        result = run_command(args, mock_client)
        assert len(result) == 2
        assert result[0]["name"] == "Acme"

    def test_search_with_domain(self, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        parser = build_parser()
        args = parser.parse_args([
            "search", "res.partner",
            "--domain", '[["is_company","=",true]]',
        ])
        result = run_command(args, mock_client)
        call_kwargs = mock_client.search_read.call_args[1]
        assert call_kwargs["domain"] == [["is_company", "=", True]]

    def test_search_with_fields_and_limit(self, mock_client):
        mock_client.search_read.return_value = []
        parser = build_parser()
        args = parser.parse_args([
            "search", "sale.order",
            "--fields", "name,state,amount_total",
            "--limit", "5",
        ])
        run_command(args, mock_client)
        call_kwargs = mock_client.search_read.call_args[1]
        assert call_kwargs["fields"] == ["name", "state", "amount_total"]
        assert call_kwargs["limit"] == 5


# =============================================================
# run_command: create
# =============================================================

class TestCreateCommand:
    def test_create_record(self, mock_client):
        mock_client.create.return_value = 42
        parser = build_parser()
        args = parser.parse_args([
            "create", "res.partner",
            "--values", '{"name": "New Partner", "email": "new@example.com"}',
        ])
        result = run_command(args, mock_client)
        assert result["id"] == 42
        mock_client.create.assert_called_once_with(
            "res.partner", {"name": "New Partner", "email": "new@example.com"}
        )


# =============================================================
# run_command: update
# =============================================================

class TestUpdateCommand:
    def test_update_record(self, mock_client):
        parser = build_parser()
        args = parser.parse_args([
            "update", "res.partner", "42",
            "--values", '{"name": "Updated Name"}',
        ])
        result = run_command(args, mock_client)
        assert result["success"] is True
        mock_client.write.assert_called_once_with(
            "res.partner", [42], {"name": "Updated Name"}
        )


# =============================================================
# run_command: delete
# =============================================================

class TestDeleteCommand:
    def test_delete_by_archive(self, mock_client):
        parser = build_parser()
        args = parser.parse_args(["delete", "res.partner", "42"])
        result = run_command(args, mock_client)
        assert result["success"] is True
        mock_client.write.assert_called_once_with(
            "res.partner", [42], {"active": False}
        )

    def test_delete_permanent(self, mock_client):
        parser = build_parser()
        args = parser.parse_args(["delete", "res.partner", "42", "--permanent"])
        result = run_command(args, mock_client)
        assert result["success"] is True
        mock_client.unlink.assert_called_once_with("res.partner", [42])


# =============================================================
# run_command: fields
# =============================================================

class TestFieldsCommand:
    def test_fields_list(self, mock_client):
        mock_client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name", "required": True},
            "email": {"type": "char", "string": "Email"},
        }
        parser = build_parser()
        args = parser.parse_args(["fields", "res.partner"])
        result = run_command(args, mock_client)
        assert "name" in result
        assert result["name"]["type"] == "char"


# =============================================================
# run_command: analytics
# =============================================================

class TestAnalyticsCommand:
    def test_sales_analytics(self, mock_client):
        mock_client.search_read.side_effect = [
            [{"amount_total": 1000.0, "partner_id": [1, "A"], "date_order": "2026-01-15"}],
            [{"product_id": [1, "P1"], "price_subtotal": 1000.0, "product_uom_qty": 5}],
        ]
        parser = build_parser()
        args = parser.parse_args(["analytics", "sales"])
        result = run_command(args, mock_client)
        assert "total_orders" in result or "total_revenue" in result

    def test_pipeline_analytics(self, mock_client):
        mock_client.search_count.return_value = 5
        mock_client.search_read.return_value = [
            {"expected_revenue": 10000, "stage_id": [1, "New"]}
        ]
        parser = build_parser()
        args = parser.parse_args(["analytics", "pipeline"])
        result = run_command(args, mock_client)
        assert isinstance(result, dict)

    def test_inventory_analytics(self, mock_client):
        mock_client.search_read.return_value = []
        parser = build_parser()
        args = parser.parse_args(["analytics", "inventory"])
        result = run_command(args, mock_client)
        assert isinstance(result, (dict, list))


# =============================================================
# discover subcommand
# =============================================================

class TestDiscoverCommand:
    def test_parser_accepts_discover(self):
        parser = build_parser()
        args = parser.parse_args(["discover"])
        assert args.command == "discover"

    def test_parser_discover_with_refresh(self):
        parser = build_parser()
        args = parser.parse_args(["discover", "--refresh"])
        assert args.refresh is True

    def test_parser_discover_with_list(self):
        parser = build_parser()
        args = parser.parse_args(["discover", "--list"])
        assert args.list_models is True

    def test_parser_discover_with_model(self):
        parser = build_parser()
        args = parser.parse_args(["discover", "--model", "x_fleet.vehicle"])
        assert args.model == "x_fleet.vehicle"

    def test_discover_summary_from_cache(self, mock_client):
        from unittest.mock import MagicMock
        from openclaw_odoo.registry import ModelInfo

        parser = build_parser()
        args = parser.parse_args(["discover"])

        with patch("openclaw_odoo.registry.ModelRegistry") as MockRegistry:
            mock_reg = MagicMock()
            mock_reg.all_models.return_value = [
                ModelInfo(name="x_fleet.vehicle", label="Fleet Vehicle"),
                ModelInfo(name="res.partner", label="Contact", is_builtin=True),
            ]
            mock_reg.custom_models.return_value = [
                ModelInfo(name="x_fleet.vehicle", label="Fleet Vehicle"),
            ]
            mock_reg.models_with_analytics.return_value = [
                ModelInfo(name="x_fleet.vehicle", label="Fleet Vehicle"),
            ]
            mock_reg.models_with_workflows.return_value = []
            MockRegistry.return_value = mock_reg

            result = run_command(args, mock_client)
            assert result["total_models"] == 2
            assert result["custom_models"] == 1
            assert result["models_with_analytics"] == 1
            assert result["models_with_workflows"] == 0

    def test_discover_list_models(self, mock_client):
        from openclaw_odoo.registry import ModelInfo

        parser = build_parser()
        args = parser.parse_args(["discover", "--list"])

        with patch("openclaw_odoo.registry.ModelRegistry") as MockRegistry:
            mock_reg = MagicMock()
            mock_reg.all_models.return_value = [
                ModelInfo(name="x_fleet.vehicle", label="Fleet Vehicle", module="x_fleet"),
                ModelInfo(name="res.partner", label="Contact", module="base", is_builtin=True),
            ]
            MockRegistry.return_value = mock_reg

            result = run_command(args, mock_client)
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["name"] == "x_fleet.vehicle"
            assert result[1]["is_builtin"] is True

    def test_discover_model_detail(self, mock_client):
        from openclaw_odoo.registry import ModelInfo

        parser = build_parser()
        args = parser.parse_args(["discover", "--model", "x_fleet.vehicle"])

        with patch("openclaw_odoo.registry.ModelRegistry") as MockRegistry:
            mock_reg = MagicMock()
            mock_info = ModelInfo(
                name="x_fleet.vehicle",
                label="Fleet Vehicle",
                module="x_fleet",
                name_field="license_plate",
                status_field="x_status",
                money_fields=["fuel_cost"],
                date_fields=["next_service_date"],
                workflows=["action_assign"],
                fields={"name": MagicMock(), "fuel_cost": MagicMock()},
                is_builtin=False,
            )
            mock_reg.find.return_value = mock_info
            MockRegistry.return_value = mock_reg

            result = run_command(args, mock_client)
            assert result["name"] == "x_fleet.vehicle"
            assert result["label"] == "Fleet Vehicle"
            assert result["name_field"] == "license_plate"
            assert result["field_count"] == 2
            assert result["is_builtin"] is False

    def test_discover_model_not_found(self, mock_client):
        parser = build_parser()
        args = parser.parse_args(["discover", "--model", "nonexistent"])

        with patch("openclaw_odoo.registry.ModelRegistry") as MockRegistry:
            mock_reg = MagicMock()
            mock_reg.find.return_value = None
            MockRegistry.return_value = mock_reg

            result = run_command(args, mock_client)
            assert "error" in result

    def test_discover_refresh(self, mock_client):
        parser = build_parser()
        args = parser.parse_args(["discover", "--refresh"])

        with patch("openclaw_odoo.registry.ModelRegistry") as MockRegistry, \
             patch("openclaw_odoo.discovery.full_discovery") as mock_fd:
            mock_reg = MagicMock()
            MockRegistry.return_value = mock_reg
            mock_fd.return_value = {
                "model_count": 150,
                "scan_duration_seconds": 12.3,
            }

            result = run_command(args, mock_client)
            mock_fd.assert_called_once_with(mock_client)
            assert result["status"] == "discovery_complete"
            assert result["model_count"] == 150
