"""CRM module -- leads, opportunities, pipeline, stages, forecast."""
from collections import defaultdict
from typing import Any, Optional

from ..client import OdooClient

MODEL = "crm.lead"
STAGE_MODEL = "crm.stage"


def create_lead(client: OdooClient, name: str, partner_name: Optional[str] = None,
                email_from: Optional[str] = None, phone: Optional[str] = None,
                **extra) -> dict:
    """Create a CRM lead and return {id, web_url}.

    Args:
        client: OdooClient instance.
        name: Lead title/subject.
        partner_name: Optional contact company name.
        email_from: Optional contact email.
        phone: Optional contact phone.
        **extra: Additional crm.lead field values.

    Returns:
        Dict with 'id' and 'web_url' of the created lead.
    """
    vals: dict[str, Any] = {"name": name}
    if partner_name is not None:
        vals["partner_name"] = partner_name
    if email_from is not None:
        vals["email_from"] = email_from
    if phone is not None:
        vals["phone"] = phone
    vals.update(extra)
    record_id = client.create(MODEL, vals)
    return {"id": record_id, "web_url": client.web_url(MODEL, record_id)}


def create_opportunity(client: OdooClient, name: str, partner_id: int,
                       expected_revenue: float = 0, probability: float = 10,
                       **extra) -> dict:
    """Create a CRM opportunity linked to a partner.

    Args:
        client: OdooClient instance.
        name: Opportunity title.
        partner_id: Linked partner record ID.
        expected_revenue: Expected deal value.
        probability: Win probability percentage (0-100).
        **extra: Additional crm.lead field values.

    Returns:
        Dict with 'id' and 'web_url' of the created opportunity.
    """
    vals: dict[str, Any] = {
        "name": name,
        "partner_id": partner_id,
        "expected_revenue": expected_revenue,
        "probability": probability,
        "type": "opportunity",
    }
    vals.update(extra)
    record_id = client.create(MODEL, vals)
    return {"id": record_id, "web_url": client.web_url(MODEL, record_id)}


def get_pipeline(client: OdooClient, user_id: Optional[int] = None) -> list[dict]:
    """Fetch the CRM pipeline grouped by stage.

    Args:
        client: OdooClient instance.
        user_id: Optional salesperson user ID to filter by.

    Returns:
        List of dicts, each with 'stage' name and 'opportunities' list.
    """
    domain: list = [["type", "=", "opportunity"]]
    if user_id is not None:
        domain.append(["user_id", "=", user_id])
    records = client.search_read(MODEL, domain=domain)
    grouped: dict[str, list] = defaultdict(list)
    stage_order: list[str] = []
    for rec in records:
        stage_name = rec["stage_id"][1] if isinstance(rec.get("stage_id"), (list, tuple)) else str(rec.get("stage_id", ""))
        if stage_name not in stage_order:
            stage_order.append(stage_name)
        grouped[stage_name].append(rec)
    return [{"stage": s, "opportunities": grouped[s]} for s in stage_order]


def move_stage(client: OdooClient, lead_id: int, stage_id: int) -> dict:
    """Move a lead/opportunity to a different pipeline stage."""
    client.write(MODEL, [lead_id], {"stage_id": stage_id})
    return {"success": True, "lead_id": lead_id, "stage_id": stage_id}


def mark_won(client: OdooClient, lead_id: int) -> dict:
    """Mark an opportunity as won."""
    client.execute(MODEL, "action_set_won", [lead_id])
    return {"success": True, "lead_id": lead_id}


def mark_lost(client: OdooClient, lead_id: int, lost_reason: Optional[str] = None) -> dict:
    """Mark an opportunity as lost with an optional reason."""
    kwargs = {}
    if lost_reason is not None:
        kwargs["lost_reason"] = lost_reason
    client.execute(MODEL, "action_set_lost", [lead_id], **kwargs)
    return {"success": True, "lead_id": lead_id}


def get_stages(client: OdooClient) -> list[dict]:
    """Fetch all CRM pipeline stages ordered by sequence."""
    return client.search_read(
        STAGE_MODEL, domain=[], fields=["name", "sequence", "is_won"],
        order="sequence",
    )


def analyze_pipeline(client: OdooClient) -> dict:
    """Compute pipeline KPIs: lead/opportunity counts, revenue, win rate, per-stage breakdown.

    Returns:
        Dict with total_leads, total_opportunities, total_revenue,
        win_rate, and conversion_per_stage.
    """
    total_leads = client.search_count(MODEL)
    total_opportunities = client.search_count(MODEL, [["type", "=", "opportunity"]])

    opportunities = client.search_read(
        MODEL, domain=[["type", "=", "opportunity"]],
        fields=["expected_revenue", "stage_id"],
    )
    total_revenue = sum(o.get("expected_revenue", 0) for o in opportunities)

    won = client.search_read(
        MODEL, domain=[["type", "=", "opportunity"], ["stage_id.is_won", "=", True]],
        fields=["stage_id"],
    )
    win_rate = (len(won) / total_opportunities * 100) if total_opportunities else 0.0

    stage_counts: dict[str, int] = defaultdict(int)
    for o in opportunities:
        stage_name = o["stage_id"][1] if isinstance(o.get("stage_id"), (list, tuple)) else str(o.get("stage_id", ""))
        stage_counts[stage_name] += 1

    return {
        "total_leads": total_leads,
        "total_opportunities": total_opportunities,
        "total_revenue": total_revenue,
        "win_rate": round(win_rate, 2),
        "conversion_per_stage": dict(stage_counts),
    }


def get_forecast(client: OdooClient) -> dict:
    """Calculate probability-weighted revenue forecast from open opportunities.

    Returns:
        Dict with weighted_revenue, opportunity_count, and opportunities list.
    """
    opportunities = client.search_read(
        MODEL,
        domain=[["type", "=", "opportunity"], ["probability", ">", 0]],
        fields=["name", "probability", "expected_revenue"],
    )
    weighted = sum(
        (o.get("probability", 0) / 100) * o.get("expected_revenue", 0)
        for o in opportunities
    )
    return {
        "weighted_revenue": weighted,
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
    }
