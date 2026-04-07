"""ChangePoller -- Background thread that polls write_date for changes."""
import logging
import threading
import time
from typing import Callable, Optional

from ..client import OdooClient
from ..config import OdooClawConfig
from ..errors import OdooClawError

logger = logging.getLogger("openclaw_odoo.poller")

ChangeCallback = Callable[[str, str, list[dict]], None]


class ChangePoller:
    """Background thread that polls Odoo write_date for record changes."""

    def __init__(self, client: OdooClient, config: OdooClawConfig,
                 models_to_watch: Optional[list[str]] = None):
        self.client = client
        self.config = config
        self.poll_interval = config.poll_interval
        self.models_to_watch: list[str] = models_to_watch or []
        self._callbacks: list[ChangeCallback] = []
        self._last_seen: dict[str, str] = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._last_poll_time: Optional[float] = None
        self._changes_detected_count: int = 0

    def on_change(self, callback: ChangeCallback) -> None:
        """Register a callback to be invoked when changes are detected."""
        with self._lock:
            self._callbacks.append(callback)

    def poll_once(self) -> None:
        """Poll all watched models once for changes."""
        for model in self.models_to_watch:
            try:
                self._poll_model(model)
            except OdooClawError as e:
                logger.warning("Poll error for %s: %s", model, e)
            except OSError as e:
                logger.error("Unexpected poll error for %s: %s", model, e)
        with self._lock:
            self._last_poll_time = time.time()

    def _poll_model(self, model: str) -> None:
        with self._lock:
            last_date = self._last_seen.get(model)

        domain = [["write_date", ">", last_date]] if last_date else []
        records = self.client.search_read(
            model, domain=domain,
            fields=["id", "write_date", "create_date"],
            order="write_date asc",
        )

        if not records:
            return

        max_date = max(r["write_date"] for r in records)

        if last_date is None:
            # First poll: just record timestamps, don't fire callbacks
            with self._lock:
                self._last_seen[model] = max_date
            return

        # Classify records into new vs updated
        new_records = [r for r in records
                       if r["create_date"] == r["write_date"] and r["create_date"] > last_date]
        updated_records = [r for r in records
                           if r["create_date"] < last_date]

        with self._lock:
            self._last_seen[model] = max_date
            self._changes_detected_count += len(new_records) + len(updated_records)

        if new_records:
            self._fire_callbacks("new_record", model, new_records)
        if updated_records:
            self._fire_callbacks("updated_record", model, updated_records)

    def _fire_callbacks(self, event_type: str, model: str, records: list[dict]) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(event_type, model, records)
            except Exception as e:
                logger.error("Callback error for %s/%s: %s", model, event_type, e)

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread is not None and self._thread.is_alive():
            return  # Already running
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background polling thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def get_state(self) -> dict:
        """Return current poller state: last poll time, watched models, change count."""
        with self._lock:
            return {
                "last_poll_time": self._last_poll_time,
                "models_watched": list(self.models_to_watch),
                "changes_detected_count": self._changes_detected_count,
            }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(timeout=self.poll_interval)
