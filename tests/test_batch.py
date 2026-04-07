from unittest.mock import MagicMock
from openclaw_odoo.batch import batch_execute
from openclaw_odoo.errors import OdooClawError


def test_batch_all_succeed():
    mock_client = MagicMock()
    mock_client.config.readonly = False
    mock_client.execute.side_effect = [1, True, True]
    ops = [
        {"model": "res.partner", "method": "create", "args": [{"name": "Test"}]},
        {"model": "res.partner", "method": "write", "args": [[1], {"email": "t@t.com"}]},
        {"model": "sale.order", "method": "action_confirm", "args": [[1]]},
    ]
    result = batch_execute(mock_client, ops)
    assert result["success"] is True
    assert result["total"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0


def test_batch_fail_fast_stops():
    mock_client = MagicMock()
    mock_client.config.readonly = False
    mock_client.execute.side_effect = [1, OdooClawError("boom"), True]
    ops = [
        {"model": "res.partner", "method": "create", "args": [{"name": "Test"}]},
        {"model": "res.partner", "method": "write", "args": [[1], {"bad": "field"}]},
        {"model": "sale.order", "method": "action_confirm", "args": [[1]]},
    ]
    result = batch_execute(mock_client, ops, fail_fast=True)
    assert result["success"] is False
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert len(result["results"]) == 2  # stopped after failure


def test_batch_continue_on_error():
    mock_client = MagicMock()
    mock_client.config.readonly = False
    mock_client.execute.side_effect = [1, OdooClawError("boom"), True]
    ops = [
        {"model": "a", "method": "create", "args": [{}]},
        {"model": "b", "method": "create", "args": [{}]},
        {"model": "c", "method": "create", "args": [{}]},
    ]
    result = batch_execute(mock_client, ops, fail_fast=False)
    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
