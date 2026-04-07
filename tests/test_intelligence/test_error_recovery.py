import pytest
from unittest.mock import MagicMock, patch
from openclaw_odoo.errors import (
    OdooValidationError, OdooAccessError, OdooClawError, classify_error,
)
from openclaw_odoo.intelligence.error_recovery import ErrorRecovery


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.fields_get.return_value = {
        "name": {"type": "char", "required": True, "string": "Name"},
        "email": {"type": "char", "required": False, "string": "Email"},
        "active": {"type": "boolean", "required": False, "string": "Active"},
        "amount": {"type": "float", "required": False, "string": "Amount"},
        "date": {"type": "date", "required": False, "string": "Date"},
        "count": {"type": "integer", "required": False, "string": "Count"},
    }
    return client


@pytest.fixture
def recovery(mock_client):
    return ErrorRecovery(mock_client)


# --- _fix_missing_required ---

class TestFixMissingRequired:
    def test_adds_default_char_field(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"email": "a@b.com"}], "kwargs": {}}
        error = OdooValidationError("ValidationError: field 'name' is required")
        result = recovery._fix_missing_required(op, error)
        assert "name" in result["args"][0]

    def test_adds_default_boolean_field(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test"}], "kwargs": {}}
        error = OdooValidationError("ValidationError: field 'active' is required")
        result = recovery._fix_missing_required(op, error)
        assert result["args"][0]["active"] is False

    def test_returns_none_when_field_not_found(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test"}], "kwargs": {}}
        error = OdooValidationError("ValidationError: field 'unknown_xyz' is required")
        result = recovery._fix_missing_required(op, error)
        assert result is None


# --- _fix_type_mismatch ---

class TestFixTypeMismatch:
    def test_converts_string_to_float(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"amount": "123.45"}], "kwargs": {}}
        error = OdooValidationError("TypeError: expected float for field 'amount'")
        result = recovery._fix_type_mismatch(op, error)
        assert result["args"][0]["amount"] == 123.45

    def test_converts_string_to_integer(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"count": "42"}], "kwargs": {}}
        error = OdooValidationError("TypeError: expected integer for field 'count'")
        result = recovery._fix_type_mismatch(op, error)
        assert result["args"][0]["count"] == 42

    def test_converts_string_to_boolean(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"active": "true"}], "kwargs": {}}
        error = OdooValidationError("TypeError: expected boolean for field 'active'")
        result = recovery._fix_type_mismatch(op, error)
        assert result["args"][0]["active"] is True

    def test_returns_none_on_unconvertible(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"amount": "not_a_number"}], "kwargs": {}}
        error = OdooValidationError("TypeError: expected float for field 'amount'")
        result = recovery._fix_type_mismatch(op, error)
        assert result is None


# --- _fix_duplicate ---

class TestFixDuplicate:
    def test_returns_existing_record(self, recovery, mock_client):
        mock_client.search_read.return_value = [{"id": 99, "name": "Existing"}]
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Existing"}], "kwargs": {}}
        error = OdooValidationError("ValidationError: duplicate key value violates unique constraint")
        result = recovery._fix_duplicate(op, error)
        assert result == {"existing_record": {"id": 99, "name": "Existing"}}

    def test_returns_none_when_no_match(self, recovery, mock_client):
        mock_client.search_read.return_value = []
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Ghost"}], "kwargs": {}}
        error = OdooValidationError("ValidationError: duplicate key value")
        result = recovery._fix_duplicate(op, error)
        assert result is None


# --- _fix_field_not_found ---

