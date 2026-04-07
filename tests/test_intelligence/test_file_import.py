"""Tests for file import/export -- detect_model, map_columns, import_csv, import_excel, export_records, generate_template."""
import csv
import os
import pytest
from unittest.mock import MagicMock, call, patch
from pathlib import Path

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.errors import OdooClawError
from openclaw_odoo.intelligence.file_import import (
    detect_model,
    map_columns,
    import_csv,
    import_excel,
    export_records,
    generate_template,
)


@pytest.fixture
def client():
    config = OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )
    c = OdooClient(config)
    c.execute = MagicMock()
    c.search_read = MagicMock(return_value=[])
    c.create = MagicMock(return_value=1)
    c.read = MagicMock(return_value=[])
    c.fields_get = MagicMock(return_value={})
    c.search_count = MagicMock(return_value=0)
    c.write = MagicMock()
    return c


# =============================================================
# detect_model
# =============================================================

class TestDetectModel:
    def test_detects_partner_from_email_phone(self):
        headers = ["name", "email", "phone"]
        assert detect_model(headers) == "res.partner"

    def test_detects_partner_from_company(self):
        headers = ["Name", "Email", "Company", "City"]
        assert detect_model(headers) == "res.partner"

    def test_detects_product(self):
        headers = ["name", "list_price", "default_code", "categ_id"]
        assert detect_model(headers) == "product.template"

    def test_detects_sale_order_line(self):
        headers = ["product_id", "quantity", "price_unit"]
        assert detect_model(headers) == "sale.order.line"

    def test_detects_employee(self):
        headers = ["name", "job_title", "department_id", "work_email"]
        assert detect_model(headers) == "hr.employee"

    def test_detects_invoice_line(self):
        headers = ["product_id", "quantity", "price_unit", "account_id"]
        assert detect_model(headers) == "account.move.line"

    def test_returns_none_for_unknown(self):
        headers = ["xyzzy", "foobar", "baz"]
        assert detect_model(headers) is None

    def test_case_insensitive(self):
        headers = ["NAME", "EMAIL", "PHONE"]
        assert detect_model(headers) == "res.partner"

    def test_detect_model_with_registry_custom_model(self):
        """detect_model uses registry signatures to match custom models."""
        from openclaw_odoo.registry import ModelInfo, FieldInfo, ModelRegistry
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        registry._models["x_fleet.vehicle"] = ModelInfo(
            name="x_fleet.vehicle",
            label="Fleet Vehicle",
            is_builtin=False,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "plate": FieldInfo(name="plate", type="char", label="License Plate", store=True),
                "driver_id": FieldInfo(name="driver_id", type="many2one", label="Driver", store=True),
                "fuel_cost": FieldInfo(name="fuel_cost", type="monetary", label="Fuel Cost", store=True),
            },
        )
        headers = ["Name", "License Plate", "Driver", "Fuel Cost"]
        result = detect_model(headers, registry=registry)
        assert result == "x_fleet.vehicle"

    def test_detect_model_builtin_takes_priority_over_registry(self):
        """Hardcoded signatures for builtins win over registry."""
        from openclaw_odoo.registry import ModelInfo, FieldInfo, ModelRegistry
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        # Even with a registry that has a custom model, builtin patterns win
        headers = ["name", "email", "phone"]
        result = detect_model(headers, registry=registry)
        assert result == "res.partner"

    def test_detect_model_registry_none_ignored(self):
        """Passing registry=None should not break detection."""
        headers = ["name", "email", "phone"]
        assert detect_model(headers, registry=None) == "res.partner"

    def test_import_csv_with_registry(self, client, tmp_path):
        """import_csv passes registry to detect_model when model is None."""
        # Use label-style headers that match the registry signatures
        csv_path = tmp_path / "fleet.csv"
        with open(csv_path, "w", newline="") as f:
            import csv as csv_mod
            writer = csv_mod.writer(f)
            writer.writerow(["Name", "License Plate", "Driver", "Fuel Cost"])
            writer.writerow(["Truck 1", "KA-01-1234", "John", "500"])

        from openclaw_odoo.registry import ModelInfo, FieldInfo, ModelRegistry
        config = MagicMock()
        config.model_hints = {}
        registry = ModelRegistry(config)
        registry._models["x_fleet.vehicle"] = ModelInfo(
            name="x_fleet.vehicle",
            label="Fleet Vehicle",
            is_builtin=False,
            fields={
                "name": FieldInfo(name="name", type="char", label="Name", store=True),
                "plate": FieldInfo(name="plate", type="char", label="License Plate", store=True),
                "driver_id": FieldInfo(name="driver_id", type="many2one", label="Driver", store=True),
                "fuel_cost": FieldInfo(name="fuel_cost", type="monetary", label="Fuel Cost", store=True),
            },
        )

        # Set up fields_get so map_columns can resolve label headers to field names
        client.fields_get.return_value = {
            "name": {"type": "char", "string": "Name"},
            "plate": {"type": "char", "string": "License Plate"},
            "driver_id": {"type": "many2one", "string": "Driver", "relation": "hr.employee"},
            "fuel_cost": {"type": "monetary", "string": "Fuel Cost"},
        }
        client.create.return_value = 1
        result = import_csv(client, str(csv_path), registry=registry)
        assert result["created_count"] == 1
        # Verify it created on the custom model
        assert client.create.call_args[0][0] == "x_fleet.vehicle"


