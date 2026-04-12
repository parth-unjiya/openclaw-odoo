# CLAUDE.md — openclaw-odoo

## Project Overview

**openclaw-odoo** is an AI-powered Odoo 19 ERP connector that provides a natural language interface to Odoo business operations via three channels: CLI, MCP server (for AI assistants like Claude Desktop), and OpenClaw skill (Telegram/WhatsApp). It communicates with Odoo via dual-protocol transport (JSON-2 for Odoo 19+, JSON-RPC fallback) — no server-side modules required.

- **Version:** 1.0.0
- **License:** MIT
- **Python:** 3.10+
- **Odoo:** 19 (Community, Enterprise, Odoo.sh, self-hosted)
- **Single dependency:** `requests` (core); optional `fastmcp` for MCP, `openpyxl` for Excel

---

## Architecture

```
src/openclaw_odoo/
├── __init__.py              # Package init, __version__
├── client.py                # OdooClient — Dual-protocol transport (JSON-2 for Odoo 19+, JSON-RPC fallback)
├── config.py                # OdooClawConfig dataclass — env vars > config file > defaults
├── errors.py                # Exception hierarchy with error classification
├── retry.py                 # Exponential backoff retry decorator (jitter, max_delay)
├── fields.py                # Smart field selection (importance scoring, excludes binary/o2m)
├── batch.py                 # Sequential batch execution with fail-fast support
├── modules/                 # 9 business domain modules
│   ├── partners.py          # res.partner — CRUD, fuzzy search, top customers, revenue summary
│   ├── sales.py             # sale.order — quotations, confirm/cancel, analytics, trends
│   ├── crm.py               # crm.lead — leads, opportunities, pipeline, forecast
│   ├── inventory.py         # product.product + stock.quant — stock levels, turnover, valuation
│   ├── accounting.py        # account.move — invoicing, payments, aging, financial ratios
│   ├── hr.py                # hr.employee — attendance, leave, expenses, headcount
│   ├── projects.py          # project.task — tasks, timesheets, helpdesk tickets
│   ├── purchase.py          # purchase.order — PO creation, confirmation, vendor analytics
│   └── calendar_mod.py      # calendar.event — events, today/upcoming queries
├── intelligence/            # Cross-cutting smart features
│   ├── smart_actions.py     # SmartActionHandler — fuzzy find_or_create, name-based resolution
│   ├── analytics.py         # Dashboard aggregators (Sales, Financial, Inventory, HR, Pipeline)
│   ├── error_recovery.py    # ErrorRecovery — 6 auto-fix strategies for common Odoo errors
│   └── file_import.py       # CSV/Excel import with auto-model detection, column mapping, export
├── interfaces/              # 3 entry points
│   ├── cli.py               # argparse CLI — search, create, update, delete, fields, analytics
│   ├── mcp_server.py        # FastMCP server — 13 tools + 3 resources for AI assistants
│   └── openclaw_skill.py    # JSON stdin/stdout skill — 80+ routed actions
└── realtime/                # Background monitoring
    ├── poller.py            # ChangePoller — threaded write_date polling
    └── alerts.py            # AlertRouter — Telegram, webhook, callback dispatch with quiet hours
```

---

## Key Design Patterns

- **Layered config:** defaults → config file → env vars (highest priority)
- **Readonly mode:** `config.readonly = True` blocks all create/write/unlink at the client level
- **Smart fields:** Auto-selects ~15 most relevant fields per model via importance scoring (avoids binary/image/o2m)
- **Fuzzy find-or-create:** SmartActionHandler resolves names to IDs via exact → ilike fallback, auto-creates if missing
- **Error classification:** `classify_error()` maps Odoo fault strings to typed exceptions (connection, auth, access, validation, not-found)
- **Retry with backoff:** `@with_retry` on `OdooClient.execute()` — retries only on `retryable=True` errors (connection/timeout)
- **Soft delete:** `delete_partner`, `delete_event` archive via `active=False` rather than `unlink`

---

## Modules Summary

