"""Tests for cross-module business analytics."""
import pytest
from unittest.mock import MagicMock

from openclaw_odoo.config import OdooClawConfig
from openclaw_odoo.client import OdooClient
from openclaw_odoo.intelligence.analytics import (
    analyze_sales_performance,
    analyze_financial_ratios,
    analyze_inventory_turnover,
    get_customer_insights,
)


@pytest.fixture
def client():
    config = OdooClawConfig(
        odoo_url="http://localhost:8069",
        odoo_db="testdb",
        odoo_api_key="test-key",
    )
    c = OdooClient(config)
    c.create = MagicMock()
    c.write = MagicMock(return_value=True)
    c.read = MagicMock()
    c.search_read = MagicMock(return_value=[])
    c.search_count = MagicMock(return_value=0)
    c.execute = MagicMock()
    return c


# ---- analyze_sales_performance ----

class TestAnalyzeSalesPerformance:
    def test_basic_sales_analysis(self, client):
        # Orders
        client.search_read.side_effect = [
            # sale.order search
            [
                {"id": 1, "amount_total": 1000, "date_order": "2026-01-15", "partner_id": [1, "Acme"]},
                {"id": 2, "amount_total": 2000, "date_order": "2026-02-10", "partner_id": [2, "Beta"]},
                {"id": 3, "amount_total": 1500, "date_order": "2026-01-20", "partner_id": [1, "Acme"]},
            ],
            # sale.order.line search for top products
            [
                {"product_id": [10, "Widget A"], "price_subtotal": 2000, "product_uom_qty": 10},
                {"product_id": [11, "Widget B"], "price_subtotal": 1500, "product_uom_qty": 5},
                {"product_id": [10, "Widget A"], "price_subtotal": 1000, "product_uom_qty": 8},
            ],
        ]
        result = analyze_sales_performance(client)
        assert result["total_orders"] == 3
        assert result["total_revenue"] == 4500
        assert result["avg_order_value"] == 1500.0
        assert len(result["top_products"]) > 0
        # Widget A should be first (3000 total)
        assert result["top_products"][0]["product_name"] == "Widget A"

    def test_with_date_range(self, client):
        client.search_read.side_effect = [
            [{"id": 1, "amount_total": 500, "date_order": "2026-01-15", "partner_id": [1, "X"]}],
            [],
        ]
        result = analyze_sales_performance(client, date_from="2026-01-01", date_to="2026-01-31")
        # Check that date filters were applied
        call_args = client.search_read.call_args_list[0]
        domain = call_args[1].get("domain", call_args[0][1] if len(call_args[0]) > 1 else [])
        assert any("date_order" in str(d) for d in domain)
        assert result["total_orders"] == 1

    def test_empty_orders(self, client):
        client.search_read.side_effect = [[], []]
        result = analyze_sales_performance(client)
        assert result["total_orders"] == 0
        assert result["total_revenue"] == 0
        assert result["avg_order_value"] == 0
        assert result["top_products"] == []

    def test_includes_top_customers(self, client):
        client.search_read.side_effect = [
            [
                {"id": 1, "amount_total": 3000, "date_order": "2026-01-15", "partner_id": [1, "Acme"]},
                {"id": 2, "amount_total": 1000, "date_order": "2026-02-10", "partner_id": [2, "Beta"]},
                {"id": 3, "amount_total": 2000, "date_order": "2026-01-20", "partner_id": [1, "Acme"]},
            ],
            [],
        ]
        result = analyze_sales_performance(client)
        assert "top_customers" in result
        assert result["top_customers"][0]["partner_name"] == "Acme"
        assert result["top_customers"][0]["total_revenue"] == 5000


# ---- analyze_financial_ratios ----

class TestAnalyzeFinancialRatios:
    def test_computes_ratios(self, client):
        # Single batch call returns all accounts with their types
        client.search_read.return_value = [
            {"id": 1, "account_type": "asset_cash", "current_balance": -5000},
            {"id": 2, "account_type": "asset_receivable", "current_balance": -3000},
            {"id": 3, "account_type": "liability_current", "current_balance": 2000},
            {"id": 4, "account_type": "liability_payable", "current_balance": 2000},
            {"id": 5, "account_type": "income", "current_balance": -20000},
        ]
        result = analyze_financial_ratios(client)
        assert "current_ratio" in result
        assert "quick_ratio" in result
        assert "ar_turnover" in result
        assert "ap_turnover" in result
        assert isinstance(result["current_ratio"], float)
        # Only 1 search_read call (batch)
        assert client.search_read.call_count == 1

    def test_handles_zero_liabilities(self, client):
        client.search_read.return_value = []
        result = analyze_financial_ratios(client)
        assert result["current_ratio"] == 0
        assert result["quick_ratio"] == 0


