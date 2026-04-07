"""Cross-module business analytics -- sales, financial, inventory, customer."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from ..client import OdooClient
from ..modules import sales, accounting, inventory, crm, hr
from ..modules.sales import _aggregate_products


def analyze_sales_performance(
    client: OdooClient,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    top_n: int = 5,
) -> dict:
    """Aggregate sales KPIs: revenue, order count, top products, top customers."""
    domain: list = [["state", "in", ["sale", "done"]]]
    if date_from:
        domain.append(["date_order", ">=", date_from])
    if date_to:
        domain.append(["date_order", "<=", date_to])

    orders = client.search_read(
        "sale.order",
        domain=domain,
        fields=["amount_total", "date_order", "partner_id"],
        limit=0,
    )

    total_orders = len(orders)
    total_revenue = sum(o["amount_total"] for o in orders)
    avg_order_value = total_revenue / total_orders if total_orders else 0.0

    # Top customers
    revenue_by_partner: dict[int, dict] = defaultdict(
        lambda: {"partner_id": 0, "partner_name": "", "total_revenue": 0.0}
    )
    for o in orders:
        pid = o.get("partner_id")
        if isinstance(pid, (list, tuple)) and len(pid) > 1:
            partner_id, partner_name = pid[0], pid[1]
        else:
            partner_id, partner_name = pid, str(pid)
        entry = revenue_by_partner[partner_id]
        entry["partner_id"] = partner_id
        entry["partner_name"] = partner_name
        entry["total_revenue"] += o.get("amount_total", 0)

    top_customers = sorted(
        revenue_by_partner.values(), key=lambda x: x["total_revenue"], reverse=True
    )[:top_n]

    # Top products from order lines
    order_ids = [o["id"] for o in orders if o.get("id")]
    if order_ids:
        line_domain: list = [["order_id", "in", order_ids]]
    else:
        line_domain = [["order_id.state", "in", ["sale", "done"]]]

    lines = client.search_read(
        "sale.order.line",
        domain=line_domain,
        fields=["product_id", "price_subtotal", "product_uom_qty"],
        limit=0,
    )
    top_products = _aggregate_products(lines, limit=top_n)

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "avg_order_value": avg_order_value,
        "top_products": top_products,
        "top_customers": top_customers,
    }


def analyze_financial_ratios(client: OdooClient) -> dict:
    """Compute key financial ratios from account balances.

    Delegates to :func:`accounting.analyze_financial_ratios`.
    """
    return accounting.analyze_financial_ratios(client)


def analyze_inventory_turnover(
    client: OdooClient,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Compute inventory turnover ratio per product from stock moves.

    Delegates to :func:`inventory.analyze_inventory_turnover`.
    """
    return inventory.analyze_inventory_turnover(
        client, date_from=date_from, date_to=date_to,
    )


def get_customer_insights(client: OdooClient, partner_id: int) -> dict:
    """Detailed analytics for a single customer: orders, products, outstanding."""
    orders = client.search_read(
        "sale.order",
        domain=[
            ["partner_id", "=", partner_id],
            ["state", "in", ["sale", "done"]],
        ],
        fields=["amount_total", "date_order"],
        limit=0,
    )

    total_orders = len(orders)
    total_revenue = sum(o["amount_total"] for o in orders)
    avg_order_value = total_revenue / total_orders if total_orders else 0.0

    dates = [o["date_order"] for o in orders if o.get("date_order")]
    last_order_date = max(dates) if dates else None

    # Top purchased products
    order_ids = [o["id"] for o in orders if o.get("id")]
    if order_ids:
        lines = client.search_read(
            "sale.order.line",
            domain=[["order_id", "in", order_ids]],
            fields=["product_id", "price_subtotal", "product_uom_qty"],
            limit=0,
        )
    else:
        lines = []
    top_products = _aggregate_products(lines, limit=5)

    # Outstanding invoices
    invoices = client.search_read(
        "account.move",
        domain=[
            ["partner_id", "=", partner_id],
            ["move_type", "=", "out_invoice"],
            ["payment_state", "in", ("not_paid", "partial")],
            ["state", "=", "posted"],
        ],
        fields=["amount_residual"],
        limit=0,
    )
    outstanding = sum(inv.get("amount_residual", 0) for inv in invoices)

    return {
        "partner_id": partner_id,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "avg_order_value": avg_order_value,
        "last_order_date": last_order_date,
        "top_products": top_products,
        "outstanding_amount": outstanding,
    }