| Module | Odoo Models | Key Functions |
|--------|-------------|---------------|
| **partners** | `res.partner` | create, find (exact+fuzzy), get, update, delete, summary (with order/invoice counts), top customers |
| **sales** | `sale.order`, `sale.order.line` | create_quotation, confirm, cancel, send email, analyze (KPIs), trend (monthly), top products |
| **crm** | `crm.lead`, `crm.stage` | create_lead/opportunity, pipeline (grouped by stage), move_stage, mark_won/lost, forecast |
| **inventory** | `product.product`, `stock.quant`, `stock.move` | create/search products, check_availability, stock levels, low stock, turnover, valuation |
| **accounting** | `account.move`, `account.move.line`, `account.account` | create_invoice/bill, post, register_payment, unpaid/overdue, financial ratios, cashflow, aging |
| **hr** | `hr.employee`, `hr.attendance`, `hr.leave`, `hr.expense` | create employee, checkin/out, request leave, expenses, headcount by department |
| **projects** | `project.project`, `project.task`, `account.analytic.line`, `helpdesk.ticket` | create project/task, assign, timesheet, project summary, helpdesk (with fallback) |
| **purchase** | `purchase.order`, `purchase.order.line` | create PO, confirm/cancel, get, search, purchase summary with top vendors |
| **calendar** | `calendar.event` | create/get/search/update/delete event, today's events, upcoming events |

---

## Intelligence Layer

### Smart Actions (SmartActionHandler)
- `find_or_create_partner/product/project` — fuzzy name resolution with auto-creation
- `resolve_department/user` — name-to-ID resolution
- `smart_create_quotation/invoice/purchase/task/lead/employee` — end-to-end creation using names instead of IDs

### Analytics Dashboards
- **SalesAnalytics** — summary + trend + top products, period comparison
- **FinancialAnalytics** — ratios + cashflow + aging, profit/loss
- **InventoryAnalytics** — turnover + valuation + low stock, ABC analysis
- **HRAnalytics** — headcount + attendance + leaves, department costs
- **PipelineAnalytics** — pipeline analysis + forecast, conversion funnel
- **full_business_dashboard()** — all 5 combined

### Error Recovery (6 strategies)
1. **missing_required** — fills type-appropriate defaults
2. **type_mismatch** — coerces values to expected type
3. **duplicate** — returns existing record instead of failing
4. **field_not_found** — removes unknown fields
5. **date_format** — tries 7 common date formats → ISO
6. **access_denied** — logs warning (not auto-fixable)

### File Import/Export
- Auto-detects model from CSV/Excel headers via signature matching
- Column mapping: direct field name → label match → alias → fuzzy substring
- Many2one resolution: resolves string values to IDs via name search
- Export to CSV/Excel with many2one formatting

---

## Interfaces

### CLI (`openclaw-odoo`)
Commands: `search`, `create`, `update`, `delete`, `fields`, `analytics`
Entry point: `openclaw_odoo.interfaces.cli:main`

### MCP Server (13 tools)
`search_records`, `count_records`, `create_record`, `update_record`, `delete_record`, `execute_method`, `batch_execute`, `smart_action`, `analyze`, `import_file`, `export_data`, `list_models`, `get_fields`
Resources: `odoo://models`, `odoo://schema/{model}`, `odoo://server/info`

### OpenClaw Skill (80+ actions)
JSON stdin/stdout bridge. Actions route to module functions, smart actions, dashboards, import/export, and generic CRUD.

---

## Configuration

Config file search order:
1. `$OPENCLAW_ODOO_CONFIG` env var path
2. `~/.config/openclaw-odoo/config.json`
3. `./openclaw-odoo.json`

