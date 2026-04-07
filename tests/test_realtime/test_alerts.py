"""Tests for AlertRouter -- event routing to Telegram, webhooks, callbacks."""
import hashlib
import hmac
import json

import pytest
from datetime import time
from unittest.mock import MagicMock, patch, call

from openclaw_odoo.errors import OdooClawError
from openclaw_odoo.realtime.alerts import AlertRouter, AlertDestination


@pytest.fixture
def router():
    return AlertRouter()


# ---- Destination registration ----

class TestRegistration:
    def test_add_callback_destination(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb)
        assert len(router.destinations) == 1
        assert router.destinations[0].kind == "callback"

    def test_add_webhook_destination(self, router):
        router.add_webhook("sale.order", "https://example.com/hook")
        assert len(router.destinations) == 1
        assert router.destinations[0].kind == "webhook"
        assert router.destinations[0].target == "https://example.com/hook"

    def test_add_telegram_destination(self, router):
        router.add_telegram("res.partner", token="BOT_TOKEN", chat_id="12345")
        assert len(router.destinations) == 1
        assert router.destinations[0].kind == "telegram"

    def test_multiple_destinations(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb)
        router.add_webhook("res.partner", "https://example.com/hook")
        router.add_telegram("sale.order", token="T", chat_id="C")
        assert len(router.destinations) == 3

    def test_wildcard_model(self, router):
        cb = MagicMock()
        router.add_callback("*", cb)
        assert router.destinations[0].model == "*"


# ---- Event routing ----

class TestRouting:
    def test_routes_to_matching_callback(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb)
        router.handle_event("res.partner", [{"id": 1}])
        cb.assert_called_once_with("res.partner", [{"id": 1}])

    def test_does_not_route_to_wrong_model(self, router):
        cb = MagicMock()
        router.add_callback("sale.order", cb)
        router.handle_event("res.partner", [{"id": 1}])
        cb.assert_not_called()

    def test_wildcard_matches_any_model(self, router):
        cb = MagicMock()
        router.add_callback("*", cb)
        router.handle_event("res.partner", [{"id": 1}])
        router.handle_event("sale.order", [{"id": 2}])
        assert cb.call_count == 2

    def test_routes_to_multiple_matching_destinations(self, router):
        cb1 = MagicMock()
        cb2 = MagicMock()
        router.add_callback("res.partner", cb1)
        router.add_callback("res.partner", cb2)
        router.handle_event("res.partner", [{"id": 1}])
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_callback_error_does_not_stop_other_destinations(self, router):
        cb1 = MagicMock(side_effect=OdooClawError("boom"))
        cb2 = MagicMock()
        router.add_callback("res.partner", cb1)
        router.add_callback("res.partner", cb2)
        router.handle_event("res.partner", [{"id": 1}])
        cb2.assert_called_once()

    @patch("openclaw_odoo.realtime.alerts.requests.post")
    def test_routes_to_webhook(self, mock_post, router):
        mock_post.return_value = MagicMock(status_code=200)
        router.add_webhook("res.partner", "https://example.com/hook")
        router.handle_event("res.partner", [{"id": 1}])
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "https://example.com/hook"

    @patch("openclaw_odoo.realtime.alerts.requests.post")
    def test_routes_to_telegram(self, mock_post, router):
        mock_post.return_value = MagicMock(status_code=200)
        router.add_telegram("res.partner", token="BOT_TOKEN", chat_id="12345")
        router.handle_event("res.partner", [{"id": 1, "name": "Test"}])
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "BOT_TOKEN" in url
        assert "sendMessage" in url


# ---- Quiet hours ----

