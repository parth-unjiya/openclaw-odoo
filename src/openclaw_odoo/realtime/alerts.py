"""AlertRouter -- route change events to Telegram, webhooks, and callbacks."""
import hashlib
import hmac
import html
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Callable, Optional

import requests

from ..errors import OdooClawError

logger = logging.getLogger("openclaw_odoo.alerts")


def _current_time() -> time:
    """Return current time. Separated for easy mocking in tests."""
    return datetime.now().time()


@dataclass
class AlertDestination:
    kind: str  # "telegram", "webhook", "callback"
    model: str  # model name or "*" for wildcard
    target: Any  # callback func, URL string, or None
    token: Optional[str] = None
    chat_id: Optional[str] = None
    secret: Optional[str] = None
    quiet_start: Optional[time] = None
    quiet_end: Optional[time] = None
    formatter: Optional[Callable] = None


class AlertRouter:
    """Route change events to Telegram, webhooks, and Python callbacks."""

    def __init__(self):
        self.destinations: list[AlertDestination] = []

    def add_callback(self, model: str, callback: Callable,
                     quiet_start: Optional[time] = None,
                     quiet_end: Optional[time] = None,
                     formatter: Optional[Callable] = None) -> None:
        """Register a Python callback for change events on a model.

        Args:
            model: Odoo model name or '*' for all models.
            callback: Function to call with (model, records).
            quiet_start: Optional quiet-hours start time.
            quiet_end: Optional quiet-hours end time.
            formatter: Optional function to transform records before callback.
        """
        self.destinations.append(AlertDestination(
            kind="callback", model=model, target=callback,
            quiet_start=quiet_start, quiet_end=quiet_end,
            formatter=formatter,
        ))

    def add_webhook(self, model: str, url: str,
                    secret: Optional[str] = None,
                    quiet_start: Optional[time] = None,
                    quiet_end: Optional[time] = None) -> None:
        """Register a webhook URL for change events on a model.

        Args:
            model: Odoo model name or '*' for all models.
            url: Webhook endpoint URL.
            secret: Optional HMAC secret for signing payloads.
            quiet_start: Optional quiet-hours start time.
            quiet_end: Optional quiet-hours end time.
        """
        self.destinations.append(AlertDestination(
            kind="webhook", model=model, target=url,
            secret=secret,
            quiet_start=quiet_start, quiet_end=quiet_end,
        ))

    def add_telegram(self, model: str, token: str, chat_id: str,
                     quiet_start: Optional[time] = None,
                     quiet_end: Optional[time] = None) -> None:
        """Register a Telegram bot destination for change events.

        Args:
            model: Odoo model name or '*' for all models.
            token: Telegram bot token.
            chat_id: Telegram chat or group ID.
            quiet_start: Optional quiet-hours start time.
            quiet_end: Optional quiet-hours end time.
        """
        self.destinations.append(AlertDestination(
            kind="telegram", model=model, target=None,
            token=token, chat_id=chat_id,
            quiet_start=quiet_start, quiet_end=quiet_end,
        ))

    def handle_event(self, model: str, records: list[dict]) -> None:
        """Dispatch a change event to all matching destinations."""
        for dest in self.destinations:
            if dest.model != "*" and dest.model != model:
                continue
            if self._is_quiet(dest):
                continue
            try:
                self._dispatch(dest, model, records)
            except (OdooClawError, OSError, ValueError) as e:
                logger.error("Alert dispatch error for %s/%s: %s",
                             dest.kind, model, e)

    def connect(self, poller) -> None:
        """Register this router as a callback on a ChangePoller."""
        def _on_change(event_type, model, records):
            self.handle_event(model, records)
        poller.on_change(_on_change)

    def _dispatch(self, dest: AlertDestination, model: str,
                  records: list[dict]) -> None:
        if dest.kind == "callback":
            if dest.formatter:
                formatted = dest.formatter(model, records)
                dest.target(model, formatted)
            else:
                dest.target(model, records)
        elif dest.kind == "webhook":
            self._send_webhook(dest, model, records)
        elif dest.kind == "telegram":
            self._send_telegram(dest, model, records)

    def _send_telegram(self, dest: AlertDestination, model: str,
                       records: list[dict]) -> None:
        url = f"https://api.telegram.org/bot{dest.token}/sendMessage"
        text = self._format_telegram(model, records)
        payload = {"chat_id": dest.chat_id, "text": text, "parse_mode": "HTML"}
        try:
            requests.post(url, json=payload, timeout=10)
        except requests.RequestException as e:
            logger.error("Telegram send error: %s", e)

    def _send_webhook(self, dest: AlertDestination, model: str,
                      records: list[dict]) -> None:
        payload = {"model": model, "records": records}
        body = json.dumps(payload, sort_keys=True, default=str).encode()
        headers = {"Content-Type": "application/json"}
        if dest.secret:
            sig = hmac.new(
                dest.secret.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
            headers["X-Signature"] = sig
        try:
            requests.post(dest.target, data=body, headers=headers, timeout=10)
        except requests.RequestException as e:
            logger.error("Webhook send error: %s", e)

    @staticmethod
    def _format_telegram(model: str, records: list[dict]) -> str:
        lines = [f"<b>{model}</b> -- {len(records)} record(s) changed"]
        for r in records[:10]:
            name = html.escape(str(r.get("name", r.get("display_name", f"ID {r.get('id', '?')}"))))
            lines.append(f"  - {name} (id={r.get('id', '?')})")
        return "\n".join(lines)

    @staticmethod
    def _is_quiet(dest: AlertDestination) -> bool:
        if dest.quiet_start is None or dest.quiet_end is None:
            return False
        now = _current_time()
        if dest.quiet_start <= dest.quiet_end:
            # Same-day range (e.g., 09:00 - 17:00)
            return dest.quiet_start <= now <= dest.quiet_end
        else:
            # Overnight range (e.g., 22:00 - 06:00)
            return now >= dest.quiet_start or now <= dest.quiet_end
