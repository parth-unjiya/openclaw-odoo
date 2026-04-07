"""Tests for the accounting module."""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient


@pytest.fixture
def client():
    config = OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )
    c = OdooClient(config)
    c._session = MagicMock()
    return c


@pytest.fixture
def mock_client():
    """A fully mocked OdooClient for unit-testing module functions."""
    c = MagicMock(spec=OdooClient)
    c.base_url = "http://localhost:8069"
    c.web_url = lambda model, rid: f"http://localhost:8069/odoo/{model}/{rid}"
    return c


# ── create_invoice ───────────────────────────────────────────────────────────


class TestCreateInvoice:
    def test_creates_out_invoice(self, mock_client):
        from openclaw_odoo.modules.accounting import create_invoice

        mock_client.create.return_value = 42
        lines = [{"product_id": 1, "quantity": 2, "price_unit": 100.0}]
        result = create_invoice(mock_client, partner_id=10, lines=lines)

        mock_client.create.assert_called_once()
        args = mock_client.create.call_args
        assert args[0][0] == "account.move"
        vals = args[0][1]
        assert vals["move_type"] == "out_invoice"
        assert vals["partner_id"] == 10
        assert len(vals["invoice_line_ids"]) == 1
        assert result["id"] == 42
        assert "web_url" in result

    def test_creates_in_refund(self, mock_client):
        from openclaw_odoo.modules.accounting import create_invoice

        mock_client.create.return_value = 99
        lines = [{"name": "Refund line", "quantity": 1, "price_unit": 50.0}]
        result = create_invoice(
            mock_client, partner_id=5, lines=lines, move_type="in_refund"
        )

        vals = mock_client.create.call_args[0][1]
        assert vals["move_type"] == "in_refund"
        assert result["id"] == 99

    def test_passes_extra_kwargs(self, mock_client):
        from openclaw_odoo.modules.accounting import create_invoice

        mock_client.create.return_value = 1
        create_invoice(
            mock_client,
            partner_id=1,
            lines=[{"name": "X", "quantity": 1, "price_unit": 10}],
            ref="INV-001",
            narration="Test note",
        )
        vals = mock_client.create.call_args[0][1]
        assert vals["ref"] == "INV-001"
        assert vals["narration"] == "Test note"

    def test_line_with_account_id(self, mock_client):
        from openclaw_odoo.modules.accounting import create_invoice

        mock_client.create.return_value = 7
        lines = [
            {"product_id": 3, "quantity": 1, "price_unit": 200, "account_id": 55}
        ]
        create_invoice(mock_client, partner_id=1, lines=lines)
        vals = mock_client.create.call_args[0][1]
        line_cmd = vals["invoice_line_ids"][0]
        # Odoo command tuple: (0, 0, {vals})
        assert line_cmd[0] == 0
        assert line_cmd[1] == 0
        assert line_cmd[2]["account_id"] == 55


# ── create_bill ──────────────────────────────────────────────────────────────


class TestCreateBill:
    def test_creates_in_invoice(self, mock_client):
        from openclaw_odoo.modules.accounting import create_bill

        mock_client.create.return_value = 50
        lines = [{"name": "Supplies", "quantity": 5, "price_unit": 20}]
        result = create_bill(mock_client, partner_id=3, lines=lines)

        vals = mock_client.create.call_args[0][1]
        assert vals["move_type"] == "in_invoice"
        assert result["id"] == 50


# ── post_invoice ─────────────────────────────────────────────────────────────


class TestPostInvoice:
    def test_calls_action_post(self, mock_client):
        from openclaw_odoo.modules.accounting import post_invoice

        mock_client.execute.return_value = True
        result = post_invoice(mock_client, invoice_id=42)

        mock_client.execute.assert_called_once_with(
            "account.move", "action_post", [42]
        )
        assert result == {"success": True, "invoice_id": 42}


# ── send_invoice_email ────────────────────────────────────────────────────────