# ---- Dashboard Aggregator Classes ----


class SalesAnalytics:
    """Sales dashboard aggregator."""

    def __init__(self, client: OdooClient):
        self.client = client

    def dashboard(self) -> dict:
        """Return combined sales summary, trend, and top products."""
        return {
            "summary": sales.analyze_sales(self.client),
            "trend": sales.get_sales_trend(self.client),
            "top_products": sales.get_top_products(self.client),
        }

    def compare_periods(
        self, period1_from: str, period1_to: str,
        period2_from: str, period2_to: str,
    ) -> dict:
        """Compare sales KPIs between two date ranges.

        Returns:
            Dict with period1, period2 data and revenue/order change percentages.
        """
        p1 = sales.analyze_sales(self.client, date_from=period1_from, date_to=period1_to)
        p2 = sales.analyze_sales(self.client, date_from=period2_from, date_to=period2_to)
        if p1["total_revenue"] > 0:
            rev_change = round((p2["total_revenue"] - p1["total_revenue"]) / p1["total_revenue"] * 100, 1)
        else:
            rev_change = None
        if p1["total_orders"] > 0:
            order_change = round((p2["total_orders"] - p1["total_orders"]) / p1["total_orders"] * 100, 1)
        else:
            order_change = None
        return {
            "period1": p1,
            "period2": p2,
            "revenue_change_pct": rev_change,
            "order_change_pct": order_change,
        }


class FinancialAnalytics:
    """Financial dashboard aggregator."""

    def __init__(self, client: OdooClient):
        self.client = client

    def dashboard(self) -> dict:
        """Return combined financial ratios, cashflow, and aging report."""
        return {
            "ratios": accounting.analyze_financial_ratios(self.client),
            "cashflow": accounting.get_cashflow_summary(self.client),
            "aging": accounting.get_aging_report(self.client),
        }

    def profit_loss(self, date_from: str, date_to: str) -> dict:
        """Return revenue, expenses, and net profit for a date range."""
        cf = accounting.get_cashflow_summary(self.client, date_from=date_from, date_to=date_to)
        return {
            "revenue": cf["total_income"],
            "expenses": cf["total_expense"],
            "net_profit": cf["net_cashflow"],
        }


class InventoryAnalytics:
    """Inventory dashboard aggregator."""

    def __init__(self, client: OdooClient):
        self.client = client

    def dashboard(self) -> dict:
        """Return combined inventory turnover, valuation, and low-stock alerts."""
        return {
            "turnover": inventory.analyze_inventory_turnover(self.client),
            "valuation": inventory.get_stock_valuation(self.client),
            "low_stock": inventory.get_low_stock(self.client),
        }

    def abc_analysis(self) -> dict:
        """Classify products into A/B/C tiers by cumulative valuation (80/95/100%)."""
        val_data = inventory.get_stock_valuation(self.client)
        products = val_data.get("products", [])
        total = val_data.get("total_valuation", 0)
        if not products or total <= 0:
            return {"A": [], "B": [], "C": []}
        ranked = sorted(products, key=lambda p: p.get("valuation", 0), reverse=True)
        result: dict[str, list] = {"A": [], "B": [], "C": []}
        cumulative = 0.0
        for p in ranked:
            cumulative += p.get("valuation", 0)
            pct = cumulative / total
            if pct <= 0.80:
                result["A"].append(p)
            elif pct <= 0.95:
                result["B"].append(p)
            else:
                result["C"].append(p)
        # Ensure the first item that crosses 80% is still in A
        if not result["A"] and ranked:
            result["A"].append(result["B"].pop(0) if result["B"] else result["C"].pop(0))
        return result