# ---- analyze_inventory_turnover ----

class TestAnalyzeInventoryTurnover:
    def test_computes_turnover(self, client):
        client.search_read.side_effect = [
            # stock.move (outgoing, done)
            [
                {"product_id": [10, "Widget A"], "product_qty": 100, "price_unit": 50},
                {"product_id": [10, "Widget A"], "product_qty": 50, "price_unit": 50},
                {"product_id": [11, "Widget B"], "product_qty": 30, "price_unit": 100},
            ],
            # product.product with stock info
            [
                {"id": 10, "name": "Widget A", "qty_available": 200, "standard_price": 50},
                {"id": 11, "name": "Widget B", "qty_available": 50, "standard_price": 100},
            ],
        ]
        result = analyze_inventory_turnover(client)
        assert len(result) == 2
        widget_a = next(r for r in result if r["product_id"] == 10)
        assert widget_a["cogs"] == 7500  # (100+50)*50
        assert widget_a["avg_inventory_value"] == 10000  # 200*50
        assert widget_a["turnover_ratio"] == 0.75

    def test_with_date_filter(self, client):
        client.search_read.side_effect = [[], []]
        result = analyze_inventory_turnover(client, date_from="2026-01-01", date_to="2026-03-01")
        call_domain = client.search_read.call_args_list[0][1].get(
            "domain", client.search_read.call_args_list[0][0][1] if len(client.search_read.call_args_list[0][0]) > 1 else []
        )
        assert any("date" in str(d) for d in call_domain)

    def test_empty_moves(self, client):
        client.search_read.side_effect = [[]]
        result = analyze_inventory_turnover(client)
        assert result == []

    def test_handles_zero_inventory_value(self, client):
        client.search_read.side_effect = [
            [{"product_id": [10, "Widget"], "product_qty": 50, "price_unit": 100}],
            [{"id": 10, "name": "Widget", "qty_available": 0, "standard_price": 0}],
        ]
        result = analyze_inventory_turnover(client)
        assert result[0]["turnover_ratio"] is None


# ---- get_customer_insights ----

class TestGetCustomerInsights:
    def test_returns_insights_for_partner(self, client):
        client.search_read.side_effect = [
            # sale.order for this partner
            [
                {"id": 1, "amount_total": 2000, "date_order": "2026-01-15"},
                {"id": 2, "amount_total": 3000, "date_order": "2026-02-20"},
                {"id": 3, "amount_total": 1000, "date_order": "2025-06-01"},
            ],
            # sale.order.line for purchased products
            [
                {"product_id": [10, "Widget A"], "price_subtotal": 3000, "product_uom_qty": 10},
                {"product_id": [11, "Widget B"], "price_subtotal": 2000, "product_uom_qty": 5},
                {"product_id": [10, "Widget A"], "price_subtotal": 1000, "product_uom_qty": 3},
            ],
            # account.move for invoices
            [
                {"id": 100, "amount_residual": 500, "payment_state": "partial"},
                {"id": 101, "amount_residual": 0, "payment_state": "paid"},
            ],
        ]
        result = get_customer_insights(client, partner_id=42)
        assert result["partner_id"] == 42
        assert result["total_orders"] == 3
        assert result["total_revenue"] == 6000
        assert result["avg_order_value"] == 2000
        assert len(result["top_products"]) > 0
        assert result["top_products"][0]["product_name"] == "Widget A"
        assert result["outstanding_amount"] == 500

    def test_empty_customer(self, client):
        client.search_read.side_effect = [[], [], []]
        result = get_customer_insights(client, partner_id=99)
        assert result["total_orders"] == 0
        assert result["total_revenue"] == 0
        assert result["avg_order_value"] == 0
        assert result["top_products"] == []
        assert result["outstanding_amount"] == 0

    def test_last_order_date(self, client):
        client.search_read.side_effect = [
            [
                {"id": 1, "amount_total": 1000, "date_order": "2025-06-01"},
                {"id": 2, "amount_total": 2000, "date_order": "2026-03-01"},
            ],
            [],
            [],
        ]
        result = get_customer_insights(client, partner_id=42)
        assert result["last_order_date"] == "2026-03-01"