class TestSendInvoiceEmail:
    def test_happy_path(self, mock_client):
        """Full wizard flow: get action → create wizard → send mail."""
        from openclaw_odoo.modules.accounting import send_invoice_email

        wizard_action = {
            "context": {
                "default_composition_mode": "comment",
                "default_model": "account.move",
                "default_res_ids": [42],
                "default_template_id": 12,
                "default_email_layout_xmlid": "mail.mail_notification_light",
            }
        }
        # execute call 1: action_invoice_sent → wizard_action dict
        # execute call 2: mail.compose.message create → wizard_id 101
        # execute call 3: action_send_mail → True
        mock_client.execute.side_effect = [wizard_action, 101, True]

        result = send_invoice_email(mock_client, invoice_id=42)

        assert result["success"] is True
        assert result["invoice_id"] == 42
        assert result["message"] == "Invoice email sent"

        assert mock_client.execute.call_count == 3

        # Step 1: fetch wizard action
        step1 = mock_client.execute.call_args_list[0]
        assert step1 == call("account.move", "action_invoice_sent", [42])

        # Step 2: create mail.compose.message wizard
        step2 = mock_client.execute.call_args_list[1]
        assert step2[0][0] == "mail.compose.message"
        assert step2[0][1] == "create"
        wizard_vals = step2[0][2]
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "account.move"
        assert wizard_vals["res_ids"] == [42]
        assert wizard_vals["template_id"] == 12
        assert wizard_vals["email_layout_xmlid"] == "mail.mail_notification_light"

        # Step 3: send the email
        step3 = mock_client.execute.call_args_list[2]
        assert step3 == call("mail.compose.message", "action_send_mail", [101])

    def test_uses_defaults_when_context_keys_missing(self, mock_client):
        """When wizard action context is missing keys, defaults are applied."""
        from openclaw_odoo.modules.accounting import send_invoice_email

        wizard_action = {
            "context": {
                "default_template_id": 20,
            }
        }
        mock_client.execute.side_effect = [wizard_action, 200, True]

        result = send_invoice_email(mock_client, invoice_id=99)

        assert result["success"] is True
        assert result["invoice_id"] == 99

        step2 = mock_client.execute.call_args_list[1]
        wizard_vals = step2[0][2]
        # Defaults from the function code
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "account.move"
        assert wizard_vals["res_ids"] == [99]
        assert wizard_vals["template_id"] == 20
        assert wizard_vals["email_layout_xmlid"] == ""

    def test_empty_context_uses_all_defaults(self, mock_client):
        """When wizard action returns empty context, all defaults kick in."""
        from openclaw_odoo.modules.accounting import send_invoice_email

        wizard_action = {"context": {}}
        mock_client.execute.side_effect = [wizard_action, 50, True]

        result = send_invoice_email(mock_client, invoice_id=10)

        assert result["success"] is True

        step2 = mock_client.execute.call_args_list[1]
        wizard_vals = step2[0][2]
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "account.move"
        assert wizard_vals["res_ids"] == [10]
        assert wizard_vals["template_id"] is None
        assert wizard_vals["email_layout_xmlid"] == ""

    def test_no_context_key_in_action(self, mock_client):
        """When wizard action has no 'context' key at all, .get returns {}."""
        from openclaw_odoo.modules.accounting import send_invoice_email

        wizard_action = {"type": "ir.actions.act_window"}
        mock_client.execute.side_effect = [wizard_action, 77, True]

        result = send_invoice_email(mock_client, invoice_id=5)

        assert result["success"] is True
        assert result["invoice_id"] == 5

        step2 = mock_client.execute.call_args_list[1]
        wizard_vals = step2[0][2]
        assert wizard_vals["composition_mode"] == "comment"
        assert wizard_vals["model"] == "account.move"
        assert wizard_vals["res_ids"] == [5]
        assert wizard_vals["template_id"] is None

    def test_action_method_raises_propagates(self, mock_client):
        """If the action method call raises, the error propagates."""
        from openclaw_odoo.modules.accounting import send_invoice_email

        mock_client.execute.side_effect = Exception("RPC error")

        with pytest.raises(Exception, match="RPC error"):
            send_invoice_email(mock_client, invoice_id=1)


# ── register_payment ─────────────────────────────────────────────────────────


