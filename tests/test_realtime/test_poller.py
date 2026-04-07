"""Tests for ChangePoller -- change detection via write_date polling."""
import threading
import time

import pytest
from unittest.mock import MagicMock, patch

from openclaw_odoo.client import OdooClient
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.errors import OdooClawError
from openclaw_odoo.realtime.poller import ChangePoller


@pytest.fixture
def config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
        poll_interval=30,
    )


@pytest.fixture
def client(config):
    c = OdooClient(config)
    c.search_read = MagicMock(return_value=[])
    return c


# -- Construction --

class TestPollerInit:
    def test_creates_with_client_and_config(self, client, config):
        poller = ChangePoller(client, config)
        assert poller.client is client
        assert poller.config is config

    def test_poll_interval_from_config(self, client, config):
        config.poll_interval = 45
        poller = ChangePoller(client, config)
        assert poller.poll_interval == 45

    def test_default_poll_interval(self, client):
        cfg = OdooClawConfig(odoo_api_key="k")
        poller = ChangePoller(client, cfg)
        assert poller.poll_interval == 30  # default from config

    def test_empty_models_to_watch(self, client, config):
        poller = ChangePoller(client, config)
        assert poller.models_to_watch == []

    def test_models_to_watch_set(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["sale.order", "hr.attendance"])
        assert poller.models_to_watch == ["sale.order", "hr.attendance"]


# -- Callback registration --