class HRAnalytics:
    """HR dashboard aggregator."""

    def __init__(self, client: OdooClient):
        self.client = client

    def dashboard(self) -> dict:
        """Return combined headcount, attendance, and leave data."""
        headcount = hr.get_headcount_summary(self.client)
        attendance_records = hr.get_attendance(self.client)
        leave_records = hr.get_leaves(self.client)
        return {
            "headcount": headcount,
            "attendance_today": {
                "total_records": len(attendance_records),
                "records": attendance_records,
            },
            "leaves": {
                "total_leaves": len(leave_records),
                "records": leave_records,
            },
        }

    def department_costs(
        self, date_from: Optional[str] = None, date_to: Optional[str] = None,
    ) -> list[dict]:
        """Sum expense costs per department.

        Uses batched queries to avoid N+1: fetches all employees and
        all expenses in two queries, then groups in Python.

        Returns:
            List of dicts with department_id, department, employee_count, total_expenses.
        """
        departments = hr.get_departments(self.client)
        if not departments:
            return []

        dept_ids = [d["id"] for d in departments]

        # Batch: fetch all employees in the relevant departments at once
        all_employees = self.client.search_read(
            "hr.employee",
            domain=[["department_id", "in", dept_ids]],
            fields=["id", "department_id"],
        )

        # Group employees by department and collect all employee IDs
        emp_by_dept: dict[int, list[int]] = defaultdict(list)
        all_emp_ids: list[int] = []
        for emp in all_employees:
            dept_ref = emp.get("department_id")
            if isinstance(dept_ref, (list, tuple)) and len(dept_ref) > 0:
                did = dept_ref[0]
            else:
                did = dept_ref
            emp_by_dept[did].append(emp["id"])
            all_emp_ids.append(emp["id"])

        # Batch: fetch all expenses for all employees at once
        expenses_by_emp: dict[int, float] = defaultdict(float)
        if all_emp_ids:
            expense_domain: list = [["employee_id", "in", all_emp_ids]]
            if date_from:
                expense_domain.append(["date", ">=", date_from])
            if date_to:
                expense_domain.append(["date", "<=", date_to])
            all_expenses = self.client.search_read(
                "hr.expense",
                domain=expense_domain,
                fields=["employee_id", "total_amount_currency"],
            )
            for exp in all_expenses:
                eid_ref = exp.get("employee_id")
                if isinstance(eid_ref, (list, tuple)) and len(eid_ref) > 0:
                    eid = eid_ref[0]
                else:
                    eid = eid_ref
                expenses_by_emp[eid] += exp.get("total_amount_currency", 0)

        result = []
        for dept in departments:
            dept_id = dept["id"]
            dept_emp_ids = emp_by_dept.get(dept_id, [])
            total = sum(expenses_by_emp.get(eid, 0.0) for eid in dept_emp_ids)
            result.append({
                "department_id": dept_id,
                "department": dept["name"],
                "employee_count": len(dept_emp_ids),
                "total_expenses": total,
            })
        return result


class PipelineAnalytics:
    """CRM pipeline dashboard aggregator."""

    def __init__(self, client: OdooClient):
        self.client = client

    def dashboard(self) -> dict:
        """Return combined pipeline analysis and forecast."""
        return {
            "pipeline": crm.analyze_pipeline(self.client),
            "forecast": crm.get_forecast(self.client),
        }

    def conversion_funnel(self) -> list[dict]:
        """Calculate stage-by-stage conversion rates through the pipeline.

        Returns:
            List of dicts with stage, count, and conversion_pct.
        """
        pipeline = crm.get_pipeline(self.client)
        if not pipeline:
            return []
        funnel = []
        prev_count = None
        for stage_data in pipeline:
            count = len(stage_data["opportunities"])
            if prev_count is not None and prev_count > 0:
                conv_pct = round(count / prev_count * 100, 1)
            else:
                conv_pct = 100.0 if prev_count is None else None
            funnel.append({
                "stage": stage_data["stage"],
                "count": count,
                "conversion_pct": conv_pct,
            })
            prev_count = count
        return funnel


def full_business_dashboard(client: OdooClient) -> dict:
    """Aggregate all department dashboards into a single business overview."""
    return {
        "sales": SalesAnalytics(client).dashboard(),
        "financial": FinancialAnalytics(client).dashboard(),
        "inventory": InventoryAnalytics(client).dashboard(),
        "hr": HRAnalytics(client).dashboard(),
        "pipeline": PipelineAnalytics(client).dashboard(),
    }
