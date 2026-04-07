---
name: openclaw-odoo
version: 1.0.0
description: "AI-powered Odoo 19 connector for OpenClaw, MCP, and CLI"
tools:
  - name: openclaw-odoo
    description: "Execute openclaw-odoo operations on Odoo 19 ERP"
    command: "python3 -m openclaw_odoo.interfaces.openclaw_skill"
    input: stdin
    output: stdout
---

# OpenClaw-Odoo Skill

openclaw-odoo is a comprehensive Odoo 19 ERP connector that provides full business operations through a single JSON interface. Send a JSON object to stdin with `action` and `params`, and receive structured JSON results on stdout.

## Input Format

```json
{"action": "action_name", "params": {"key": "value"}}
```

## Output Format

All responses are JSON. Successful results return the operation data directly. Errors return:

```json
{"error": true, "message": "description", "action": "action_name"}
```

## Supported Actions

### Partners
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_partner` | `name` | Create a contact or company |
| `find_partner` | `query` | Fuzzy search by name/email/phone |
| `get_partner` | `partner_id` | Get partner details with smart fields |
| `update_partner` | `partner_id` + fields | Update partner fields |
| `delete_partner` | `partner_id` | Archive a partner |
| `get_partner_summary` | `partner_id` | Partner with order/invoice counts + revenue |
| `get_top_customers` | | Top customers by revenue |

### Sales
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_quotation` | `partner_id`, `lines` | Create a sales quotation |
| `confirm_order` | `order_id` | Confirm quotation into sales order |
| `cancel_order` | `order_id` | Cancel a sales order |
| `get_order` | `order_id` | Get order with lines |
| `search_orders` | | Search orders with optional domain/limit |
| `analyze_sales` | | Sales summary: revenue, orders, top products |
| `get_sales_trend` | | Monthly revenue trend (6 months) |

### CRM
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_lead` | `name` | Create a CRM lead |
| `create_opportunity` | `name`, `partner_id` | Create an opportunity |
| `get_pipeline` | | Full pipeline grouped by stage |
| `move_stage` | `lead_id`, `stage_id` | Move lead/opportunity to a stage |
| `mark_won` | `lead_id` | Mark opportunity as won |
| `mark_lost` | `lead_id` | Mark opportunity as lost |
| `analyze_pipeline` | | Pipeline KPIs: win rate, stage counts |
| `get_forecast` | | Weighted revenue forecast |

### Inventory
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_product` | `name` | Create a product |
| `search_products` | `query` | Search products by name |
| `check_availability` | `product_id` | Check stock qty and reserved |
| `get_stock_levels` | | All product stock levels |
| `get_low_stock` | | Products below threshold |
| `get_stock_valuation` | | Total stock valuation |

### Accounting
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_invoice` | `partner_id`, `lines` | Create customer invoice |
| `post_invoice` | `invoice_id` | Post/confirm an invoice |
| `register_payment` | `invoice_id` | Register payment against invoice |
| `get_unpaid_invoices` | | Unpaid posted invoices |
| `get_overdue_invoices` | | Overdue invoices past due date |
| `analyze_financial_ratios` | | Current, quick, AR/AP ratios |
| `get_aging_report` | | Receivables aging 0-30/31-60/61-90/90+ |

### Purchase
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_purchase_order` | `partner_id`, `lines` | Create purchase order |
| `confirm_purchase` | `order_id` | Confirm purchase order |
| `cancel_purchase` | `order_id` | Cancel purchase order |
| `get_purchase` | `order_id` | Get purchase order with lines |
| `search_purchases` | | Search purchase orders |
| `get_purchase_summary` | | Purchase analytics |

### HR
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_employee` | `name` | Create employee record |
| `checkin` | `employee_id` | Clock in attendance |
| `checkout` | `employee_id` | Clock out attendance |
| `get_attendance` | | Attendance records with optional filters |
| `request_leave` | `employee_id`, `leave_type_id`, `date_from`, `date_to` | Request time off |
| `get_leaves` | | Leave requests with optional filters |
| `get_headcount_summary` | | Headcount by department |

### Projects
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_project` | `name` | Create a project |
| `create_task` | `project_id`, `name` | Create a task in a project |
| `update_task` | `task_id` + fields | Update task fields |
| `search_tasks` | | Search tasks with filters |
| `log_timesheet` | `task_id`, `hours`, `description` | Log timesheet entry |
| `get_project_summary` | `project_id` | Tasks by stage, hours, team |
| `create_ticket` | `name` | Create helpdesk ticket |

### Calendar
| Action | Required Params | Description |
|--------|----------------|-------------|
| `create_event` | `name`, `start`, `stop` | Create calendar event |
| `get_event` | `event_id` | Get event details |
| `search_events` | | Search events |
| `update_event` | `event_id` + fields | Update event |
| `delete_event` | `event_id` | Archive event |
| `get_today_events` | | Today's schedule |
| `get_upcoming_events` | | Next N days |

### Smart Actions (Fuzzy Matching)
| Action | Required Params | Description |
|--------|----------------|-------------|
| `smart_create_quotation` | `partner` (name), `lines` | Find-or-create partner + products, then create quotation |
| `smart_create_invoice` | `partner` (name), `lines` | Find-or-create partner, then create invoice |
| `smart_create_lead` | `name` | Create lead with optional partner resolution |
| `smart_create_task` | `project` (name), `name` | Find-or-create project, then create task |
| `smart_create_purchase` | `partner` (name), `lines` | Find-or-create vendor + products, then create PO |
| `smart_create_employee` | `name` | Create employee with department resolution |

### Analytics Dashboards
| Action | Description |
|--------|-------------|
| `sales_dashboard` | Sales summary + trend + top products |
| `financial_dashboard` | Ratios + cashflow + aging |
| `inventory_dashboard` | Turnover + valuation + low stock |
| `hr_dashboard` | Headcount + attendance + leaves |
| `pipeline_dashboard` | Pipeline analysis + forecast |
| `full_dashboard` | All five dashboards combined |

### Import/Export
| Action | Required Params | Description |
|--------|----------------|-------------|
| `import_csv` | `filepath` | Import CSV with auto-detect model |
| `import_excel` | `filepath` | Import Excel with auto-detect model |
| `export_records` | `model` | Export records to CSV/Excel |

### Generic CRUD
| Action | Required Params | Description |
|--------|----------------|-------------|
| `search` | `model` | Search any Odoo model |
| `create` | `model`, `values` | Create any record |
| `update` | `model`, `record_id`, `values` | Update any record |
| `delete` | `model`, `record_id` | Archive any record |
| `execute` | `model`, `method` | Call any Odoo method |
| `fields` | `model` | Get field definitions |
| `batch` | `operations` | Execute multiple operations |
