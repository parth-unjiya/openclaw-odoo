"""Calendar module -- CRUD, search, and date-range queries for calendar.event."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..client import OdooClient
from ..errors import OdooRecordNotFoundError
from ..fields import select_smart_fields

MODEL = "calendar.event"


def create_event(
    client: OdooClient,
    name: str,
    start: str,
    stop: str,
    partner_ids: Optional[list[int]] = None,
    **extra: Any,
) -> dict:
    """Create a new calendar event.

    Args:
        client: Authenticated OdooClient instance.
        name: Title/subject of the event.
        start: Start datetime string (e.g. "2026-03-10 09:00:00").
        stop: Stop datetime string (e.g. "2026-03-10 10:00:00").
        partner_ids: Optional list of partner IDs to add as attendees.
            Will be formatted as [(6, 0, partner_ids)] for Odoo many2many.
        **extra: Additional field values to set on the event.

    Returns:
        Dict with 'id' and 'web_url' of the created event.
    """
    values: dict[str, Any] = {"name": name, "start": start, "stop": stop}
    if partner_ids is not None:
        values["partner_ids"] = [(6, 0, partner_ids)]
    values.update(extra)
    record_id = client.create(MODEL, values)
    return {"id": record_id, "web_url": client.web_url(MODEL, record_id)}


def get_event(
    client: OdooClient,
    event_id: int,
    smart_fields: bool = True,
) -> dict:
    """Get a single calendar event by ID.

    Args:
        client: Authenticated OdooClient instance.
        event_id: ID of the calendar event to retrieve.
        smart_fields: If True, use smart field selection to limit returned
            fields. If False, return all fields.

    Returns:
        Dict of event data.

    Raises:
        OdooRecordNotFoundError: If no event with the given ID exists.
    """
    fields: Optional[list[str]] = None
    if smart_fields:
        fields_def = client.fields_get(MODEL)
        fields = select_smart_fields(fields_def)
    results = client.search_read(
        MODEL, domain=[["id", "=", event_id]], fields=fields, limit=1,
    )
    if not results:
        raise OdooRecordNotFoundError(
            f"Calendar event {event_id} not found", model=MODEL,
        )
    return results[0]


def search_events(
    client: OdooClient,
    domain: Optional[list] = None,
    limit: Optional[int] = None,
    **kwargs: Any,
) -> list[dict]:
    """Search calendar events with smart field selection.

    Args:
        client: Authenticated OdooClient instance.
        domain: Odoo domain filter list. Defaults to empty (all events).
        limit: Maximum number of records to return.
        **kwargs: Additional keyword arguments passed to search_read
            (e.g. order, offset).

    Returns:
        List of event dicts matching the domain.
    """
    fields_def = client.fields_get(MODEL)
    fields = select_smart_fields(fields_def)
    return client.search_read(
        MODEL, domain=domain or [], fields=fields, limit=limit, **kwargs,
    )


def update_event(
    client: OdooClient,
    event_id: int,
    values: dict,
) -> dict:
    """Update fields on a calendar event.

    Args:
        client: Authenticated OdooClient instance.
        event_id: ID of the event to update.
        values: Dict of field names to new values.

    Returns:
        Dict with 'id' and 'web_url' of the updated event.
    """
    client.write(MODEL, [event_id], values)
    return {"id": event_id, "web_url": client.web_url(MODEL, event_id)}


def delete_event(
    client: OdooClient,
    event_id: int,
) -> dict:
    """Archive a calendar event (set active=False).

    Args:
        client: Authenticated OdooClient instance.
        event_id: ID of the event to archive.

    Returns:
        Dict with 'id' and 'archived' status.
    """
    client.write(MODEL, [event_id], {"active": False})
    return {"id": event_id, "archived": True}


def get_today_events(client: OdooClient) -> list[dict]:
    """Get all calendar events scheduled for today (UTC).

    Args:
        client: Authenticated OdooClient instance.

    Returns:
        List of event dicts with start times within today (UTC).
    """
    today = datetime.now(timezone.utc).date()
    start_of_day = f"{today} 00:00:00"
    end_of_day = f"{today} 23:59:59"
    domain = [
        ["start", ">=", start_of_day],
        ["start", "<=", end_of_day],
    ]
    fields_def = client.fields_get(MODEL)
    fields = select_smart_fields(fields_def)
    return client.search_read(MODEL, domain=domain, fields=fields)


def get_upcoming_events(
    client: OdooClient,
    days: int = 7,
) -> list[dict]:
    """Get upcoming calendar events within the next N days, sorted by start.

    Args:
        client: Authenticated OdooClient instance.
        days: Number of days to look ahead. Defaults to 7.

    Returns:
        List of event dicts sorted by start ascending.
    """
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    domain = [
        ["start", ">=", now.strftime("%Y-%m-%d %H:%M:%S")],
        ["start", "<=", end.strftime("%Y-%m-%d %H:%M:%S")],
    ]
    fields_def = client.fields_get(MODEL)
    fields = select_smart_fields(fields_def)
    return client.search_read(
        MODEL, domain=domain, fields=fields, order="start asc",
    )