# =============================================================
# map_columns
# =============================================================

class TestMapColumns:
    def test_direct_field_match(self):
        result = map_columns(["name", "email", "phone"], "res.partner")
        assert result["name"] == "name"
        assert result["email"] == "email"
        assert result["phone"] == "phone"

    def test_label_match_with_client(self, client):
        client.fields_get.return_value = {
            "name": {"string": "Name", "type": "char"},
            "email": {"string": "Email Address", "type": "char"},
            "phone": {"string": "Phone Number", "type": "char"},
            "street": {"string": "Street", "type": "char"},
        }
        result = map_columns(
            ["Name", "Email Address", "Phone Number"],
            "res.partner",
            client=client,
        )
        assert result["Name"] == "name"
        assert result["Email Address"] == "email"
        assert result["Phone Number"] == "phone"

    def test_fuzzy_label_match(self, client):
        client.fields_get.return_value = {
            "name": {"string": "Name", "type": "char"},
            "email": {"string": "Email", "type": "char"},
            "parent_id": {"string": "Company", "type": "many2one", "relation": "res.partner"},
        }
        result = map_columns(["Company Name"], "res.partner", client=client)
        # "Company Name" should fuzzy match to parent_id (label "Company")
        assert result.get("Company Name") == "parent_id"

    def test_unmapped_columns_not_in_result(self):
        result = map_columns(["totally_unknown_xyz"], "res.partner")
        assert "totally_unknown_xyz" not in result

    def test_common_aliases(self):
        result = map_columns(["Company", "Mobile"], "res.partner")
        assert result.get("Company") == "parent_id"
        assert result.get("Mobile") == "mobile"


# =============================================================
# import_csv
# =============================================================

