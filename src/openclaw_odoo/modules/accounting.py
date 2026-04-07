"""Accounting module -- invoicing, payments, financial analysis."""
from datetime import date, timedelta
from typing import Optional

from ..client import OdooClient
from ..errors import OdooRecordNotFoundError


def create_invoice(
    client: OdooClient,
    partner_id: int,
    lines: list[dict],
    move_type: str = "out_invoice",
    **extra,
) -> dict:
    """Create an invoice (or credit note) and return {id, web_url}."""
    invoice_lines = []
    for line in lines:
        vals = {
            "quantity": line.get("quantity", 1),
            "price_unit": line.get("price_unit", 0),
        }
        if "product_id" in line:
            vals["product_id"] = line["product_id"]
        if "name" in line:
            vals["name"] = line["name"]
        if "account_id" in line:
            vals["account_id"] = line["account_id"]
        invoice_lines.append((0, 0, vals))

    values = {
        "move_type": move_type,
        "partner_id": partner_id,
        "invoice_line_ids": invoice_lines,
        **extra,
    }
    record_id = client.create("account.move", values)
    return {"id": record_id, "web_url": client.web_url("account.move", record_id)}


def create_bill(
    client: OdooClient, partner_id: int, lines: list[dict], **extra
) -> dict:
    """Create a vendor bill (in_invoice)."""
    return create_invoice(client, partner_id, lines, move_type="in_invoice", **extra)


def post_invoice(client: OdooClient, invoice_id: int) -> dict:
    """Confirm/post an invoice."""
    client.execute("account.move", "action_post", [invoice_id])
    return {"success": True, "invoice_id": invoice_id}


def send_invoice_email(client: OdooClient, invoice_id: int) -> dict:
    """Send invoice by email using Odoo's mail wizard."""
    wizard_action = client.execute("account.move", "action_invoice_sent", [invoice_id])
    ctx = wizard_action.get("context", {})
    wizard_vals = {
        "composition_mode": ctx.get("default_composition_mode", "comment"),
        "model": ctx.get("default_model", "account.move"),
        "res_ids": ctx.get("default_res_ids", [invoice_id]),
        "template_id": ctx.get("default_template_id"),
        "email_layout_xmlid": ctx.get("default_email_layout_xmlid", ""),
    }
    wizard_id = client.execute("mail.compose.message", "create", wizard_vals)
    client.execute("mail.compose.message", "action_send_mail", [wizard_id])
    return {"success": True, "invoice_id": invoice_id, "message": "Invoice email sent"}


def register_payment(
    client: OdooClient,
    invoice_id: int,
    amount: Optional[float] = None,
    journal_id: Optional[int] = None,
) -> dict:
    """Register a payment against an invoice using Odoo's payment register wizard.

    This uses the ``account.payment.register`` wizard which automatically
    reconciles the payment with the invoice.
    """
    invoices = client.search_read(
        "account.move",
        domain=[["id", "=", invoice_id]],
        fields=["amount_residual", "state"],
    )
    if not invoices:
        raise OdooRecordNotFoundError(f"Invoice {invoice_id} not found", model="account.move")

    wizard_vals = {}
    if amount is not None:
        wizard_vals["amount"] = amount
    if journal_id:
        wizard_vals["journal_id"] = journal_id

    ctx = {"active_model": "account.move", "active_ids": [invoice_id]}
    wizard_id = client.execute(
        "account.payment.register", "create", wizard_vals, context=ctx,
    )
    result = client.execute(
        "account.payment.register", "action_create_payments",
        [wizard_id], context=ctx,
    )
    return {"success": True, "invoice_id": invoice_id, "wizard_result": result}


def get_unpaid_invoices(
    client: OdooClient, move_type: str = "out_invoice"
) -> list[dict]:
    """Return invoices that are not fully paid."""
    domain = [
        ["move_type", "=", move_type],
        ["payment_state", "in", ("not_paid", "partial")],
        ["state", "=", "posted"],
    ]
    return client.search_read(
        "account.move",
        domain=domain,
        fields=[
            "name", "partner_id", "invoice_date", "invoice_date_due",
            "amount_total", "amount_residual", "payment_state",
        ],
    )