# ---- Dashboard Aggregator Classes ----

from unittest.mock import patch
from openclaw_odoo.intelligence.analytics import (
    SalesAnalytics,
    FinancialAnalytics,
    InventoryAnalytics,
    HRAnalytics,
    PipelineAnalytics,
    full_business_dashboard,
)


class TestSalesAnalytics:
    def test_dashboard_combines_all(self, client):
        with patch("openclaw_odoo.intelligence.analytics.sales") as mock_sales:
            mock_sales.analyze_sales.return_value = {
                "total_orders": 10, "total_revenue": 50000,
                "avg_order_value": 5000, "top_products": [],
            }
            mock_sales.get_sales_trend.return_value = [
                {"month": "2026-01", "revenue": 20000, "order_count": 4, "change_pct": None},
                {"month": "2026-02", "revenue": 30000, "order_count": 6, "change_pct": 50.0},
            ]
            mock_sales.get_top_products.return_value = [
                {"product_id": 1, "product_name": "Widget", "total_revenue": 30000, "total_qty": 100},
            ]
            sa = SalesAnalytics(client)
            result = sa.dashboard()
            assert result["summary"]["total_orders"] == 10
            assert result["summary"]["total_revenue"] == 50000
            assert len(result["trend"]) == 2
            assert result["top_products"][0]["product_name"] == "Widget"
            mock_sales.analyze_sales.assert_called_once_with(client)
            mock_sales.get_sales_trend.assert_called_once_with(client)
            mock_sales.get_top_products.assert_called_once_with(client)

    def test_compare_periods(self, client):
        with patch("openclaw_odoo.intelligence.analytics.sales") as mock_sales:
            mock_sales.analyze_sales.side_effect = [
                {"total_orders": 5, "total_revenue": 20000, "avg_order_value": 4000, "top_products": []},
                {"total_orders": 8, "total_revenue": 35000, "avg_order_value": 4375, "top_products": []},
            ]
            sa = SalesAnalytics(client)
            result = sa.compare_periods("2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28")
            assert result["period1"]["total_orders"] == 5
            assert result["period2"]["total_orders"] == 8
            assert result["period1"]["total_revenue"] == 20000
            assert result["period2"]["total_revenue"] == 35000
            assert result["revenue_change_pct"] == 75.0
            assert result["order_change_pct"] == 60.0

    def test_compare_periods_zero_base(self, client):
        with patch("openclaw_odoo.intelligence.analytics.sales") as mock_sales:
            mock_sales.analyze_sales.side_effect = [
                {"total_orders": 0, "total_revenue": 0, "avg_order_value": 0, "top_products": []},
                {"total_orders": 5, "total_revenue": 10000, "avg_order_value": 2000, "top_products": []},
            ]
            sa = SalesAnalytics(client)
            result = sa.compare_periods("2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28")
            assert result["revenue_change_pct"] is None
            assert result["order_change_pct"] is None


class TestFinancialAnalytics:
    def test_dashboard_combines_all(self, client):
        with patch("openclaw_odoo.intelligence.analytics.accounting") as mock_acc:
            mock_acc.analyze_financial_ratios.return_value = {
                "current_ratio": 2.5, "quick_ratio": 1.8,
                "ar_turnover": 5.0, "ap_turnover": 3.0,
            }
            mock_acc.get_cashflow_summary.return_value = {
                "total_income": 100000, "total_expense": 60000, "net_cashflow": 40000,
            }
            mock_acc.get_aging_report.return_value = {
                "0-30": {"count": 5, "amount": 10000},
                "31-60": {"count": 2, "amount": 5000},
                "61-90": {"count": 1, "amount": 2000},
                "90+": {"count": 0, "amount": 0},
            }
            fa = FinancialAnalytics(client)
            result = fa.dashboard()
            assert result["ratios"]["current_ratio"] == 2.5
            assert result["cashflow"]["net_cashflow"] == 40000
            assert result["aging"]["0-30"]["count"] == 5

    def test_profit_loss(self, client):
        with patch("openclaw_odoo.intelligence.analytics.accounting") as mock_acc:
            mock_acc.get_cashflow_summary.return_value = {
                "total_income": 80000, "total_expense": 50000, "net_cashflow": 30000,
            }
            fa = FinancialAnalytics(client)
            result = fa.profit_loss("2026-01-01", "2026-01-31")
            assert result["revenue"] == 80000
            assert result["expenses"] == 50000
            assert result["net_profit"] == 30000
            mock_acc.get_cashflow_summary.assert_called_once_with(
                client, date_from="2026-01-01", date_to="2026-01-31"
            )


