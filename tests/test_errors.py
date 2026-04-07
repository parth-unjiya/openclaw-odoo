from openclaw_odoo.errors import (
    OdooClawError, OdooConnectionError, OdooAuthenticationError,
    OdooAccessError, OdooValidationError, OdooRecordNotFoundError,
    classify_error
)

def test_error_hierarchy():
    assert issubclass(OdooConnectionError, OdooClawError)
    assert issubclass(OdooAuthenticationError, OdooClawError)
    assert issubclass(OdooAccessError, OdooClawError)
    assert issubclass(OdooValidationError, OdooClawError)
    assert issubclass(OdooRecordNotFoundError, OdooClawError)

def test_classify_access_denied():
    err = classify_error("AccessDenied: invalid credentials")
    assert isinstance(err, OdooAuthenticationError)

def test_classify_access_error():
    err = classify_error("AccessError: not allowed to read sale.order")
    assert isinstance(err, OdooAccessError)

def test_classify_validation():
    err = classify_error("ValidationError: field 'name' is required")
    assert isinstance(err, OdooValidationError)

def test_classify_missing():
    err = classify_error("MissingError: Record does not exist")
    assert isinstance(err, OdooRecordNotFoundError)

def test_classify_connection():
    err = classify_error("ConnectionError: timeout")
    assert isinstance(err, OdooConnectionError)

def test_classify_unknown():
    err = classify_error("SomeRandomError: weird stuff")
    assert isinstance(err, OdooClawError)

def test_error_attrs():
    err = OdooValidationError("bad field", model="res.partner", method="create")
    assert err.model == "res.partner"
    assert err.method == "create"
    assert str(err) == "bad field"
