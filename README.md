# openclaw-odoo

> Manage your Odoo 19 business system using plain English -- from Telegram, AI assistants, or your terminal.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Odoo 19](https://img.shields.io/badge/odoo-19-purple)
![Tests: 809](https://img.shields.io/badge/tests-809-brightgreen)
![Coverage: 93%](https://img.shields.io/badge/coverage-93%25-brightgreen)

openclaw-odoo connects to your Odoo 19 system and lets you do things like:

- "Create a quotation for Acme Corp with 10 keyboards at $45 each"
- "Show me all overdue invoices"
- "Who are my top 5 customers?"
- "What meetings do I have this week?"
- "Show me fleet vehicle costs by status" *(works with custom modules too!)*

No menus, no clicking around, no memorizing IDs. Just type what you want in plain English.

It works with **any Odoo 19 instance** (Community, Enterprise, Odoo.sh, or self-hosted) and you do **not** need to install anything extra on your Odoo server.

**Dynamic Model Registry** -- auto-discovers ALL your Odoo models (including custom ones) and generates smart CRUD, workflow actions, and analytics dashboards for every model automatically. No code changes needed when you add custom modules.

---

## Quick Start (5 minutes)

**What you need before starting:**

- **Python 3.10 or newer** -- [Download Python](https://www.python.org/downloads/) if you don't have it. Check with `python3 --version`.
- **A running Odoo 19 instance** -- You need the server address, database name, username, and password. If you don't have Odoo, see [odoo.com](https://www.odoo.com/) to get started.

**Step 1: Install**

Open your terminal and run:

```bash
pip install git+https://github.com/parth-unjiya/openclaw-odoo.git
```

**Step 2: Configure**

Create a configuration file at `~/.config/openclaw-odoo/config.json` with your Odoo connection details:

```json
{
  "odoo": {
    "url": "http://your-odoo-server:8069",
    "db": "your_database_name",
    "user": "your_username",
    "password": "your_password"
  }
}
```

Replace the values with your actual Odoo server address, database name, login, and password.

**Step 3: Test it**

```bash
openclaw-odoo search res.partner --fields name,email --limit 5
```

If you see a list of contacts from your Odoo, you're all set!

---

## How to Use It

There are three ways to use openclaw-odoo, depending on your setup.

### Option A: With OpenClaw (Telegram / WhatsApp)

If you use [OpenClaw](https://openclaw.dev) to chat with AI agents via Telegram or WhatsApp, you can add openclaw-odoo as a skill so your bot can talk to Odoo.

1. Install (see Quick Start above)
2. Set up the config file (see Quick Start above)
3. Copy `SKILL.md` from this repository into your OpenClaw workspace directory
4. Send messages to your Telegram bot:
   - "Show me today's sales"
   - "Create a quotation for Acme Corp with 10 keyboards at $45 each"
   - "How much inventory do we have of Widget Pro?"

### Option B: With AI Assistants (Claude Desktop, ChatGPT, Cursor)

openclaw-odoo includes an MCP server. MCP (Model Context Protocol) is a standard that lets AI assistants connect to external tools. If your AI app supports MCP, it can talk to your Odoo through openclaw-odoo.

**Setting up with Claude Desktop:**

1. Install (see Quick Start above)
2. Open your Claude Desktop config file:
   - **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux:** `~/.config/claude/claude_desktop_config.json`
3. Add this block (replace the Odoo details with yours):

```json
{
  "mcpServers": {
    "openclaw-odoo": {
      "command": "python3",
      "args": ["-m", "openclaw_odoo.interfaces.mcp_server"],
      "env": {
        "ODOO_URL": "http://your-odoo-server:8069",
        "ODOO_DB": "your_database_name",
        "ODOO_USER": "your_username",
        "ODOO_PASSWORD": "your_password"
      }
    }
  }
}
```

4. Restart Claude Desktop. Now you can ask things like:
   - "Search for all unpaid invoices"
   - "Create a new lead for TechStart Inc with expected revenue $50,000"
   - "Show me the sales dashboard"

**Available MCP tools:**

| Tool | What it does |
|------|-------------|
| `search_records` | Search any Odoo data with filters |
| `create_record` | Create a new record |
| `update_record` | Update an existing record |
| `delete_record` | Delete a record |
| `execute_method` | Run any action on any Odoo model |
| `batch_execute` | Run multiple operations at once |
| `smart_action` | Use names instead of IDs (finds or creates automatically) |
| `analyze` | View analytics dashboards |
| `import_file` | Import data from CSV or Excel |
| `export_data` | Export records to CSV or Excel |
| `list_models` | See what Odoo models are available |
| `get_fields` | See what fields a model has |

### Option C: Command Line (Terminal)

Use openclaw-odoo directly from your terminal for quick lookups and operations.

```bash
# List your contacts
openclaw-odoo search res.partner --fields name,email --limit 5

# Create a product
openclaw-odoo create product.product --values '{"name": "Widget Pro", "list_price": 49.99}'

# View sales analytics
openclaw-odoo analytics sales

# See the full business dashboard
openclaw-odoo analytics full

# Discover all models (including custom ones)
openclaw-odoo discover --refresh

# List all discovered models
openclaw-odoo discover --list

# See details of a specific model
openclaw-odoo discover --model sale.order

# Tip: pipe output to jq for nice formatting
openclaw-odoo search res.partner --limit 3 | jq '.[].name'
```

---

## What Can You Do With It?

| Area | Examples |
|------|---------|
| **Contacts** | Create, search, and update customers and companies. See top customers by revenue. |
| **Sales** | Create quotations, confirm orders, track revenue trends. |
| **Purchasing** | Create purchase orders, confirm them, track vendor spending. |
| **CRM** | Manage leads and opportunities, view your sales pipeline, forecast revenue. |
| **Inventory** | Check stock levels, find low-stock products, see stock valuation. |
| **Accounting** | Create invoices, register payments, view aging reports. |
| **HR** | Manage employees, clock in/out, request leave, track expenses. |
| **Projects** | Create projects and tasks, log timesheets, manage helpdesk tickets. |
| **Calendar** | Create events, check today's schedule, view upcoming meetings. |
| **Custom Modules** | **Auto-discovers any custom model** -- search, create, update, delete, workflow actions, and analytics work automatically for any installed Odoo module. |

---

## Dynamic Model Registry (NEW)

openclaw-odoo can auto-discover **every model** in your Odoo instance -- including custom modules you've built or installed from the Odoo App Store. No code changes needed.

**How it works:**

1. Run `openclaw-odoo discover --refresh` (one-time, takes ~5-15 seconds)
2. The tool scans your Odoo: models, fields, workflows, access rights
3. For every discovered model, it automatically generates:
   - **Smart CRUD** -- search, create, get, update, delete, find, find-or-create
   - **Workflow actions** -- confirm, cancel, approve, etc. (from discovered buttons)
   - **Analytics dashboard** -- totals, group-by-status, trends (for models with money/date fields)

**Example:** You install a custom "Fleet Management" module. Without any configuration:

```
User: "Search fleet vehicles"
→ Auto-generated search_fleet_vehicles action → returns results

User: "Show fleet costs by status"
→ Auto-generated dashboard → totals, grouped by status field
```

**Optional hints:** For even smarter behavior, add `model_hints` to your config:

```json
{
  "odoo": { "url": "...", "db": "...", "user": "...", "password": "..." },
  "model_hints": {
    "x_fleet.vehicle": {
      "label": "Fleet Vehicle",
      "name_field": "license_plate",
      "aliases": ["vehicle", "car", "fleet"],
      "money_fields": ["fuel_cost", "maintenance_cost"],
      "analytics": {
        "group_by": "x_status",
        "sum_fields": ["fuel_cost", "maintenance_cost"]
      }
    }
  }
}
```

Now "show me fleet costs" works because the tool knows "fleet" = `x_fleet.vehicle`.

---

## Smart Actions

You don't need to know Odoo record IDs. Just use names and openclaw-odoo figures out the rest.

For example, say "Create a quotation for Acme Corp with 20 cables at $12 each" -- openclaw-odoo will:

1. Search for "Acme Corp" in your contacts
2. If not found, create the contact automatically
3. Search for "cables" in your products
4. If not found, create the product automatically
5. Build the quotation with everything linked correctly

**Smart actions available:**

| Action | What it does |
|--------|-------------|
| Create quotation | Finds (or creates) customer and products by name |
| Create invoice | Finds (or creates) customer by name |
| Create purchase order | Finds (or creates) vendor and products by name |
| Create lead | Optionally links to a customer by name |
| Create task | Finds project and assignee by name |
| Create employee | Finds department by name |

---

## Analytics Dashboards

Get instant business insights by asking for a dashboard or running a CLI command:

| Dashboard | What you see |
|-----------|-------------|
| **Sales** | Revenue summary, monthly trends, top-selling products |
| **Financial** | Key ratios, cashflow summary, receivables aging (0-30, 31-60, 61-90, 90+ days) |
| **Inventory** | Turnover, stock valuation, low-stock alerts |
| **HR** | Headcount by department, attendance, leave requests |
| **Pipeline** | Win rate, stage distribution, revenue forecast |

Run `openclaw-odoo analytics full` to see everything at once.

---

## Configuration Reference

openclaw-odoo looks for settings in this order (each level overrides the previous):

1. Default values
2. Config file
3. Environment variables (highest priority)

### Config File Locations

The config file is searched in this order:

1. Path set in `$OPENCLAW_ODOO_CONFIG` environment variable
2. `~/.config/openclaw-odoo/config.json`
3. `./openclaw-odoo.json` (in your current folder)

### Full Config File Format

```json
{
  "odoo": {
    "url": "http://localhost:8069",
    "db": "your_database_name",
    "user": "your_username",
    "password": "your_password"
  },
  "limits": {
    "default": 50,
    "max": 500
  },
  "readonly": false,
  "alerts": {
    "enabled": false,
    "poll_interval": 60
  },
  "model_hints": {}
}
```

- **readonly** -- Set to `true` if you want to prevent any changes to your Odoo data (search-only mode).
- **limits** -- Controls how many records are returned per query. Default is 50, maximum is 500.
- **alerts** -- When enabled, polls Odoo for changes and can notify you (e.g., via Telegram) when records are created or updated.
- **model_hints** -- Optional hints for custom models to improve auto-generated actions and analytics. See [Dynamic Model Registry](#dynamic-model-registry-new) above.

### Environment Variables

You can also configure everything using environment variables (useful for servers or containers):

| Variable | What it does | Default |
|----------|-------------|---------|
| `ODOO_URL` | Your Odoo server address | `http://localhost:8069` |
| `ODOO_DB` | Database name | *(required)* |
| `ODOO_USER` | Login username | *(required)* |
| `ODOO_PASSWORD` | Login password | *(required)* |
| `OPENCLAW_ODOO_READONLY` | Block all write operations | `false` |
| `OPENCLAW_ODOO_DEFAULT_LIMIT` | Records per query | `50` |
| `OPENCLAW_ODOO_MAX_LIMIT` | Maximum records per query | `500` |
| `OPENCLAW_ODOO_CONFIG` | Path to config file | *(auto-detected)* |

---

## Using as a Python Library

If you write Python scripts, you can use openclaw-odoo directly in your code:

```python
from openclaw_odoo.config import load_config
from openclaw_odoo.client import OdooClient

config = load_config()
client = OdooClient(config)

# Search for companies
partners = client.search_read(
    "res.partner",
    domain=[["is_company", "=", True]],
    fields=["name", "email"],
    limit=10,
)

# Create a contact
partner_id = client.create("res.partner", {
    "name": "Acme Corp",
    "email": "info@acme.com",
    "is_company": True,
})

# Smart actions -- use names, not IDs
from openclaw_odoo.intelligence.smart_actions import SmartActionHandler
smart = SmartActionHandler(client)
order = smart.smart_create_quotation(
    partner="Acme Corp",
    lines=[{"product": "Widget Pro", "quantity": 20, "price_unit": 45.00}],
)

# Analytics
from openclaw_odoo.intelligence.analytics import full_business_dashboard
dashboard = full_business_dashboard(client)
```

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and guidelines.

```bash
git clone https://github.com/parth-unjiya/openclaw-odoo.git
cd openclaw-odoo
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

---

## License

MIT -- see [LICENSE](LICENSE) for details.