class TestInventoryAnalytics:
    def test_dashboard_combines_all(self, client):
        with patch("openclaw_odoo.intelligence.analytics.inventory") as mock_inv:
            mock_inv.analyze_inventory_turnover.return_value = [
                {"product_id": 1, "name": "A", "turnover_ratio": 2.0,
                 "cogs": 10000, "avg_inventory_value": 5000},
            ]
            mock_inv.get_stock_valuation.return_value = {
                "total_valuation": 50000,
                "products": [{"product_id": 1, "name": "A", "valuation": 50000,
                              "qty_available": 100, "standard_price": 500}],
            }
            mock_inv.get_low_stock.return_value = [
                {"id": 2, "name": "B", "qty_available": 3},
            ]
            ia = InventoryAnalytics(client)
            result = ia.dashboard()
            assert len(result["turnover"]) == 1
            assert result["valuation"]["total_valuation"] == 50000
            assert len(result["low_stock"]) == 1

    def test_abc_analysis(self, client):
        with patch("openclaw_odoo.intelligence.analytics.inventory") as mock_inv:
            mock_inv.get_stock_valuation.return_value = {
                "total_valuation": 100000,
                "products": [
                    {"product_id": 1, "name": "Big", "valuation": 60000,
                     "qty_available": 10, "standard_price": 6000},
                    {"product_id": 2, "name": "Medium", "valuation": 25000,
                     "qty_available": 50, "standard_price": 500},
                    {"product_id": 3, "name": "Small1", "valuation": 10000,
                     "qty_available": 100, "standard_price": 100},
                    {"product_id": 4, "name": "Small2", "valuation": 5000,
                     "qty_available": 200, "standard_price": 25},
                ],
            }
            ia = InventoryAnalytics(client)
            result = ia.abc_analysis()
            assert "A" in result
            assert "B" in result
            assert "C" in result
            # Big (60%) + Medium (25%) = 85% > 80%, so Big is A, Medium starts B
            a_ids = [p["product_id"] for p in result["A"]]
            assert 1 in a_ids  # Big is definitely A class
            # All products should appear somewhere
            all_ids = set()
            for cat in ("A", "B", "C"):
                for p in result[cat]:
                    all_ids.add(p["product_id"])
            assert all_ids == {1, 2, 3, 4}

    def test_abc_analysis_empty(self, client):
        with patch("openclaw_odoo.intelligence.analytics.inventory") as mock_inv:
            mock_inv.get_stock_valuation.return_value = {
                "total_valuation": 0, "products": [],
            }
            ia = InventoryAnalytics(client)
            result = ia.abc_analysis()
            assert result == {"A": [], "B": [], "C": []}