class TestFixFieldNotFound:
    def test_removes_unknown_field(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test", "bogus": "val"}], "kwargs": {}}
        error = OdooValidationError("ValueError: field 'bogus' does not exist on model 'res.partner'")
        result = recovery._fix_field_not_found(op, error)
        assert "bogus" not in result["args"][0]
        assert result["args"][0]["name"] == "Test"

    def test_returns_none_when_field_not_parseable(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test"}], "kwargs": {}}
        error = OdooValidationError("ValueError: some vague error no field mentioned")
        result = recovery._fix_field_not_found(op, error)
        assert result is None


# --- _fix_date_format ---

class TestFixDateFormat:
    def test_converts_slash_format(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"date": "03/06/2026"}], "kwargs": {}}
        error = OdooValidationError("ValueError: invalid date format for field 'date'")
        result = recovery._fix_date_format(op, error)
        assert result["args"][0]["date"] == "2026-03-06"

    def test_converts_verbose_format(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"date": "March 6, 2026"}], "kwargs": {}}
        error = OdooValidationError("ValueError: invalid date format for field 'date'")
        result = recovery._fix_date_format(op, error)
        assert result["args"][0]["date"] == "2026-03-06"

    def test_converts_dot_format(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"date": "06.03.2026"}], "kwargs": {}}
        error = OdooValidationError("ValueError: invalid date format for field 'date'")
        result = recovery._fix_date_format(op, error)
        assert result["args"][0]["date"] == "2026-03-06"

    def test_returns_none_when_no_date_field(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test"}], "kwargs": {}}
        error = OdooValidationError("ValueError: invalid date format for field 'date'")
        result = recovery._fix_date_format(op, error)
        assert result is None


# --- _fix_access_denied ---

class TestFixAccessDenied:
    def test_returns_none(self, recovery, mock_client):
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test"}], "kwargs": {}}
        error = OdooAccessError("AccessError: not allowed")
        result = recovery._fix_access_denied(op, error)
        assert result is None


# --- recover orchestrator ---

class TestRecover:
    def test_successful_recovery_missing_required(self, recovery, mock_client):
        error = OdooValidationError("ValidationError: field 'name' is required")
        op = {"model": "res.partner", "method": "create", "args": [{"email": "a@b.com"}], "kwargs": {}}
        mock_client.execute.return_value = 42
        result = recovery.recover(op, error)
        assert result["success"] is True
        assert result["result"] == 42
        assert result["attempts"] >= 1
        assert len(result["fixes_applied"]) >= 1

    def test_unrecoverable_error(self, recovery, mock_client):
        error = OdooAccessError("AccessError: not allowed")
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test"}], "kwargs": {}}
        result = recovery.recover(op, error)
        assert result["success"] is False

    def test_max_attempts_respected(self, recovery, mock_client):
        error = OdooValidationError("ValidationError: field 'name' is required")
        op = {"model": "res.partner", "method": "create", "args": [{"email": "a@b.com"}], "kwargs": {}}
        mock_client.execute.side_effect = OdooValidationError("ValidationError: field 'name' is required")
        result = recovery.recover(op, error, max_attempts=2)
        assert result["success"] is False
        assert result["attempts"] == 2

    def test_recover_field_not_found(self, recovery, mock_client):
        error = OdooValidationError("ValueError: field 'bogus' does not exist on model 'res.partner'")
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Test", "bogus": "val"}], "kwargs": {}}
        mock_client.execute.return_value = 10
        result = recovery.recover(op, error)
        assert result["success"] is True
        assert result["result"] == 10

    def test_recover_date_format(self, recovery, mock_client):
        error = OdooValidationError("ValueError: invalid date format for field 'date'")
        op = {"model": "res.partner", "method": "create", "args": [{"date": "03/06/2026"}], "kwargs": {}}
        mock_client.execute.return_value = 7
        result = recovery.recover(op, error)
        assert result["success"] is True
        assert result["result"] == 7

    def test_recover_type_mismatch(self, recovery, mock_client):
        error = OdooValidationError("TypeError: expected float for field 'amount'")
        op = {"model": "res.partner", "method": "create", "args": [{"amount": "99.5"}], "kwargs": {}}
        mock_client.execute.return_value = 5
        result = recovery.recover(op, error)
        assert result["success"] is True
        assert result["result"] == 5

    def test_recover_duplicate(self, recovery, mock_client):
        mock_client.search_read.return_value = [{"id": 77, "name": "Dup"}]
        error = OdooValidationError("ValidationError: duplicate key value violates unique constraint")
        op = {"model": "res.partner", "method": "create", "args": [{"name": "Dup"}], "kwargs": {}}
        result = recovery.recover(op, error)
        assert result["success"] is True
        assert result["result"] == {"existing_record": {"id": 77, "name": "Dup"}}
