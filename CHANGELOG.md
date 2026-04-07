# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-03-09

### Added
- 9 business modules: Partners, Sales, CRM, Inventory, Accounting, HR, Projects, Purchase, Calendar
- Dynamic Model Registry — auto-discovers all Odoo models (including custom ones) and generates smart CRUD, workflow actions, and analytics dashboards automatically
- 86+ actions via OpenClaw skill interface
- 12 MCP tools for AI assistant integration (Claude Desktop, ChatGPT, Cursor, etc.)
- CLI with search, create, update, delete, fields, analytics, and discover commands
- 6 smart actions with fuzzy find-or-create (quotation, invoice, purchase, lead, task, employee)
- 5 analytics dashboards (sales, financial, inventory, HR, pipeline)
- CSV/Excel import with auto-model detection and column mapping
- Record export to CSV/Excel
- Real-time change detection with configurable polling
- Alert routing to Telegram, webhooks, and Python callbacks with quiet hours
- Automatic error recovery with 6 fix strategies
- JSON-RPC client — works with any Odoo 19 instance, no extra modules needed
- Smart field selection — returns ~15 most relevant fields per model
- Batch operations with fail-fast control
- Readonly mode for safe exploration
- Exponential backoff retry with jitter
- Security hardening: readonly enforcement, password redaction in __repr__, error classification
- Model hints support for custom module configuration
- 809 tests with 93% code coverage