class TestQuietHours:
    def test_respects_quiet_hours(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb, quiet_start=time(22, 0), quiet_end=time(6, 0))
        # Simulate routing during quiet hours (23:00)
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(23, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_not_called()

    def test_delivers_outside_quiet_hours(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb, quiet_start=time(22, 0), quiet_end=time(6, 0))
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(12, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_called_once()

    def test_quiet_hours_spanning_midnight(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb, quiet_start=time(22, 0), quiet_end=time(6, 0))
        # 3 AM should be quiet
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(3, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_not_called()

    def test_no_quiet_hours_always_delivers(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb)
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(3, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_called_once()


# ---- Integration with ChangePoller ----

class TestPollerIntegration:
    def test_connect_to_poller(self, router):
        poller = MagicMock()
        cb = MagicMock()
        router.add_callback("res.partner", cb)
        router.connect(poller)
        # Should register handle_event as callback for each model
        poller.on_change.assert_called()

    def test_connect_registers_single_callback(self, router):
        poller = MagicMock()
        cb1 = MagicMock()
        cb2 = MagicMock()
        router.add_callback("res.partner", cb1)
        router.add_callback("sale.order", cb2)
        router.connect(poller)
        # connect() now registers one callback on the poller
        poller.on_change.assert_called_once()
        callback = poller.on_change.call_args[0][0]
        assert callable(callback)


# ---- Formatter ----

class TestFormatter:
    def test_custom_formatter(self, router):
        cb = MagicMock()
        formatter = MagicMock(return_value="formatted text")
        router.add_callback("res.partner", cb, formatter=formatter)
        router.handle_event("res.partner", [{"id": 1, "name": "Test"}])
        formatter.assert_called_once_with("res.partner", [{"id": 1, "name": "Test"}])
        cb.assert_called_once_with("res.partner", "formatted text")


# ---- Webhook with HMAC signature ----

class TestWebhookHMAC:
    @patch("openclaw_odoo.realtime.alerts.requests.post")
    def test_webhook_sends_hmac_signature(self, mock_post, router):
        mock_post.return_value = MagicMock(status_code=200)
        router.add_webhook("sale.order", "https://example.com/hook", secret="my-secret")
        router.handle_event("sale.order", [{"id": 1}])
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        headers = call_kwargs[1].get("headers", {})
        assert "X-Signature" in headers

    @patch("openclaw_odoo.realtime.alerts.requests.post")
    def test_webhook_hmac_is_valid(self, mock_post, router):
        mock_post.return_value = MagicMock(status_code=200)
        secret = "test-secret-key"
        router.add_webhook("sale.order", "https://example.com/hook", secret=secret)
        records = [{"id": 1, "name": "SO001"}]
        router.handle_event("sale.order", records)

        call_kwargs = mock_post.call_args
        body = call_kwargs[1]["data"]  # pre-serialized bytes
        sig = call_kwargs[1]["headers"]["X-Signature"]
        expected = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        assert sig == expected

    @patch("openclaw_odoo.realtime.alerts.requests.post")
    def test_webhook_no_secret_no_signature(self, mock_post, router):
        mock_post.return_value = MagicMock(status_code=200)
        router.add_webhook("sale.order", "https://example.com/hook")
        router.handle_event("sale.order", [{"id": 1}])
        call_kwargs = mock_post.call_args
        headers = call_kwargs[1].get("headers", {})
        assert "X-Signature" not in headers


# ---- Telegram message formatting ----

class TestTelegramFormat:
    def test_format_includes_model_name(self, router):
        text = router._format_telegram("res.partner", [{"id": 1, "name": "Alice"}])
        assert "res.partner" in text

    def test_format_includes_record_name(self, router):
        text = router._format_telegram("res.partner", [{"id": 1, "name": "Alice"}])
        assert "Alice" in text

    def test_format_includes_record_id(self, router):
        text = router._format_telegram("res.partner", [{"id": 42, "name": "Bob"}])
        assert "42" in text

    def test_format_fallback_when_no_name(self, router):
        text = router._format_telegram("res.partner", [{"id": 7}])
        assert "7" in text

    def test_format_limits_records_shown(self, router):
        records = [{"id": i, "name": f"Record {i}"} for i in range(20)]
        text = router._format_telegram("res.partner", records)
        # Should only show first 10
        assert "Record 9" in text
        assert "Record 10" not in text


# ---- Quiet hours edge cases ----

class TestQuietHoursEdgeCases:
    def test_same_day_quiet_range(self, router):
        """Quiet hours within same day (e.g., 09:00-17:00)."""
        cb = MagicMock()
        router.add_callback("res.partner", cb, quiet_start=time(9, 0), quiet_end=time(17, 0))
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(12, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_not_called()

    def test_same_day_quiet_before_range(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb, quiet_start=time(9, 0), quiet_end=time(17, 0))
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(8, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_called_once()

    def test_same_day_quiet_after_range(self, router):
        cb = MagicMock()
        router.add_callback("res.partner", cb, quiet_start=time(9, 0), quiet_end=time(17, 0))
        with patch("openclaw_odoo.realtime.alerts._current_time", return_value=time(18, 0)):
            router.handle_event("res.partner", [{"id": 1}])
        cb.assert_called_once()