def get_overdue_invoices(client: OdooClient) -> list[dict]:
    """Return unpaid invoices past their due date."""
    today_str = date.today().isoformat()
    domain = [
        ["move_type", "in", ("out_invoice", "in_invoice")],
        ["payment_state", "in", ("not_paid", "partial")],
        ["state", "=", "posted"],
        ["invoice_date_due", "<", today_str],
    ]
    return client.search_read(
        "account.move",
        domain=domain,
        fields=[
            "name", "partner_id", "invoice_date", "invoice_date_due",
            "amount_total", "amount_residual", "move_type",
        ],
    )


def analyze_financial_ratios(client: OdooClient) -> dict:
    """Compute key financial ratios from account balances.

    Uses a single search_read call to fetch all accounts whose type is
    in the union of needed types, then partitions by type in Python.
    """
    all_needed_types = [
        "asset_current", "asset_cash", "asset_receivable",
        "liability_current", "liability_payable",
        "income", "income_other",
    ]
    all_accounts = client.search_read(
        "account.account",
        domain=[["account_type", "in", all_needed_types]],
        fields=["account_type", "current_balance"],
    )

    # Partition balances by account type
    balance_by_type: dict[str, float] = {}
    for acc in all_accounts:
        atype = acc.get("account_type", "")
        balance_by_type.setdefault(atype, 0.0)
        balance_by_type[atype] += acc.get("current_balance", 0)

    def _sum_types(types: list[str]) -> float:
        return sum(balance_by_type.get(t, 0.0) for t in types)

    current_assets = abs(_sum_types([
        "asset_current", "asset_cash", "asset_receivable",
    ]))
    current_liabilities = abs(_sum_types([
        "liability_current", "liability_payable",
    ]))
    receivables = abs(_sum_types(["asset_receivable"]))
    payables = abs(_sum_types(["liability_payable"]))
    revenue = abs(_sum_types(["income", "income_other"]))

    # Quick ratio = (current_assets - inventory_value) / current_liabilities
    # Since Odoo doesn't have a dedicated inventory account type,
    # approximate as: current_assets minus non-liquid assets
    inventory_value = abs(_sum_types(["asset_current"])) - abs(_sum_types(["asset_cash", "asset_receivable"]))
    if inventory_value < 0:
        inventory_value = 0
    quick_assets = current_assets - inventory_value

    current_ratio = (current_assets / current_liabilities) if current_liabilities else 0
    quick_ratio = (quick_assets / current_liabilities) if current_liabilities else 0
    ar_turnover = (revenue / receivables) if receivables else 0
    ap_turnover = (revenue / payables) if payables else 0

    return {
        "current_ratio": round(current_ratio, 2),
        "quick_ratio": round(quick_ratio, 2),
        "ar_turnover": round(ar_turnover, 2),
        "ap_turnover": round(ap_turnover, 2),
    }