class TestImportCsv:
    def _write_csv(self, path, headers, rows):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)

    def test_basic_import(self, client, tmp_path):
        csv_path = tmp_path / "partners.csv"
        self._write_csv(csv_path, ["name", "email"], [
            ["Alice", "alice@example.com"],
            ["Bob", "bob@example.com"],
        ])
        client.create.side_effect = [1, 2]
        result = import_csv(client, str(csv_path), model="res.partner")
        assert result["created_count"] == 2
        assert result["skipped_count"] == 0
        assert result["errors"] == []
        assert client.create.call_count == 2

    def test_auto_detects_model(self, client, tmp_path):
        csv_path = tmp_path / "contacts.csv"
        self._write_csv(csv_path, ["name", "email", "phone"], [
            ["Alice", "alice@example.com", "555-1234"],
        ])
        client.create.return_value = 1
        result = import_csv(client, str(csv_path))
        assert result["created_count"] == 1
        # Verify it detected res.partner and created on that model
        client.create.assert_called_once()
        assert client.create.call_args[0][0] == "res.partner"

    def test_dry_run_does_not_create(self, client, tmp_path):
        csv_path = tmp_path / "partners.csv"
        self._write_csv(csv_path, ["name", "email"], [
            ["Alice", "alice@example.com"],
        ])
        result = import_csv(client, str(csv_path), model="res.partner", dry_run=True)
        assert result["created_count"] == 0
        assert client.create.call_count == 0

    def test_custom_column_map(self, client, tmp_path):
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, ["Full Name", "Email Address"], [
            ["Alice", "alice@example.com"],
        ])
        client.create.return_value = 1
        column_map = {"Full Name": "name", "Email Address": "email"}
        result = import_csv(
            client, str(csv_path), model="res.partner", column_map=column_map
        )
        assert result["created_count"] == 1
        vals = client.create.call_args[0][1]
        assert vals["name"] == "Alice"
        assert vals["email"] == "alice@example.com"

    def test_relational_field_resolution(self, client, tmp_path):
        csv_path = tmp_path / "partners.csv"
        self._write_csv(csv_path, ["name", "parent_id"], [
            ["Alice", "Acme Corp"],
        ])
        client.fields_get.return_value = {
            "name": {"string": "Name", "type": "char"},
            "parent_id": {"string": "Company", "type": "many2one", "relation": "res.partner"},
        }
        # Resolve parent_id: search for "Acme Corp" in res.partner
        client.search_read.return_value = [{"id": 10, "name": "Acme Corp"}]
        client.create.return_value = 1
        result = import_csv(client, str(csv_path), model="res.partner")
        assert result["created_count"] == 1
        vals = client.create.call_args[0][1]
        assert vals["parent_id"] == 10

    def test_skips_empty_rows(self, client, tmp_path):
        csv_path = tmp_path / "partners.csv"
        self._write_csv(csv_path, ["name", "email"], [
            ["Alice", "alice@example.com"],
            ["", ""],  # empty row
            ["Bob", "bob@example.com"],
        ])
        client.create.side_effect = [1, 2]
        result = import_csv(client, str(csv_path), model="res.partner")
        assert result["created_count"] == 2
        assert result["skipped_count"] == 1

    def test_handles_create_error(self, client, tmp_path):
        csv_path = tmp_path / "partners.csv"
        self._write_csv(csv_path, ["name", "email"], [
            ["Alice", "alice@example.com"],
            ["Bob", "bob@example.com"],
        ])
        client.create.side_effect = [1, OdooClawError("Validation failed")]
        result = import_csv(client, str(csv_path), model="res.partner")
        assert result["created_count"] == 1
        assert len(result["errors"]) == 1
        assert "Bob" in str(result["errors"][0]) or "Validation" in str(result["errors"][0])


# =============================================================
# import_excel
# =============================================================

