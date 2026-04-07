# Contributing to openclaw-odoo

Thank you for your interest in contributing!

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/parth-unjiya/openclaw-odoo.git
   cd openclaw-odoo
   ```

2. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install in development mode:
   ```bash
   pip install -e ".[dev]"
   ```

4. Run tests:
   ```bash
   pytest tests/ -v
   ```

## Project Structure

```
src/openclaw_odoo/
├── client.py              # JSON-RPC client for Odoo
├── config.py              # Configuration (file + env vars)
├── errors.py              # Error hierarchy
├── retry.py               # Exponential backoff retry
├── fields.py              # Smart field selection
├── batch.py               # Batch operations
├── modules/               # Business modules (one per Odoo domain)
├── intelligence/          # Smart actions, analytics, error recovery, file import
├── interfaces/            # CLI, MCP server, OpenClaw skill
└── realtime/              # Change poller, alert router
```

## Code Style

- Python 3.10+ with type hints
- Docstrings on all public functions (Google style)
- Relative imports within the package (`from ..client import OdooClient`)
- Tests use absolute imports (`from openclaw_odoo.modules.sales import ...`)

## Adding a New Business Module

1. Create `src/openclaw_odoo/modules/your_module.py`
   - Set `MODEL = "odoo.model.name"` at top
   - Import from `..client`, `..fields`, `..errors`
   - Add docstrings to every function
2. Create `tests/test_modules/test_your_module.py`
   - Mock OdooClient with `unittest.mock.MagicMock`
   - Test every function including error cases
3. Register actions in `src/openclaw_odoo/interfaces/openclaw_skill.py`
4. Run full test suite: `pytest tests/ -v`

## Pull Requests

- One feature per PR
- Include tests for all new code
- Update CHANGELOG.md
- Run the full test suite before submitting
- Keep commits focused and well-described
