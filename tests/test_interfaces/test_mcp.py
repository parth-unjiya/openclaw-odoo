"""Tests for the MCP server interface."""
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from openclaw_odoo.interfaces.mcp_server import create_mcp_server


def _tool_text(result) -> str:
    """Extract text from FastMCP ToolResult."""
    return result.content[0].text


def _resource_text(result) -> str:
    """Extract text from FastMCP ResourceResult."""
    return result.contents[0].content


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.config = MagicMock()
    client.config.odoo_url = "http://localhost:8069"
    client.config.odoo_db = "test_db"
    client.config.readonly = False
    client.search_read = MagicMock(return_value=[])
    client.create = MagicMock(return_value=1)
    client.write = MagicMock(return_value=True)
    client.unlink = MagicMock(return_value=True)
    client.execute = MagicMock(return_value=None)
    client.fields_get = MagicMock(return_value={})
    client.web_url = MagicMock(return_value="http://localhost:8069/odoo/res.partner/1")
    return client


@pytest.fixture
def mcp(mock_client):
    return create_mcp_server(mock_client)


# =============================================================
# Tool registration
# =============================================================

class TestToolRegistration:
    @pytest.mark.anyio
    async def test_has_13_tools(self, mcp):
        tools = await mcp.list_tools()
        assert len(tools) == 13

    @pytest.mark.anyio
    async def test_tool_names(self, mcp):
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        expected = {
            "search_records", "count_records", "create_record", "update_record",
            "delete_record", "execute_method", "batch_execute", "smart_action",
            "analyze", "import_file", "export_data", "list_models", "get_fields",
        }
        assert names == expected


# =============================================================
# Resource registration
# =============================================================

class TestResourceRegistration:
    @pytest.mark.anyio
    async def test_server_info_resource(self, mcp, mock_client):
        result = await mcp.read_resource("odoo://server/info")
        content = json.loads(_resource_text(result))
        assert content["url"] == "http://localhost:8069"
        assert content["database"] == "test_db"

    @pytest.mark.anyio
    async def test_models_resource(self, mcp, mock_client):
        mock_client.search_read.return_value = [
            {"model": "res.partner", "name": "Contact"},
            {"model": "sale.order", "name": "Sales Order"},
        ]
        result = await mcp.read_resource("odoo://models")
        content = json.loads(_resource_text(result))
        assert len(content) == 2
        assert content[0]["model"] == "res.partner"

    @pytest.mark.anyio
    async def test_schema_resource_template(self, mcp, mock_client):
        mock_client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name", "required": True},
            "email": {"type": "char", "string": "Email"},
        }
        result = await mcp.read_resource("odoo://schema/res.partner")
        content = json.loads(_resource_text(result))
        assert "name" in content
        assert content["name"]["type"] == "char"


# =============================================================
# Tool: search_records
# =============================================================

class TestSearchRecords:
    @pytest.mark.anyio
    async def test_basic_search(self, mcp, mock_client):
        mock_client.search_read.return_value = [
            {"id": 1, "name": "Acme"},
            {"id": 2, "name": "Globex"},
        ]
        result = await mcp.call_tool("search_records", {
            "model": "res.partner",
        })
        text = _tool_text(result)
        data = json.loads(text)
        assert len(data) == 2
        mock_client.search_read.assert_called_once()

    @pytest.mark.anyio
    async def test_search_with_domain_fields_limit(self, mcp, mock_client):
        mock_client.search_read.return_value = [{"id": 1, "name": "Acme"}]
        await mcp.call_tool("search_records", {
            "model": "res.partner",
            "domain": [["is_company", "=", True]],
            "fields": ["name", "email"],
            "limit": 10,
        })
        call_kwargs = mock_client.search_read.call_args
        assert call_kwargs[1]["domain"] == [["is_company", "=", True]]
        assert call_kwargs[1]["fields"] == ["name", "email"]
        assert call_kwargs[1]["limit"] == 10


# =============================================================
# Tool: create_record
# =============================================================

class TestCreateRecord:
    @pytest.mark.anyio
    async def test_create(self, mcp, mock_client):
        mock_client.create.return_value = 42
        result = await mcp.call_tool("create_record", {
            "model": "res.partner",
            "values": {"name": "New Partner", "email": "new@example.com"},
        })
        data = json.loads(_tool_text(result))
        assert data["id"] == 42
        mock_client.create.assert_called_once_with(
            "res.partner", {"name": "New Partner", "email": "new@example.com"}
        )


