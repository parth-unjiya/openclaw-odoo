"""Smart field selection with importance scoring."""

_EXCLUDE_TYPES = {"binary", "image"}
_EXCLUDE_PATTERNS = {
    "__last_update", "message_ids", "message_follower_ids",
    "activity_ids", "activity_user_id", "activity_state",
    "message_is_follower", "message_needaction", "message_unread",
    "message_unread_counter", "website_message_ids",
}

_HIGH_IMPORTANCE = {
    "id", "name", "display_name", "active", "state", "email",
    "phone", "partner_id", "company_id", "user_id", "date",
    "amount_total", "amount_untaxed", "amount_tax",
    "date_order", "create_date",
}


def select_smart_fields(fields_def: dict, limit: int = 15) -> list[str]:
    """Select the most relevant fields from a model's field definitions.

    Scores fields by type, importance, and required status, then returns the
    top N field names. Excludes binary, image, one2many, and internal fields.

    Args:
        fields_def: Output of fields_get() -- field name to attribute dict.
        limit: Maximum number of fields to return (default 15).

    Returns:
        List of field name strings, highest-scored first.
    """
    scored = []
    for fname, fdef in fields_def.items():
        ftype = fdef.get("type", "")
        if ftype in _EXCLUDE_TYPES:
            continue
        if fname in _EXCLUDE_PATTERNS:
            continue
        if fname.startswith("__"):
            continue
        if ftype == "one2many":
            continue

        score = 0
        if fname in _HIGH_IMPORTANCE:
            score += 100
        if ftype in ("char", "integer", "float", "monetary", "date",
                      "datetime", "selection"):
            score += 10
        if ftype == "many2one":
            score += 8
        if fdef.get("required"):
            score += 15
        if ftype == "boolean":
            score += 3
        if ftype in ("html", "text"):
            score += 1

        scored.append((fname, score))

    scored.sort(key=lambda x: -x[1])
    return [f[0] for f in scored[:limit]]
