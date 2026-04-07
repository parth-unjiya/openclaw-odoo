from openclaw_odoo.fields import select_smart_fields

SAMPLE_FIELDS = {
    "id": {"type": "integer", "string": "ID"},
    "name": {"type": "char", "string": "Name"},
    "email": {"type": "char", "string": "Email"},
    "phone": {"type": "char", "string": "Phone"},
    "active": {"type": "boolean", "string": "Active"},
    "create_date": {"type": "datetime", "string": "Created on"},
    "write_date": {"type": "datetime", "string": "Last Updated"},
    "__last_update": {"type": "datetime", "string": "Last Modified"},
    "display_name": {"type": "char", "string": "Display Name"},
    "message_ids": {"type": "one2many", "string": "Messages"},
    "activity_ids": {"type": "one2many", "string": "Activities"},
    "country_id": {"type": "many2one", "string": "Country"},
    "street": {"type": "char", "string": "Street"},
    "city": {"type": "char", "string": "City"},
    "zip": {"type": "char", "string": "Zip"},
    "state_id": {"type": "many2one", "string": "State"},
    "vat": {"type": "char", "string": "Tax ID"},
    "website": {"type": "char", "string": "Website"},
    "comment": {"type": "html", "string": "Notes"},
    "image_1920": {"type": "binary", "string": "Image"},
}


def test_smart_fields_excludes_binary():
    fields = select_smart_fields(SAMPLE_FIELDS, limit=20)
    assert "image_1920" not in fields


def test_smart_fields_excludes_technical():
    fields = select_smart_fields(SAMPLE_FIELDS, limit=20)
    assert "__last_update" not in fields
    assert "message_ids" not in fields
    assert "activity_ids" not in fields


def test_smart_fields_includes_important():
    fields = select_smart_fields(SAMPLE_FIELDS, limit=15)
    assert "name" in fields
    assert "email" in fields
    assert "id" in fields


def test_smart_fields_respects_limit():
    fields = select_smart_fields(SAMPLE_FIELDS, limit=5)
    assert len(fields) <= 5