class TestHRAnalytics:
    def test_dashboard_combines_all(self, client):
        with patch("openclaw_odoo.intelligence.analytics.hr") as mock_hr:
            mock_hr.get_headcount_summary.return_value = {
                "total_employees": 50, "active": 48, "inactive": 2,
                "per_department": [
                    {"department": [1, "Engineering"], "count": 20},
                    {"department": [2, "Sales"], "count": 15},
                ],
            }
            mock_hr.get_attendance.return_value = [
                {"id": 1, "employee_id": [1, "Alice"], "check_in": "2026-03-06 09:00:00", "check_out": "2026-03-06 17:00:00"},
                {"id": 2, "employee_id": [2, "Bob"], "check_in": "2026-03-06 09:30:00", "check_out": False},
            ]
            mock_hr.get_leaves.return_value = [
                {"id": 1, "employee_id": [3, "Charlie"], "state": "validate"},
                {"id": 2, "employee_id": [4, "Diana"], "state": "confirm"},
            ]
            hra = HRAnalytics(client)
            result = hra.dashboard()
            assert result["headcount"]["total_employees"] == 50
            assert result["attendance_today"]["total_records"] == 2
            assert result["leaves"]["total_leaves"] == 2

    def test_department_costs(self, client):
        with patch("openclaw_odoo.intelligence.analytics.hr") as mock_hr:
            mock_hr.get_departments.return_value = [
                {"id": 1, "name": "Engineering", "manager_id": [1, "Boss"], "parent_id": False},
                {"id": 2, "name": "Sales", "manager_id": [2, "Lead"], "parent_id": False},
            ]
            # Batched queries via client.search_read:
            # 1st call: all employees in departments [1, 2]
            # 2nd call: all expenses for employees [1, 2]
            client.search_read.side_effect = [
                [
                    {"id": 1, "department_id": [1, "Engineering"]},
                    {"id": 2, "department_id": [2, "Sales"]},
                ],
                [
                    {"id": 1, "employee_id": [1, "A"], "total_amount_currency": 500},
                    {"id": 2, "employee_id": [2, "B"], "total_amount_currency": 100},
                ],
            ]
            hra = HRAnalytics(client)
            result = hra.department_costs()
            assert isinstance(result, list)
            assert len(result) == 2
            eng = next(d for d in result if d["department"] == "Engineering")
            assert eng["total_expenses"] == 500
            assert eng["employee_count"] == 1
            sales_dept = next(d for d in result if d["department"] == "Sales")
            assert sales_dept["total_expenses"] == 100
            assert sales_dept["employee_count"] == 1
            # Verify batched: only 2 search_read calls instead of N+1
            assert client.search_read.call_count == 2

    def test_department_costs_no_expenses(self, client):
        with patch("openclaw_odoo.intelligence.analytics.hr") as mock_hr:
            mock_hr.get_departments.return_value = [
                {"id": 1, "name": "Engineering", "manager_id": False, "parent_id": False},
            ]
            # Batched: 1st call returns employees, 2nd returns empty expenses
            client.search_read.side_effect = [
                [{"id": 1, "department_id": [1, "Engineering"]}],
                [],
            ]
            hra = HRAnalytics(client)
            result = hra.department_costs()
            assert result[0]["total_expenses"] == 0
            assert result[0]["employee_count"] == 1

    def test_department_costs_empty_departments(self, client):
        with patch("openclaw_odoo.intelligence.analytics.hr") as mock_hr:
            mock_hr.get_departments.return_value = []
            hra = HRAnalytics(client)
            result = hra.department_costs()
            assert result == []

    def test_department_costs_with_date_filter(self, client):
        with patch("openclaw_odoo.intelligence.analytics.hr") as mock_hr:
            mock_hr.get_departments.return_value = [
                {"id": 1, "name": "Engineering", "manager_id": False, "parent_id": False},
            ]
            client.search_read.side_effect = [
                [{"id": 1, "department_id": [1, "Engineering"]}],
                [{"employee_id": [1, "A"], "total_amount_currency": 200}],
            ]
            hra = HRAnalytics(client)
            result = hra.department_costs(date_from="2026-01-01", date_to="2026-03-31")
            assert result[0]["total_expenses"] == 200
            # Verify date filters were passed to the expense query
            expense_call = client.search_read.call_args_list[1]
            expense_domain = expense_call[1].get("domain") or expense_call[0][1]
            assert ["date", ">=", "2026-01-01"] in expense_domain
            assert ["date", "<=", "2026-03-31"] in expense_domain