Key env vars: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`, `ODOO_API_KEY`, `OPENCLAW_ODOO_READONLY`, `OPENCLAW_ODOO_DEFAULT_LIMIT`, `OPENCLAW_ODOO_MAX_LIMIT`, `OPENCLAW_ODOO_PROTOCOL`

Protocol selection (`OPENCLAW_ODOO_PROTOCOL` env var or `"protocol"` in config file): `"auto"` (default — uses JSON-2 for Odoo 19+, JSON-RPC for older), `"json2"` (force JSON-2), `"jsonrpc"` (force JSON-RPC).

---

## Testing

- **31 test files**, 510+ tests, 93% coverage
- All tests mock `OdooClient` — no live Odoo required (except `test_integration_live.py`)
- Test layout mirrors source: `tests/test_modules/`, `tests/test_intelligence/`, `tests/test_interfaces/`, `tests/test_realtime/`
- Run: `pytest tests/ -v`

---

## Development Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run a specific module's tests
pytest tests/test_modules/test_sales.py -v

# CLI usage
openclaw-odoo search res.partner --fields name,email --limit 5
openclaw-odoo create product.product --values '{"name": "Widget", "list_price": 29.99}'
openclaw-odoo analytics sales --date-from 2026-01-01

# MCP server
python3 -m openclaw_odoo.interfaces.mcp_server
```

---

## Code Conventions

- Python 3.10+ with type hints throughout
- Google-style docstrings on all public functions
- Relative imports within the package (`from ..client import OdooClient`)
- Tests use absolute imports (`from openclaw_odoo.modules.sales import ...`)
- Module constants at top: `MODEL = "sale.order"`, field lists
- Return pattern: `{"id": record_id, "web_url": client.web_url(MODEL, record_id)}` for creates
- Soft-delete by default (archive via `active=False`), permanent delete only when explicitly requested
- `limit=None` in analytics queries to fetch all records for aggregation (bypasses default_limit)

---

## Known Patterns / Gotchas

- **Many2one fields** return `[id, name]` tuples from Odoo — code handles both tuple and int forms
- **`datetime.utcnow()`** is used in `calendar_mod.py` — deprecated in 3.12+, consider migrating to `datetime.now(timezone.utc)`
- **`fields_get()` is cached** per (model, attributes) in `OdooClient._fields_cache`
- **`get_top_customers`** fetches all confirmed orders (`limit=0`) then aggregates in Python — may be slow with large datasets
- **`_month_offset`** helper in `sales.py` handles month arithmetic for trend calculations
- **Helpdesk fallback**: `create_ticket` falls back to `project.task` if `helpdesk.ticket` raises `OdooAccessError`
- **Webhook signing** uses HMAC-SHA256 with sorted JSON payload
- **Quiet hours** support overnight ranges (e.g., 22:00-06:00) via wraparound logic
- **Duplicate `analyze_financial_ratios`** exists in both `accounting.py` and `analytics.py` — the analytics version adds `float()` casting

---

## Live Odoo 19 Connection (Development)

```
Odoo Server:  /home/workspace/odoo19/odoo/odoo-bin
Port:         5923
Database:     openclaw_odoo_db
Admin:        admin / admin
Python:       pyenv odoo19-venv (Python 3.12.3)
Addons:       /home/workspace/odoo19/odoo/addons,
              /home/workspace/odoo19/enterprise_19/enterprise
Config:       /home/odoo-openclaw/config.json
```

**Start Odoo:**
```bash
export PYENV_ROOT="$HOME/.pyenv" && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)" && eval "$(pyenv virtualenv-init -)"
pyenv activate odoo19-venv
cd /home/workspace/odoo19/odoo
python odoo-bin --http-port=5923 --database=openclaw_odoo_db --db_host=localhost \
  --addons-path=/home/workspace/odoo19/odoo/addons,/home/workspace/odoo19/enterprise_19/enterprise \
  --log-level=warn
```

**Run openclaw-odoo against it:**
```bash
pyenv activate odoo19-venv
cd /home/odoo-openclaw
export OPENCLAW_ODOO_CONFIG=/home/odoo-openclaw/config.json
openclaw-odoo search res.partner --fields name,email --limit 5
```

**Installed Odoo Modules (12):**
`sale`, `purchase`, `crm`, `stock`, `account`, `hr_attendance`, `hr_holidays`, `hr_expense`, `hr_timesheet`, `project`, `calendar`, `helpdesk`

