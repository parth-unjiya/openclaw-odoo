import pytest
from unittest.mock import MagicMock, call, patch
from openclaw_odoo.client import OdooClient
from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.modules.partners import (
    create_partner, find_partner, get_partner, update_partner,
    delete_partner, get_partner_summary, get_top_customers,
)

MODEL = "res.partner"


@pytest.fixture
def config():
    return OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )


@pytest.fixture
def client(config):
    c = OdooClient(config)
    c.create = MagicMock()
    c.write = MagicMock()
    c.search_read = MagicMock()
    c.search_count = MagicMock()
    c.fields_get = MagicMock()
    c.read = MagicMock()
    c.web_url = MagicMock(return_value="http://localhost:8069/odoo/res.partner/42")
    return c


# -- create_partner --

class TestCreatePartner:
    def test_create_minimal(self, client):
        client.create.return_value = 42
        result = create_partner(client, "Acme Corp")
        client.create.assert_called_once_with(MODEL, {"name": "Acme Corp", "is_company": False})
        assert result == {"id": 42, "web_url": "http://localhost:8069/odoo/res.partner/42"}

    def test_create_with_all_fields(self, client):
        client.create.return_value = 7
        client.web_url.return_value = "http://localhost:8069/odoo/res.partner/7"
        result = create_partner(client, "Bob", email="bob@example.com",
                                phone="+1234", is_company=True, city="NYC")
        expected_vals = {
            "name": "Bob", "email": "bob@example.com",
            "phone": "+1234", "is_company": True, "city": "NYC",
        }
        client.create.assert_called_once_with(MODEL, expected_vals)
        assert result["id"] == 7

    def test_create_returns_web_url(self, client):
        client.create.return_value = 10
        result = create_partner(client, "Test")
        assert "web_url" in result
        client.web_url.assert_called_with(MODEL, 10)


# -- find_partner --

class TestFindPartner:
    def test_find_exact_match_returns_immediately(self, client):
        client.search_read.return_value = [{"id": 1, "name": "Alice", "email": "alice@x.com"}]
        result = find_partner(client, "Alice")
        # First call should be exact match on name
        first_call = client.search_read.call_args_list[0]
        domain = first_call[1].get("domain") or first_call[0][1]
        assert ["name", "=", "Alice"] in domain
        assert len(result) >= 1

    def test_find_falls_back_to_ilike(self, client):
        # First call (exact) returns empty, second call (ilike) returns results
        client.search_read.side_effect = [
            [],  # exact match returns nothing
            [{"id": 2, "name": "Alice Smith", "email": "alice@x.com"}],  # ilike match
        ]
        result = find_partner(client, "Alice")
        assert len(result) == 1
        assert result[0]["name"] == "Alice Smith"
        # Should have made 2 calls
        assert client.search_read.call_count == 2

    def test_find_searches_email_and_phone(self, client):
        client.search_read.side_effect = [
            [],  # exact
            [{"id": 3, "name": "Bob", "email": "bob@test.com", "phone": "+1234"}],  # ilike
        ]
        result = find_partner(client, "bob@test.com")
        # The ilike domain should search across name, email, phone
        second_call = client.search_read.call_args_list[1]
        domain = second_call[1].get("domain") or second_call[0][1]
        # Should have OR conditions for ilike on name, email, phone
        assert "|" in domain

    def test_find_no_results(self, client):
        client.search_read.side_effect = [[], []]
        result = find_partner(client, "nonexistent")
        assert result == []


# -- get_partner --

class TestGetPartner:
    def test_get_with_smart_fields(self, client):
        client.fields_get.return_value = {
            "id": {"type": "integer"}, "name": {"type": "char", "required": True},
            "email": {"type": "char"}, "phone": {"type": "char"},
        }
        client.search_read.return_value = [{"id": 42, "name": "Acme", "email": "a@b.com"}]
        result = get_partner(client, 42, smart_fields=True)
        client.fields_get.assert_called_once_with(MODEL)
        assert result["id"] == 42

    def test_get_without_smart_fields(self, client):
        client.search_read.return_value = [{"id": 42, "name": "Acme"}]
        result = get_partner(client, 42, smart_fields=False)
        client.fields_get.assert_not_called()
        assert result["id"] == 42

    def test_get_not_found_raises(self, client):
        client.search_read.return_value = []
        from openclaw_odoo.errors import OdooRecordNotFoundError
        with pytest.raises(OdooRecordNotFoundError):
            get_partner(client, 999)