class TestRegisterPayment:
    def test_creates_payment_via_wizard(self, mock_client):
        from openclaw_odoo.modules.accounting import register_payment

        mock_client.search_read.return_value = [
            {"id": 42, "amount_residual": 500.0, "state": "posted"}
        ]
        mock_client.execute.side_effect = [
            100,    # wizard create returns wizard_id
            True,   # action_create_payments returns result
        ]

        result = register_payment(mock_client, invoice_id=42)

        # Should read the invoice first
        mock_client.search_read.assert_called_once()
        # Should call execute twice: create wizard, then action_create_payments
        assert mock_client.execute.call_count == 2
        # First call: create wizard with context
        create_call = mock_client.execute.call_args_list[0]
        assert create_call[0][0] == "account.payment.register"
        assert create_call[0][1] == "create"
        assert create_call[1]["context"] == {"active_model": "account.move", "active_ids": [42]}
        # Second call: action_create_payments
        action_call = mock_client.execute.call_args_list[1]
        assert action_call[0][0] == "account.payment.register"
        assert action_call[0][1] == "action_create_payments"
        assert action_call[0][2] == [100]
        assert action_call[1]["context"] == {"active_model": "account.move", "active_ids": [42]}
        # Result format
        assert result["success"] is True
        assert result["invoice_id"] == 42
        assert "wizard_result" in result

    def test_creates_payment_with_custom_amount(self, mock_client):
        from openclaw_odoo.modules.accounting import register_payment

        mock_client.search_read.return_value = [
            {"id": 42, "amount_residual": 500.0, "state": "posted"}
        ]
        mock_client.execute.side_effect = [101, True]

        result = register_payment(mock_client, invoice_id=42, amount=200.0)

        # Wizard create should include amount
        create_call = mock_client.execute.call_args_list[0]
        wizard_vals = create_call[0][2]
        assert wizard_vals["amount"] == 200.0
        assert result["success"] is True

    def test_creates_payment_with_journal(self, mock_client):
        from openclaw_odoo.modules.accounting import register_payment

        mock_client.search_read.return_value = [
            {"id": 42, "amount_residual": 300.0, "state": "posted"}
        ]
        mock_client.execute.side_effect = [102, True]

        register_payment(mock_client, invoice_id=42, journal_id=7)

        # Wizard create should include journal_id
        create_call = mock_client.execute.call_args_list[0]
        wizard_vals = create_call[0][2]
        assert wizard_vals["journal_id"] == 7

    def test_invoice_not_found_raises(self, mock_client):
        from openclaw_odoo.modules.accounting import register_payment
        from openclaw_odoo.errors import OdooRecordNotFoundError

        mock_client.search_read.return_value = []

        with pytest.raises(OdooRecordNotFoundError):
            register_payment(mock_client, invoice_id=999)


# ── get_unpaid_invoices ──────────────────────────────────────────────────────


class TestGetUnpaidInvoices:
    def test_default_out_invoice(self, mock_client):
        from openclaw_odoo.modules.accounting import get_unpaid_invoices

        mock_client.search_read.return_value = [
            {"id": 1, "name": "INV/001", "amount_residual": 500}
        ]
        result = get_unpaid_invoices(mock_client)

        domain = mock_client.search_read.call_args[1]["domain"]
        assert ["move_type", "=", "out_invoice"] in domain
        assert ["payment_state", "in", ("not_paid", "partial")] in domain
        assert len(result) == 1

    def test_in_invoice(self, mock_client):
        from openclaw_odoo.modules.accounting import get_unpaid_invoices

        mock_client.search_read.return_value = []
        get_unpaid_invoices(mock_client, move_type="in_invoice")

        domain = mock_client.search_read.call_args[1]["domain"]
        assert ["move_type", "=", "in_invoice"] in domain


# ── get_overdue_invoices ─────────────────────────────────────────────────────


class TestGetOverdueInvoices:
    def test_filters_by_due_date(self, mock_client):
        from openclaw_odoo.modules.accounting import get_overdue_invoices

        mock_client.search_read.return_value = [
            {"id": 1, "name": "INV/001", "invoice_date_due": "2025-01-01"}
        ]
        result = get_overdue_invoices(mock_client)

        domain = mock_client.search_read.call_args[1]["domain"]
        # Should have invoice_date_due < today
        due_filter = [d for d in domain if isinstance(d, list) and d[0] == "invoice_date_due"]
        assert len(due_filter) == 1
        assert due_filter[0][1] == "<"
        assert len(result) == 1


# ── analyze_financial_ratios ─────────────────────────────────────────────────


class TestAnalyzeFinancialRatios:
    def test_returns_ratio_dict(self, mock_client):
        from openclaw_odoo.modules.accounting import analyze_financial_ratios

        # Single search_read call returns all accounts with their types
        mock_client.search_read.return_value = [
            {"id": 1, "account_type": "asset_current", "current_balance": -3000.0},
            {"id": 2, "account_type": "asset_cash", "current_balance": -5000.0},
            {"id": 3, "account_type": "asset_receivable", "current_balance": -2000.0},
            {"id": 4, "account_type": "liability_current", "current_balance": 3000.0},
            {"id": 5, "account_type": "liability_payable", "current_balance": 2000.0},
            {"id": 6, "account_type": "income", "current_balance": -20000.0},
            {"id": 7, "account_type": "income_other", "current_balance": -5000.0},
        ]

        result = analyze_financial_ratios(mock_client)

        assert "current_ratio" in result
        assert "quick_ratio" in result
        assert "ar_turnover" in result
        assert "ap_turnover" in result
        # Only 1 search_read call (batch)
        mock_client.search_read.assert_called_once()

    def test_handles_zero_liabilities(self, mock_client):
        from openclaw_odoo.modules.accounting import analyze_financial_ratios

        mock_client.search_read.return_value = []

        result = analyze_financial_ratios(mock_client)

        # Should not crash; ratios should be 0 for undefined
        assert result["current_ratio"] == 0
        assert result["quick_ratio"] == 0