---

## Live Integration Test Results (2026-03-17)

**82 / 82 tests passed — 100% success rate**

| Category | Tests | Result |
|----------|-------|--------|
| Config & Client | 2 | PASS |
| Partners (CRUD, search, summary, top customers) | 7 | PASS |
| Sales (quotation, confirm, analytics, trend) | 6 | PASS |
| CRM (lead, opportunity, pipeline, forecast) | 8 | PASS |
| Inventory (product, stock, valuation) | 6 | PASS |
| Accounting (invoice, payment, aging, ratios) | 6 | PASS |
| HR (employee, attendance, leave, headcount) | 8 | PASS |
| Projects (project, task, timesheet, ticket) | 7 | PASS |
| Purchase (PO, confirm, summary) | 5 | PASS |
| Calendar (event CRUD, today/upcoming) | 7 | PASS |
| Smart Actions (6 smart_create operations) | 6 | PASS |
| Analytics Dashboards (all 5 + full) | 6 | PASS |
| Batch Execute | 1 | PASS |
| Smart Fields | 2 | PASS |
| Error Recovery | 2 | PASS |
| File Import/Export | 3 | PASS |

**Discoveries during live testing:**
- `hr_timesheet` module is required for `log_timesheet` and `get_project_summary` (not listed in original deps)
- `helpdesk.ticket` creation in Odoo 19 requires `team_id` field (not just `project_id`)
- Some leave types (e.g., "Paid Time Off") require pre-allocated leave balance; "Unpaid" works without

---

## Swarm Audit Results (2026-03-17)

3 specialized agents ran in parallel: Security Auditor, Code Quality Analyst, Test Coverage Auditor.

### Security Audit (3 CRITICAL, 7 HIGH, 10 MEDIUM, 5 LOW)

**CRITICAL:**

| # | Finding | Location | Impact |
|---|---------|----------|--------|
| S1 | **Readonly bypass: `client.execute()` has zero readonly enforcement** | `client.py:94-155` | Only `create()`/`write()`/`unlink()` check readonly. Raw `execute()` allows any method on any model even in readonly mode. **Single most important fix needed.** |
| S2 | **Arbitrary method execution via skill `execute` action** | `openclaw_skill.py:259-264` | JSON stdin can invoke any Odoo method (incl. `unlink`, `action_confirm`) bypassing all guards. |
| S3 | **Arbitrary method execution via MCP `execute_method` tool** | `mcp_server.py:68-77` | Same as S2 but via MCP interface. AI assistants can call any server method. |

**HIGH:**

| # | Finding | Location |
|---|---------|----------|
| S4 | Batch executor denylist incomplete (only blocks `create`/`write`/`unlink`) | `batch.py:31` |
| S5 | Module functions bypass readonly via direct `execute()` calls (17+ functions) | `sales.py:60`, `accounting.py:50`, `purchase.py:70`, etc. |
| S6 | Password stored as plain-text instance attribute | `client.py:90` |
| S7 | No validation of `odoo_url` (SSRF risk) | `config.py:66`, `client.py:19` |
| S8 | File import accepts arbitrary filesystem paths (read) | `file_import.py:231,264` |
| S9 | File export writes to arbitrary filesystem paths (write) | `file_import.py:301-342` |
| S10 | HMAC signature computed over different JSON than sent | `alerts.py:145-153` |

**MEDIUM:** No model access restrictions, CWD config file loading, webhook URL SSRF, unsigned webhooks, openpyxl processes untrusted OOXML, error info leakage (skill + client), no rate limiting (MCP + skill), credentials over HTTP.

**Priority fix:** Add read-method allowlist to `client.execute()` — this single change fixes S1, S2, S3, S4, S5 simultaneously.

### Code Quality Audit (3 CRITICAL, 12 HIGH, 16 MEDIUM, 6 LOW = 37 issues)

**CRITICAL:**