class TestImportExcel:
    def _write_xlsx(self, path, headers, rows):
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        wb.save(path)

    def test_basic_import(self, client, tmp_path):
        xlsx_path = tmp_path / "partners.xlsx"
        self._write_xlsx(xlsx_path, ["name", "email"], [
            ["Alice", "alice@example.com"],
            ["Bob", "bob@example.com"],
        ])
        client.create.side_effect = [1, 2]
        result = import_excel(client, str(xlsx_path), model="res.partner")
        assert result["created_count"] == 2
        assert result["skipped_count"] == 0
        assert result["errors"] == []

    def test_specific_sheet(self, client, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        xlsx_path = tmp_path / "multi.xlsx"
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Ignore"
        ws1.append(["junk"])
        ws2 = wb.create_sheet("Contacts")
        ws2.append(["name", "email"])
        ws2.append(["Alice", "alice@example.com"])
        wb.save(xlsx_path)

        client.create.return_value = 1
        result = import_excel(
            client, str(xlsx_path), sheet="Contacts", model="res.partner"
        )
        assert result["created_count"] == 1

    def test_dry_run(self, client, tmp_path):
        xlsx_path = tmp_path / "partners.xlsx"
        self._write_xlsx(xlsx_path, ["name", "email"], [
            ["Alice", "alice@example.com"],
        ])
        result = import_excel(
            client, str(xlsx_path), model="res.partner", dry_run=True
        )
        assert result["created_count"] == 0
        assert client.create.call_count == 0


# =============================================================
# export_records
# =============================================================

class TestExportRecords:
    def test_export_csv(self, client, tmp_path):
        client.search_read.return_value = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"},
        ]
        filepath = str(tmp_path / "export.csv")
        result = export_records(
            client, "res.partner",
            fields=["name", "email"],
            output_format="csv",
            filepath=filepath,
        )
        assert result == filepath
        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert rows[0] == ["name", "email"]
        assert rows[1] == ["Alice", "alice@example.com"]
        assert rows[2] == ["Bob", "bob@example.com"]

    def test_export_excel(self, client, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        client.search_read.return_value = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
        ]
        filepath = str(tmp_path / "export.xlsx")
        result = export_records(
            client, "res.partner",
            fields=["name", "email"],
            output_format="excel",
            filepath=filepath,
        )
        assert result == filepath
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        assert [c.value for c in ws[1]] == ["name", "email"]
        assert [c.value for c in ws[2]] == ["Alice", "alice@example.com"]

    def test_export_with_domain(self, client, tmp_path):
        client.search_read.return_value = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
        ]
        filepath = str(tmp_path / "filtered.csv")
        export_records(
            client, "res.partner",
            domain=[("email", "ilike", "alice")],
            fields=["name", "email"],
            output_format="csv",
            filepath=filepath,
        )
        client.search_read.assert_called_once_with(
            "res.partner",
            domain=[("email", "ilike", "alice")],
            fields=["name", "email"],
            limit=0,
        )

    def test_export_auto_filepath(self, client, tmp_path):
        client.search_read.return_value = [
            {"id": 1, "name": "Alice"},
        ]
        with patch("openclaw_odoo.intelligence.file_import._default_export_dir", return_value=str(tmp_path)):
            result = export_records(
                client, "res.partner",
                fields=["name"],
                output_format="csv",
            )
        assert result.endswith(".csv")
        assert os.path.isfile(result)

    def test_export_handles_many2one_tuples(self, client, tmp_path):
        """Many2one fields are returned as [id, name] tuples -- export should use the name."""
        client.search_read.return_value = [
            {"id": 1, "name": "Alice", "parent_id": [10, "Acme Corp"]},
        ]
        filepath = str(tmp_path / "export.csv")
        export_records(
            client, "res.partner",
            fields=["name", "parent_id"],
            output_format="csv",
            filepath=filepath,
        )
        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert rows[1] == ["Alice", "Acme Corp"]


# =============================================================
# generate_template
# =============================================================

class TestGenerateTemplate:
    def test_csv_template(self, client, tmp_path):
        client.fields_get.return_value = {
            "id": {"string": "ID", "type": "integer", "readonly": True},
            "name": {"string": "Name", "type": "char", "readonly": False},
            "email": {"string": "Email", "type": "char", "readonly": False},
            "create_date": {"string": "Created on", "type": "datetime", "readonly": True},
            "message_ids": {"string": "Messages", "type": "one2many", "readonly": True},
        }
        filepath = str(tmp_path / "template.csv")
        result = generate_template(
            client, "res.partner", output_format="csv", filepath=filepath
        )
        assert result == filepath
        with open(filepath) as f:
            reader = csv.reader(f)
            headers = next(reader)
        # Should include writable fields, exclude readonly/one2many/id
        assert "name" in headers
        assert "email" in headers
        assert "id" not in headers
        assert "create_date" not in headers
        assert "message_ids" not in headers

    def test_excel_template(self, client, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        client.fields_get.return_value = {
            "name": {"string": "Name", "type": "char", "readonly": False},
            "email": {"string": "Email", "type": "char", "readonly": False},
        }
        filepath = str(tmp_path / "template.xlsx")
        result = generate_template(
            client, "res.partner", output_format="excel", filepath=filepath
        )
        assert result == filepath
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        headers = [c.value for c in ws[1]]
        assert "name" in headers
        assert "email" in headers

    def test_auto_filepath(self, client, tmp_path):
        client.fields_get.return_value = {
            "name": {"string": "Name", "type": "char", "readonly": False},
        }
        with patch("openclaw_odoo.intelligence.file_import._default_export_dir", return_value=str(tmp_path)):
            result = generate_template(client, "res.partner", output_format="csv")
        assert result.endswith(".csv")
        assert os.path.isfile(result)