# ── get_cashflow_summary ─────────────────────────────────────────────────────


class TestGetCashflowSummary:
    def test_returns_summary_dict(self, mock_client):
        from openclaw_odoo.modules.accounting import get_cashflow_summary

        mock_client.search_read.return_value = [
            {"id": 1, "balance": -5000.0, "account_id": [1, "Revenue"]},
            {"id": 2, "balance": 3000.0, "account_id": [2, "Expense"]},
        ]

        result = get_cashflow_summary(mock_client)

        assert "total_income" in result
        assert "total_expense" in result
        assert "net_cashflow" in result

    def test_with_date_range(self, mock_client):
        from openclaw_odoo.modules.accounting import get_cashflow_summary

        mock_client.search_read.return_value = []

        get_cashflow_summary(
            mock_client, date_from="2025-01-01", date_to="2025-12-31"
        )

        # Check both calls (income + expense) include date filters
        for c in mock_client.search_read.call_args_list:
            domain = c[1]["domain"]
            date_filters = [d for d in domain if isinstance(d, list) and d[0] == "date"]
            assert len(date_filters) == 2


# ── get_revenue_vs_expense ───────────────────────────────────────────────────


class TestGetRevenueVsExpense:
    def test_returns_monthly_list(self, mock_client):
        from openclaw_odoo.modules.accounting import get_revenue_vs_expense

        today = date.today()
        # Compute a month label that falls within the 6-month window
        m = today.month
        y = today.year
        current_label = f"{y:04d}-{m:02d}"

        # Two batch calls: income lines, then expense lines
        mock_client.search_read.side_effect = [
            # Income lines (1st call)
            [
                {"id": 1, "date": f"{current_label}-15", "balance": -1000.0},
            ],
            # Expense lines (2nd call)
            [
                {"id": 2, "date": f"{current_label}-20", "balance": 500.0},
            ],
        ]

        result = get_revenue_vs_expense(mock_client, months=6)

        assert isinstance(result, list)
        assert len(result) == 6
        for entry in result:
            assert "month" in entry
            assert "revenue" in entry
            assert "expense" in entry
            assert "profit" in entry
        # Only 2 search_read calls (income + expense)
        assert mock_client.search_read.call_count == 2

    def test_default_months_is_6(self, mock_client):
        from openclaw_odoo.modules.accounting import get_revenue_vs_expense

        mock_client.search_read.return_value = []
        result = get_revenue_vs_expense(mock_client)
        assert len(result) == 6


# ── get_aging_report ─────────────────────────────────────────────────────────


class TestGetAgingReport:
    def test_returns_bucket_structure(self, mock_client):
        from openclaw_odoo.modules.accounting import get_aging_report

        today = date.today()
        mock_client.search_read.return_value = [
            {
                "id": 1,
                "invoice_date_due": str(today - timedelta(days=10)),
                "amount_residual": 100.0,
            },
            {
                "id": 2,
                "invoice_date_due": str(today - timedelta(days=45)),
                "amount_residual": 200.0,
            },
            {
                "id": 3,
                "invoice_date_due": str(today - timedelta(days=75)),
                "amount_residual": 300.0,
            },
            {
                "id": 4,
                "invoice_date_due": str(today - timedelta(days=100)),
                "amount_residual": 400.0,
            },
        ]

        result = get_aging_report(mock_client)

        assert "0-30" in result
        assert "31-60" in result
        assert "61-90" in result
        assert "90+" in result

        assert result["0-30"]["count"] == 1
        assert result["0-30"]["amount"] == 100.0
        assert result["31-60"]["count"] == 1
        assert result["31-60"]["amount"] == 200.0
        assert result["61-90"]["count"] == 1
        assert result["61-90"]["amount"] == 300.0
        assert result["90+"]["count"] == 1
        assert result["90+"]["amount"] == 400.0

    def test_filters_by_move_type(self, mock_client):
        from openclaw_odoo.modules.accounting import get_aging_report

        mock_client.search_read.return_value = []
        get_aging_report(mock_client, move_type="in_invoice")

        domain = mock_client.search_read.call_args[1]["domain"]
        assert ["move_type", "=", "in_invoice"] in domain

    def test_empty_invoices(self, mock_client):
        from openclaw_odoo.modules.accounting import get_aging_report

        mock_client.search_read.return_value = []
        result = get_aging_report(mock_client)

        for bucket in ("0-30", "31-60", "61-90", "90+"):
            assert result[bucket]["count"] == 0
            assert result[bucket]["amount"] == 0.0
