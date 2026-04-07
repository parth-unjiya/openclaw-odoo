from openclaw_odoo.retry import with_retry
from openclaw_odoo.errors import OdooConnectionError, OdooAuthenticationError

def test_retry_succeeds_first_try():
    call_count = 0
    @with_retry(max_retries=3, base_delay=0.01)
    def succeed():
        nonlocal call_count
        call_count += 1
        return "ok"
    assert succeed() == "ok"
    assert call_count == 1

def test_retry_succeeds_after_failures():
    call_count = 0
    @with_retry(max_retries=3, base_delay=0.01)
    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OdooConnectionError("timeout")
        return "ok"
    assert flaky() == "ok"
    assert call_count == 3

def test_retry_gives_up():
    @with_retry(max_retries=2, base_delay=0.01)
    def always_fail():
        raise OdooConnectionError("timeout")
    try:
        always_fail()
        assert False, "Should have raised"
    except OdooConnectionError:
        pass

def test_no_retry_on_auth_error():
    call_count = 0
    @with_retry(max_retries=3, base_delay=0.01)
    def auth_fail():
        nonlocal call_count
        call_count += 1
        raise OdooAuthenticationError("bad creds")
    try:
        auth_fail()
    except OdooAuthenticationError:
        pass
    assert call_count == 1  # No retry on non-retryable errors