# -- update_partner --

class TestUpdatePartner:
    def test_update_calls_write(self, client):
        client.write.return_value = True
        result = update_partner(client, 42, name="New Name", email="new@x.com")
        client.write.assert_called_once_with(MODEL, [42], {"name": "New Name", "email": "new@x.com"})
        assert result["id"] == 42
        assert "web_url" in result

    def test_update_returns_web_url(self, client):
        client.write.return_value = True
        result = update_partner(client, 42, phone="+999")
        client.web_url.assert_called_with(MODEL, 42)


# -- delete_partner --

class TestDeletePartner:
    def test_delete_archives_not_unlinks(self, client):
        client.write.return_value = True
        result = delete_partner(client, 42)
        client.write.assert_called_once_with(MODEL, [42], {"active": False})
        assert result["id"] == 42
        assert result["archived"] is True

    def test_delete_does_not_call_unlink(self, client):
        client.unlink = MagicMock()
        client.write.return_value = True
        delete_partner(client, 42)
        client.unlink.assert_not_called()


# -- get_partner_summary --

class TestGetPartnerSummary:
    def test_summary_includes_counts_and_revenue(self, client):
        client.search_read.return_value = [{"id": 42, "name": "Acme", "email": "a@b.com"}]
        client.fields_get.return_value = {
            "id": {"type": "integer"}, "name": {"type": "char", "required": True},
            "email": {"type": "char"},
        }
        client.search_count.side_effect = [5, 3]  # sale orders, invoices
        # For total revenue: search_read on sale.order returns orders with amount_total
        so_search_read = client.search_read
        # We need to differentiate calls: first for partner, then for sale orders
        client.search_read.side_effect = [
            [{"id": 42, "name": "Acme", "email": "a@b.com"}],  # partner
            [{"amount_total": 1000}, {"amount_total": 2000}],  # sale orders for revenue
        ]
        result = get_partner_summary(client, 42)
        assert result["id"] == 42
        assert result["sale_order_count"] == 5
        assert result["invoice_count"] == 3
        assert result["total_revenue"] == 3000

    def test_summary_zero_revenue_when_no_orders(self, client):
        client.search_read.side_effect = [
            [{"id": 42, "name": "Acme"}],  # partner
            [],  # no sale orders
        ]
        client.fields_get.return_value = {
            "id": {"type": "integer"}, "name": {"type": "char", "required": True},
        }
        client.search_count.side_effect = [0, 0]
        result = get_partner_summary(client, 42)
        assert result["total_revenue"] == 0
        assert result["sale_order_count"] == 0


# -- get_top_customers --

class TestGetTopCustomers:
    def test_returns_limited_results(self, client):
        orders = [
            {"partner_id": [1, "Alice"], "amount_total": 5000},
            {"partner_id": [1, "Alice"], "amount_total": 3000},
            {"partner_id": [2, "Bob"], "amount_total": 2000},
            {"partner_id": [3, "Carol"], "amount_total": 1000},
        ]
        client.search_read.return_value = orders
        result = get_top_customers(client, limit=2)
        assert len(result) == 2
        # Alice should be first (8000 total)
        assert result[0]["partner_id"] == 1
        assert result[0]["total_revenue"] == 8000

    def test_respects_limit(self, client):
        orders = [
            {"partner_id": [i, f"Partner {i}"], "amount_total": 100 * i}
            for i in range(1, 20)
        ]
        client.search_read.return_value = orders
        result = get_top_customers(client, limit=5)
        assert len(result) <= 5

    def test_aggregates_by_partner(self, client):
        orders = [
            {"partner_id": [1, "Alice"], "amount_total": 1000},
            {"partner_id": [1, "Alice"], "amount_total": 2000},
            {"partner_id": [2, "Bob"], "amount_total": 500},
        ]
        client.search_read.return_value = orders
        result = get_top_customers(client, limit=10)
        alice = next(r for r in result if r["partner_id"] == 1)
        assert alice["total_revenue"] == 3000
        bob = next(r for r in result if r["partner_id"] == 2)
        assert bob["total_revenue"] == 500