# =============================================================
# Tool: update_record
# =============================================================

class TestUpdateRecord:
    @pytest.mark.anyio
    async def test_update(self, mcp, mock_client):
        result = await mcp.call_tool("update_record", {
            "model": "res.partner",
            "record_id": 42,
            "values": {"name": "Updated Name"},
        })
        data = json.loads(_tool_text(result))
        assert data["success"] is True
        mock_client.write.assert_called_once_with(
            "res.partner", [42], {"name": "Updated Name"}
        )


# =============================================================
# Tool: delete_record
# =============================================================

class TestDeleteRecord:
    @pytest.mark.anyio
    async def test_delete_soft_by_default(self, mcp, mock_client):
        result = await mcp.call_tool("delete_record", {
            "model": "res.partner",
            "record_id": 42,
        })
        data = json.loads(_tool_text(result))
        assert data["success"] is True
        assert data["permanent"] is False
        mock_client.write.assert_called_with("res.partner", [42], {"active": False})
        mock_client.unlink.assert_not_called()

    @pytest.mark.anyio
    async def test_delete_permanent(self, mcp, mock_client):
        result = await mcp.call_tool("delete_record", {
            "model": "res.partner",
            "record_id": 42,
            "permanent": True,
        })
        data = json.loads(_tool_text(result))
        assert data["success"] is True
        assert data["permanent"] is True
        mock_client.unlink.assert_called_once_with("res.partner", [42])


# =============================================================
# Tool: execute_method
# =============================================================

class TestExecuteMethod:
    @pytest.mark.anyio
    async def test_execute(self, mcp, mock_client):
        mock_client.execute.return_value = {"state": "done"}
        result = await mcp.call_tool("execute_method", {
            "model": "sale.order",
            "method": "action_confirm",
            "args": [[1]],
        })
        data = json.loads(_tool_text(result))
        assert data == {"state": "done"}
        mock_client.execute.assert_called_once_with(
            "sale.order", "action_confirm", [1]
        )


# =============================================================
# Tool: batch_execute
# =============================================================

class TestBatchExecute:
    @pytest.mark.anyio
    async def test_batch(self, mcp, mock_client):
        mock_client.execute.return_value = True
        operations = [
            {"model": "res.partner", "method": "write", "args": [[1], {"name": "A"}]},
            {"model": "res.partner", "method": "write", "args": [[2], {"name": "B"}]},
        ]
        result = await mcp.call_tool("batch_execute", {
            "operations": operations,
            "fail_fast": True,
        })
        data = json.loads(_tool_text(result))
        assert data["success"] is True
        assert data["succeeded"] == 2


# =============================================================
# Tool: smart_action
# =============================================================

class TestSmartAction:
    @pytest.mark.anyio
    async def test_find_or_create_partner(self, mcp, mock_client):
        mock_client.search_read.return_value = []
        mock_client.create.return_value = 10
        result = await mcp.call_tool("smart_action", {
            "action": "find_or_create_partner",
            "params": {"name": "Acme Corp"},
        })
        data = json.loads(_tool_text(result))
        assert data["id"] == 10
        assert data["created"] is True

    @pytest.mark.anyio
    async def test_unknown_action(self, mcp, mock_client):
        result = await mcp.call_tool("smart_action", {
            "action": "nonexistent_action",
            "params": {},
        })
        text = _tool_text(result)
        assert "Unknown" in text or "error" in text.lower()

    @pytest.mark.anyio
    async def test_private_method_blocked(self, mcp, mock_client):
        result = await mcp.call_tool("smart_action", {
            "action": "_internal_method",
            "params": {},
        })
        data = json.loads(_tool_text(result))
        assert "error" in data


# =============================================================
# Tool: analyze
# =============================================================