class TestCallbacks:
    def test_on_change_registers_callback(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb = MagicMock()
        poller.on_change(cb)
        assert cb in poller._callbacks

    def test_on_change_multiple_callbacks(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb1 = MagicMock()
        cb2 = MagicMock()
        poller.on_change(cb1)
        poller.on_change(cb2)
        assert len(poller._callbacks) == 2


# -- Polling logic --

class TestPollOnce:
    def test_first_poll_records_timestamps_no_callbacks(self, client, config):
        """First poll should just record timestamps, not fire callbacks."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb = MagicMock()
        poller.on_change(cb)

        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
            {"id": 2, "write_date": "2026-03-06 10:01:00", "create_date": "2026-03-06 10:01:00"},
        ]
        poller.poll_once()

        cb.assert_not_called()
        assert poller._last_seen["res.partner"] == "2026-03-06 10:01:00"

    def test_second_poll_detects_new_records(self, client, config):
        """New records (create_date == write_date and > last_seen) => 'new_record'."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb = MagicMock()
        poller.on_change(cb)

        # First poll: seed timestamps
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.poll_once()
        cb.assert_not_called()

        # Second poll: new record appears
        client.search_read.return_value = [
            {"id": 2, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"},
        ]
        poller.poll_once()

        cb.assert_called_once()
        event_type, model, records = cb.call_args[0]
        assert event_type == "new_record"
        assert model == "res.partner"
        assert len(records) == 1
        assert records[0]["id"] == 2

    def test_second_poll_detects_updated_records(self, client, config):
        """Updated records (write_date > last_seen but create_date < last_seen) => 'updated_record'."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb = MagicMock()
        poller.on_change(cb)

        # First poll
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 09:00:00"},
        ]
        poller.poll_once()

        # Second poll: same record updated
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 09:00:00"},
        ]
        poller.poll_once()

        cb.assert_called_once()
        event_type, model, records = cb.call_args[0]
        assert event_type == "updated_record"
        assert model == "res.partner"
        assert records[0]["id"] == 1

    def test_mixed_new_and_updated_fires_separate_callbacks(self, client, config):
        """New and updated records in same poll should fire separate callbacks."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb = MagicMock()
        poller.on_change(cb)

        # First poll
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 09:00:00"},
        ]
        poller.poll_once()

        # Second poll: one new, one updated
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 09:00:00"},  # updated
            {"id": 2, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"},  # new
        ]
        poller.poll_once()

        assert cb.call_count == 2
        calls = [c[0] for c in cb.call_args_list]
        event_types = {c[0] for c in calls}
        assert event_types == {"new_record", "updated_record"}

    def test_no_callback_when_no_changes(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb = MagicMock()
        poller.on_change(cb)

        # First poll: seed
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.poll_once()

        # Second poll: no changes
        client.search_read.return_value = []
        poller.poll_once()

        cb.assert_not_called()

    def test_polls_multiple_models(self, client, config):
        poller = ChangePoller(client, config,
                              models_to_watch=["res.partner", "sale.order"])
        cb = MagicMock()
        poller.on_change(cb)

        # First poll: seed both models
        client.search_read.side_effect = [
            [{"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"}],
            [{"id": 10, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"}],
        ]
        poller.poll_once()
        cb.assert_not_called()

        # Second poll: changes in both
        client.search_read.side_effect = [
            [{"id": 2, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"}],
            [{"id": 11, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"}],
        ]
        poller.poll_once()

        assert cb.call_count == 2
        models_called = {c[0][1] for c in cb.call_args_list}
        assert models_called == {"res.partner", "sale.order"}

    def test_write_date_domain_after_first_poll(self, client, config):
        """After first poll, second poll should filter by write_date > last_seen."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        # First poll
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.poll_once()

        # Second poll
        client.search_read.return_value = []
        poller.poll_once()

        second_call = client.search_read.call_args_list[1]
        domain = second_call[1].get("domain", second_call[0][1] if len(second_call[0]) > 1 else [])
        assert ["write_date", ">", "2026-03-06 10:00:00"] in domain

    def test_first_poll_has_no_domain_filter(self, client, config):
        """First poll should not filter by write_date."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        client.search_read.return_value = []
        poller.poll_once()

        call_args = client.search_read.call_args
        domain = call_args[1].get("domain", call_args[0][1] if len(call_args[0]) > 1 else [])
        assert domain == []

    def test_updates_last_seen_to_max_write_date(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
            {"id": 2, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"},
            {"id": 3, "write_date": "2026-03-06 10:02:00", "create_date": "2026-03-06 10:02:00"},
        ]
        poller.poll_once()

        assert poller._last_seen["res.partner"] == "2026-03-06 10:05:00"

    def test_search_read_requests_create_date_field(self, client, config):
        """poll_once should request both write_date and create_date fields."""
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        client.search_read.return_value = []
        poller.poll_once()

        call_args = client.search_read.call_args
        fields = call_args[1].get("fields", [])
        assert "write_date" in fields
        assert "create_date" in fields
        assert "id" in fields


# -- Error handling --

class TestErrorHandling:
    def test_callback_error_does_not_crash_poller(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        cb_bad = MagicMock(side_effect=OdooClawError("boom"))
        cb_good = MagicMock()
        poller.on_change(cb_bad)
        poller.on_change(cb_good)

        # First poll: seed
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.poll_once()

        # Second poll: triggers callbacks
        client.search_read.return_value = [
            {"id": 2, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"},
        ]
        poller.poll_once()  # should not raise

        cb_bad.assert_called_once()
        cb_good.assert_called_once()

    def test_odoo_error_does_not_crash_poller(self, client, config):
        from openclaw_odoo.errors import OdooConnectionError
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        client.search_read.side_effect = OdooConnectionError("timeout")
        poller.poll_once()  # should not raise

    def test_model_error_does_not_block_other_models(self, client, config):
        from openclaw_odoo.errors import OdooConnectionError
        poller = ChangePoller(client, config,
                              models_to_watch=["res.partner", "sale.order"])
        cb = MagicMock()
        poller.on_change(cb)

        # First poll: seed both
        client.search_read.side_effect = [
            [{"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"}],
            [{"id": 10, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"}],
        ]
        poller.poll_once()

        # Second poll: first model errors, second succeeds
        client.search_read.side_effect = [
            OdooConnectionError("timeout"),
            [{"id": 11, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"}],
        ]
        poller.poll_once()

        # Callback fired for sale.order despite res.partner error
        assert cb.call_count == 1
        assert cb.call_args[0][1] == "sale.order"


# -- get_state --

class TestGetState:
    def test_get_state_initial(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        state = poller.get_state()
        assert state["last_poll_time"] is None
        assert state["models_watched"] == ["res.partner"]
        assert state["changes_detected_count"] == 0

    def test_get_state_after_poll(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        # First poll (seed)
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.poll_once()
        state = poller.get_state()
        assert state["last_poll_time"] is not None
        assert state["changes_detected_count"] == 0  # first poll doesn't count

    def test_get_state_counts_changes(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        poller.on_change(MagicMock())

        # First poll: seed
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.poll_once()

        # Second poll: changes
        client.search_read.return_value = [
            {"id": 2, "write_date": "2026-03-06 10:05:00", "create_date": "2026-03-06 10:05:00"},
            {"id": 3, "write_date": "2026-03-06 10:06:00", "create_date": "2026-03-06 10:06:00"},
        ]
        poller.poll_once()

        state = poller.get_state()
        assert state["changes_detected_count"] == 2


# -- Thread safety --

class TestThreadSafety:
    def test_uses_lock_for_state_access(self, client, config):
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        assert hasattr(poller, '_lock')
        assert isinstance(poller._lock, type(threading.Lock()))


# -- Background thread --

class TestBackgroundThread:
    def test_start_and_stop(self, client, config):
        config.poll_interval = 1
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        poller.start()
        assert poller._thread is not None
        assert poller._thread.is_alive()
        poller.stop()
        assert poller._thread is None or not poller._thread.is_alive()

    def test_stop_is_idempotent(self, client, config):
        config.poll_interval = 1
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        poller.stop()  # should not raise when not started
        poller.start()
        poller.stop()
        poller.stop()  # should not raise again

    def test_thread_is_daemon(self, client, config):
        config.poll_interval = 1
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        poller.start()
        assert poller._thread.daemon is True
        poller.stop()

    def test_polls_in_background(self, client, config):
        config.poll_interval = 1
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])

        # Return records on every poll to track calls
        client.search_read.return_value = [
            {"id": 1, "write_date": "2026-03-06 10:00:00", "create_date": "2026-03-06 10:00:00"},
        ]
        poller.start()
        time.sleep(0.3)
        poller.stop()

        # search_read should have been called at least once
        assert client.search_read.call_count >= 1

    def test_stop_uses_event(self, client, config):
        config.poll_interval = 1
        poller = ChangePoller(client, config, models_to_watch=["res.partner"])
        assert hasattr(poller, '_stop_event')
        assert isinstance(poller._stop_event, threading.Event)