def get_cashflow_summary(
    client: OdooClient,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """Summarize cash flow: income, expense, net."""
    domain: list = [["parent_state", "=", "posted"]]
    if date_from:
        domain.append(["date", ">=", date_from])
    if date_to:
        domain.append(["date", "<=", date_to])

    income_domain = domain + [
        ["account_id.account_type", "in", ("income", "income_other")]
    ]
    expense_domain = domain + [
        ["account_id.account_type", "in", ("expense", "expense_depreciation")]
    ]

    income_lines = client.search_read(
        "account.move.line", domain=income_domain, fields=["balance"]
    )
    expense_lines = client.search_read(
        "account.move.line", domain=expense_domain, fields=["balance"]
    )

    total_income = abs(sum(l.get("balance", 0) for l in income_lines))
    total_expense = abs(sum(l.get("balance", 0) for l in expense_lines))

    return {
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "net_cashflow": round(total_income - total_expense, 2),
    }


def get_revenue_vs_expense(client: OdooClient, months: int = 6) -> list[dict]:
    """Monthly revenue vs expense breakdown.

    Uses just 2 search_read calls (one for income, one for expense) for the
    entire date range, then buckets by month in Python.
    """
    today = date.today()

    # Build month boundaries
    month_boundaries: list[tuple[date, date, str]] = []
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_start = date(y, m, 1)
        if m == 12:
            month_end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(y, m + 1, 1) - timedelta(days=1)
        month_boundaries.append((month_start, month_end, month_start.strftime("%Y-%m")))

    range_start = month_boundaries[0][0]
    range_end = month_boundaries[-1][1]

    base_domain: list = [
        ["parent_state", "=", "posted"],
        ["date", ">=", range_start.isoformat()],
        ["date", "<=", range_end.isoformat()],
    ]

    # 2 RPCs total: one for income, one for expense
    income_lines = client.search_read(
        "account.move.line",
        domain=base_domain + [
            ["account_id.account_type", "in", ("income", "income_other")]
        ],
        fields=["balance", "date"],
    )
    expense_lines = client.search_read(
        "account.move.line",
        domain=base_domain + [
            ["account_id.account_type", "in", ("expense", "expense_depreciation")]
        ],
        fields=["balance", "date"],
    )

    # Bucket by month label
    month_labels = {label for _, _, label in month_boundaries}
    income_by_month: dict[str, float] = {label: 0.0 for label in month_labels}
    expense_by_month: dict[str, float] = {label: 0.0 for label in month_labels}

    for line in income_lines:
        raw_date = line.get("date", "")
        if not raw_date:
            continue
        month_key = str(raw_date)[:7]
        if month_key in income_by_month:
            income_by_month[month_key] += abs(line.get("balance", 0))

    for line in expense_lines:
        raw_date = line.get("date", "")
        if not raw_date:
            continue
        month_key = str(raw_date)[:7]
        if month_key in expense_by_month:
            expense_by_month[month_key] += abs(line.get("balance", 0))

    result = []
    for _, _, label in month_boundaries:
        revenue = income_by_month[label]
        expense = expense_by_month[label]
        result.append({
            "month": label,
            "revenue": round(revenue, 2),
            "expense": round(expense, 2),
            "profit": round(revenue - expense, 2),
        })

    return result


def get_aging_report(
    client: OdooClient, move_type: str = "out_invoice"
) -> dict:
    """Aging report: group unpaid invoices into 0-30, 31-60, 61-90, 90+ day buckets."""
    domain = [
        ["move_type", "=", move_type],
        ["payment_state", "in", ("not_paid", "partial")],
        ["state", "=", "posted"],
    ]
    invoices = client.search_read(
        "account.move",
        domain=domain,
        fields=["invoice_date_due", "amount_residual"],
    )

    buckets = {
        "0-30": {"count": 0, "amount": 0.0},
        "31-60": {"count": 0, "amount": 0.0},
        "61-90": {"count": 0, "amount": 0.0},
        "90+": {"count": 0, "amount": 0.0},
    }
    today = date.today()

    for inv in invoices:
        due = inv.get("invoice_date_due")
        if not due:
            continue
        if isinstance(due, str):
            due = date.fromisoformat(due)
        days = (today - due).days
        if days < 0:
            days = 0

        amt = inv.get("amount_residual", 0)
        if days <= 30:
            buckets["0-30"]["count"] += 1
            buckets["0-30"]["amount"] += amt
        elif days <= 60:
            buckets["31-60"]["count"] += 1
            buckets["31-60"]["amount"] += amt
        elif days <= 90:
            buckets["61-90"]["count"] += 1
            buckets["61-90"]["amount"] += amt
        else:
            buckets["90+"]["count"] += 1
            buckets["90+"]["amount"] += amt

    return buckets