class TestAnalyze:
    @pytest.mark.anyio
    async def test_sales_report(self, mcp, mock_client):
        mock_client.search_read.return_value = []
        result = await mcp.call_tool("analyze", {
            "report_type": "sales",
        })
        data = json.loads(_tool_text(result))
        assert isinstance(data, dict)

    @pytest.mark.anyio
    async def test_full_report(self, mcp, mock_client):
        mock_client.search_read.return_value = []
        mock_client.search_count.return_value = 0
        mock_client.execute.return_value = []
        result = await mcp.call_tool("analyze", {
            "report_type": "full",
        })
        data = json.loads(_tool_text(result))
        assert isinstance(data, dict)

    @pytest.mark.anyio
    async def test_unknown_report(self, mcp, mock_client):
        result = await mcp.call_tool("analyze", {
            "report_type": "nonexistent",
        })
        text = _tool_text(result)
        assert "Unknown" in text or "error" in text.lower()

    @pytest.mark.anyio
    async def test_auto_report_requires_model(self, mcp, mock_client):
        result = await mcp.call_tool("analyze", {
            "report_type": "auto",
        })
        data = json.loads(_tool_text(result))
        assert "error" in data
        assert "model" in data["error"]

    @pytest.mark.anyio
    async def test_auto_report_with_valid_model(self, mcp, mock_client):
        """Auto report delegates to generate_auto_dashboard via registry."""
        mock_client.search_count.return_value = 5
        mock_client.search_read.return_value = [{"id": i} for i in range(5)]

        mock_info = MagicMock()
        mock_info.name = "x_fleet.vehicle"
        mock_info.label = "Fleet Vehicle"
        mock_info.money_fields = []
        mock_info.date_fields = []
        mock_info.status_field = None

        mock_reg = MagicMock()
        mock_reg.resolve.return_value = mock_info

        mock_dash_result = {
            "model": "x_fleet.vehicle",
            "label": "Fleet Vehicle",
            "total_records": 5,
            "by_status": {},
            "totals": {},
            "recent": [],
        }

        with patch("openclaw_odoo.registry.ModelRegistry", return_value=mock_reg), \
             patch("openclaw_odoo.auto_actions.generate_auto_dashboard", return_value=mock_dash_result):
            result = await mcp.call_tool("analyze", {
                "report_type": "auto",
                "params": {"model": "x_fleet.vehicle"},
            })
            data = json.loads(_tool_text(result))
            assert data["total_records"] == 5
            assert data["model"] == "x_fleet.vehicle"


# =============================================================
# Tool: import_file
# =============================================================

class TestImportFile:
    @pytest.mark.anyio
    async def test_import_csv(self, mcp, mock_client, tmp_path):
        csv_file = tmp_path / "partners.csv"
        csv_file.write_text("name,email\nAcme,acme@test.com\n")
        mock_client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name"},
            "email": {"type": "char", "string": "Email"},
        }
        mock_client.create.return_value = 1
        result = await mcp.call_tool("import_file", {
            "filepath": str(csv_file),
            "model": "res.partner",
        })
        data = json.loads(_tool_text(result))
        assert data["created_count"] == 1


# =============================================================
# Tool: export_data
# =============================================================

class TestExportData:
    @pytest.mark.anyio
    async def test_export_csv(self, mcp, mock_client, tmp_path):
        mock_client.search_read.return_value = [
            {"id": 1, "name": "Acme", "email": "acme@test.com"},
        ]
        result = await mcp.call_tool("export_data", {
            "model": "res.partner",
            "fields": ["name", "email"],
            "output_format": "csv",
        })
        data = json.loads(_tool_text(result))
        assert "filepath" in data


# =============================================================
# Tool: list_models
# =============================================================

class TestListModels:
    @pytest.mark.anyio
    async def test_list_models(self, mcp, mock_client):
        mock_client.search_read.return_value = [
            {"model": "res.partner", "name": "Contact"},
            {"model": "sale.order", "name": "Sales Order"},
        ]
        result = await mcp.call_tool("list_models", {})
        data = json.loads(_tool_text(result))
        assert len(data) == 2


# =============================================================
# Tool: get_fields
# =============================================================

class TestGetFields:
    @pytest.mark.anyio
    async def test_get_fields(self, mcp, mock_client):
        mock_client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name", "required": True},
            "email": {"type": "char", "string": "Email"},
        }
        result = await mcp.call_tool("get_fields", {"model": "res.partner"})
        data = json.loads(_tool_text(result))
        assert "name" in data
        assert data["name"]["type"] == "char"