| # | Finding | Location |
|---|---------|----------|
| Q1 | `analyze_financial_ratios` duplicated verbatim | `accounting.py:144` vs `analytics.py:78` |
| Q2 | N+1+M query pattern in `department_costs` (510+ RPC calls for 10 depts) | `analytics.py:392-407` |
| Q3 | `limit=None` silently capped to 50 — analytics produce wrong numbers | `client.py:174`, multiple callers |

**HIGH:**

| # | Finding | Location |
|---|---------|----------|
| Q4 | Duplicate `_aggregate_products` | `sales.py:293` vs `analytics.py:226` |
| Q5 | Duplicate `analyze_inventory_turnover` | `inventory.py:151` vs `analytics.py:119` |
| Q6 | `requests.Session` never closed (connection leak) | `client.py:20` |
| Q7 | `_rpc_id` and `_fields_cache` not thread-safe | `client.py:28-30,261` |
| Q8 | `_callbacks` list mutated without lock | `poller.py:35` |
| Q9 | Deprecated `datetime.utcnow()` (Python 3.12) | `calendar_mod.py:147,172` |
| Q10 | Broad `except Exception` without logging | `openclaw_skill.py:28` |
| Q11 | Unprotected `json.loads` in skill entry point | `openclaw_skill.py:279` |
| Q12 | Inconsistent mutation return shapes across modules | Multiple modules |
| Q13 | `str = None` instead of `Optional[str]` in hr.py (7 signatures) | `hr.py:10+` |
| Q14 | Tasks fetched twice in `get_project_summary` | `projects.py:143-162` |
| Q15 | `limit=0` treated as falsy in `get_top_customers` (gets 50 not all) | `partners.py:165` |

**MEDIUM:** Unreachable except clause in poller, `ValueError` instead of `OdooRecordNotFoundError` in checkout, operator precedence ambiguity in error recovery, Excel workbook not in finally, 22 functions implemented but not routed in skill interface, inconsistent `values` merge for updates, 2*N RPC calls in `get_revenue_vs_expense`, 7 redundant RPC calls for financial ratios, `send_quotation_email`/`send_invoice_email` undocumented in SKILL.md.

### Test Coverage Audit (~88% overall, 27 test files, ~310 test cases)

| Module | Coverage | Key Gaps |
|--------|----------|----------|
| `config.py` | ~65% | Readonly env var, limit validation, user/password env |
| `client.py` | ~72% | `search()`, `read()`, API-key auth, connection exceptions |
| `batch.py` | ~75% | Readonly batch blocking untested |
| `openclaw_skill.py` | ~75% | 13 action routes untested (calendar, purchase, import) |
| `retry.py` | ~78% | Delay mechanics (acceptable) |
| `cli.py` | ~80% | `main()`, JSON error paths |
| `fields.py` | ~80% | Scoring details, empty input |
| `accounting.py` | ~88% | **`send_invoice_email` — zero coverage** |
| `sales.py` | ~88% | **`send_quotation_email` — zero coverage** |
| `mcp_server.py` | ~88% | `main()`, 3 analyze report types |
| `file_import.py` | ~90% | Auto-detect failure paths |
| `crm.py` | ~92% | Minor empty pipeline gaps |
| `inventory.py`-`calendar_mod.py` | 93-95% | Solid |
| `smart_actions.py`-`error_recovery.py` | ~95% | Near-complete |
| `poller.py`, `alerts.py` | ~97% | Excellent |

**Zero-coverage functions:** `send_quotation_email`, `send_invoice_email` (both HIGH risk — multi-step wizard flows), `client.search()`, `client.read()`.

**Broken test file:** `test_integration_live.py` references nonexistent `AnalyticsEngine` and `OdooPoller` classes.

---

## File Sizes

| Component | Lines |
|-----------|-------|
| Source code total | ~5,075 |
| Largest module: `analytics.py` | 459 |
| Largest interface: `openclaw_skill.py` | 291 |
| Client (`client.py`) | 268 |
| Test files | 31 files |