class TestPipelineAnalytics:
    def test_dashboard_combines_all(self, client):
        with patch("openclaw_odoo.intelligence.analytics.crm") as mock_crm:
            mock_crm.analyze_pipeline.return_value = {
                "total_leads": 100, "total_opportunities": 50,
                "total_revenue": 500000, "win_rate": 25.0,
                "conversion_per_stage": {"New": 20, "Qualified": 15, "Won": 15},
            }
            mock_crm.get_forecast.return_value = {
                "weighted_revenue": 125000, "opportunity_count": 50,
                "opportunities": [],
            }
            pa = PipelineAnalytics(client)
            result = pa.dashboard()
            assert result["pipeline"]["total_leads"] == 100
            assert result["pipeline"]["win_rate"] == 25.0
            assert result["forecast"]["weighted_revenue"] == 125000

    def test_conversion_funnel(self, client):
        with patch("openclaw_odoo.intelligence.analytics.crm") as mock_crm:
            mock_crm.get_stages.return_value = [
                {"id": 1, "name": "New", "sequence": 1, "is_won": False},
                {"id": 2, "name": "Qualified", "sequence": 2, "is_won": False},
                {"id": 3, "name": "Proposition", "sequence": 3, "is_won": False},
                {"id": 4, "name": "Won", "sequence": 4, "is_won": True},
            ]
            mock_crm.get_pipeline.return_value = [
                {"stage": "New", "opportunities": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]},
                {"stage": "Qualified", "opportunities": [{"id": 1}, {"id": 2}, {"id": 3}]},
                {"stage": "Proposition", "opportunities": [{"id": 1}, {"id": 2}]},
                {"stage": "Won", "opportunities": [{"id": 1}]},
            ]
            pa = PipelineAnalytics(client)
            result = pa.conversion_funnel()
            assert isinstance(result, list)
            assert len(result) == 4
            assert result[0]["stage"] == "New"
            assert result[0]["count"] == 5
            # Qualified: 3 out of 5 from New = 60%
            assert result[1]["stage"] == "Qualified"
            assert result[1]["count"] == 3
            assert result[1]["conversion_pct"] == 60.0

    def test_conversion_funnel_empty(self, client):
        with patch("openclaw_odoo.intelligence.analytics.crm") as mock_crm:
            mock_crm.get_stages.return_value = []
            mock_crm.get_pipeline.return_value = []
            pa = PipelineAnalytics(client)
            result = pa.conversion_funnel()
            assert result == []


class TestFullBusinessDashboard:
    def test_returns_all_sections(self, client):
        with patch("openclaw_odoo.intelligence.analytics.sales") as mock_sales, \
             patch("openclaw_odoo.intelligence.analytics.accounting") as mock_acc, \
             patch("openclaw_odoo.intelligence.analytics.inventory") as mock_inv, \
             patch("openclaw_odoo.intelligence.analytics.hr") as mock_hr, \
             patch("openclaw_odoo.intelligence.analytics.crm") as mock_crm:

            mock_sales.analyze_sales.return_value = {"total_orders": 10, "total_revenue": 50000, "avg_order_value": 5000, "top_products": []}
            mock_sales.get_sales_trend.return_value = []
            mock_sales.get_top_products.return_value = []

            mock_acc.analyze_financial_ratios.return_value = {"current_ratio": 2.0, "quick_ratio": 1.5, "ar_turnover": 4.0, "ap_turnover": 3.0}
            mock_acc.get_cashflow_summary.return_value = {"total_income": 80000, "total_expense": 40000, "net_cashflow": 40000}
            mock_acc.get_aging_report.return_value = {"0-30": {"count": 0, "amount": 0}, "31-60": {"count": 0, "amount": 0}, "61-90": {"count": 0, "amount": 0}, "90+": {"count": 0, "amount": 0}}

            mock_inv.analyze_inventory_turnover.return_value = []
            mock_inv.get_stock_valuation.return_value = {"total_valuation": 0, "products": []}
            mock_inv.get_low_stock.return_value = []

            mock_hr.get_headcount_summary.return_value = {"total_employees": 10, "active": 10, "inactive": 0, "per_department": []}
            mock_hr.get_attendance.return_value = []
            mock_hr.get_leaves.return_value = []

            mock_crm.analyze_pipeline.return_value = {"total_leads": 0, "total_opportunities": 0, "total_revenue": 0, "win_rate": 0, "conversion_per_stage": {}}
            mock_crm.get_forecast.return_value = {"weighted_revenue": 0, "opportunity_count": 0, "opportunities": []}

            result = full_business_dashboard(client)
            assert "sales" in result
            assert "financial" in result
            assert "inventory" in result
            assert "hr" in result
            assert "pipeline" in result
            assert result["sales"]["summary"]["total_orders"] == 10
            assert result["hr"]["headcount"]["total_employees"] == 10
