"""SmartActionHandler -- fuzzy find_or_create, resolve, and smart_create operations."""
from __future__ import annotations

from typing import Any, Optional

from ..client import OdooClient
from ..errors import OdooClawError

_SENSITIVE_MODELS = frozenset({
    "res.users", "ir.cron", "ir.config_parameter", "ir.module.module",
    "ir.rule", "ir.model.access", "ir.ui.view", "ir.actions.server",
    "ir.mail_server", "base.automation",
})


class SmartActionHandler:
    def __init__(self, client: OdooClient):
        self.client = client

    # ----- internal helpers -----

    def _fuzzy_find(
        self, model: str, name_field: str, query: str,
        extra_fields: Optional[list[str]] = None,
        alt_fields: Optional[list[str]] = None,
    ) -> Optional[dict]:
        fields = [name_field] + (extra_fields or [])
        # Exact match first
        domain = [[name_field, "=", query]]
        results = self.client.search_read(model, domain=domain, fields=fields, limit=1)
        if results:
            return results[0]

        # Fuzzy (ilike) on name + alt fields
        search_fields = [name_field] + (alt_fields or [])
        if len(search_fields) == 1:
            ilike_domain = [[name_field, "ilike", query]]
        else:
            or_clauses: list = []
            for i, f in enumerate(search_fields):
                if i > 0:
                    or_clauses.insert(0, "|")
                or_clauses.append([f, "ilike", query])
            ilike_domain = or_clauses

        results = self.client.search_read(model, domain=ilike_domain, fields=fields, limit=1)
        return results[0] if results else None

    # =============================================================
    # generic find_or_create (registry-driven)
    # =============================================================

    def generic_find_or_create(
        self, model: str, name: str,
        name_field: str = "name",
        extra_values: Optional[dict] = None,
    ) -> dict:
        """Find a record by name or create it. Works for any model.

        Args:
            model: Odoo model technical name (e.g. 'x_fleet.vehicle').
            name: Value to search for / create with.
            name_field: Field to search on (default 'name').
            extra_values: Additional field values for creation.

        Returns:
            Dict with 'id', name_field value, and 'created' (bool).

        Raises:
            OdooClawError: If model is in the sensitive models deny list.
        """
        if model in _SENSITIVE_MODELS:
            raise OdooClawError(f"Cannot create records in sensitive model: {model}")

        found = self._fuzzy_find(model, name_field, name)
        if found:
            return {"id": found["id"], name_field: found.get(name_field, name), "created": False}

        vals: dict[str, Any] = {name_field: name}
        if extra_values:
            vals.update(extra_values)
        record_id = self.client.create(model, vals)
        return {"id": record_id, name_field: name, "created": True}

    # =============================================================
    # find_or_create: partner, product, project
    # =============================================================

    def find_or_create_partner(
        self, name: str, email: Optional[str] = None,
        is_company: bool = False, **extra: Any,
    ) -> dict:
        """Find an existing partner by name/email/phone, or create a new one.

        Returns:
            Dict with 'id', 'name', and 'created' (bool).
        """
        found = self._fuzzy_find(
            "res.partner", "name", name,
            extra_fields=["email", "phone"],
            alt_fields=["email", "phone"],
        )
        if found:
            return {"id": found["id"], "name": found.get("name", name), "created": False}

        vals: dict[str, Any] = {"name": name, "is_company": is_company}
        if email:
            vals["email"] = email
        vals.update(extra)
        record_id = self.client.create("res.partner", vals)
        return {"id": record_id, "name": name, "created": True}

    def find_or_create_product(
        self, name: str, list_price: float = 0, **extra: Any,
    ) -> dict:
        """Find an existing product by name, or create a new one.

        Returns:
            Dict with 'id', 'name', and 'created' (bool).
        """
        found = self._fuzzy_find(
            "product.product", "name", name,
            extra_fields=["list_price"],
        )
        if found:
            return {"id": found["id"], "name": found.get("name", name), "created": False}

        vals: dict[str, Any] = {"name": name, "list_price": list_price}
        vals.update(extra)
        record_id = self.client.create("product.product", vals)
        return {"id": record_id, "name": name, "created": True}

    def find_or_create_project(self, name: str, **extra: Any) -> dict:
        """Find an existing project by name, or create a new one.

        Returns:
            Dict with 'id', 'name', and 'created' (bool).
        """
        found = self._fuzzy_find("project.project", "name", name)
        if found:
            return {"id": found["id"], "name": found.get("name", name), "created": False}

        vals = {"name": name, **extra}
        record_id = self.client.create("project.project", vals)
        return {"id": record_id, "name": name, "created": True}

    # =============================================================
    # resolve: department, user
    # =============================================================

    def resolve_department(self, name: str, auto_create: bool = False) -> Optional[int]:
        """Resolve a department name to its record ID.

        Args:
            name: Department name to search for.
            auto_create: If True, create the department when not found.

        Returns:
            Department record ID, or None if not found and auto_create is False.
        """
        found = self._fuzzy_find("hr.department", "name", name)
        if found:
            return found["id"]
        if auto_create:
            return self.client.create("hr.department", {"name": name})
        return None

    def resolve_user(self, name: str) -> Optional[int]:
        """Resolve a user name or login to their record ID, or None if not found."""
        found = self._fuzzy_find(
            "res.users", "name", name,
            extra_fields=["login"],
            alt_fields=["login"],
        )
        return found["id"] if found else None

    # =============================================================
    # smart_create: quotation, invoice, purchase, task, lead, employee
    # =============================================================

    def smart_create_quotation(
        self, partner: str, lines: list[dict], **extra: Any,
    ) -> dict:
        """Create a quotation resolving partner and products by name.

        Args:
            partner: Partner name (fuzzy-matched or auto-created).
            lines: List of dicts with 'product' name, 'quantity', optional 'price_unit'.
            **extra: Additional sale.order field values.

        Returns:
            Dict with 'id' and 'web_url' of the created quotation.
        """
        partner_result = self.find_or_create_partner(partner)
        partner_id = partner_result["id"]

        order_lines = []
        for line in lines:
            product_result = self.find_or_create_product(line["product"])
            vals: dict[str, Any] = {
                "product_id": product_result["id"],
                "product_uom_qty": line.get("quantity", 1),
            }
            if "price_unit" in line:
                vals["price_unit"] = line["price_unit"]
            order_lines.append((0, 0, vals))

        values = {"partner_id": partner_id, "order_line": order_lines, **extra}
        record_id = self.client.create("sale.order", values)
        return {"id": record_id, "web_url": self.client.web_url("sale.order", record_id)}

    def smart_create_invoice(
        self, partner: str, lines: list[dict],
        move_type: str = "out_invoice", **extra: Any,
    ) -> dict:
        """Create an invoice resolving partner by name.

        Args:
            partner: Partner name (fuzzy-matched or auto-created).
            lines: Invoice line dicts with 'quantity', 'price_unit', optional 'product_id'/'name'.
            move_type: Invoice type (default 'out_invoice').
            **extra: Additional account.move field values.

        Returns:
            Dict with 'id' and 'web_url' of the created invoice.
        """
        partner_result = self.find_or_create_partner(partner)
        partner_id = partner_result["id"]

        invoice_lines = []
        for line in lines:
            vals: dict[str, Any] = {
                "quantity": line.get("quantity", 1),
                "price_unit": line.get("price_unit", 0),
            }
            if "product_id" in line:
                vals["product_id"] = line["product_id"]
            if "name" in line:
                vals["name"] = line["name"]
            invoice_lines.append((0, 0, vals))

        values = {
            "move_type": move_type,
            "partner_id": partner_id,
            "invoice_line_ids": invoice_lines,
            **extra,
        }
        record_id = self.client.create("account.move", values)
        return {"id": record_id, "web_url": self.client.web_url("account.move", record_id)}

    def smart_create_purchase(
        self, partner: str, lines: list[dict], **extra: Any,
    ) -> dict:
        """Create a purchase order resolving partner and products by name.

        Args:
            partner: Vendor name (fuzzy-matched or auto-created).
            lines: List of dicts with 'product' name, 'quantity', optional 'price_unit'.
            **extra: Additional purchase.order field values.

        Returns:
            Dict with 'id' and 'web_url' of the created purchase order.
        """
        partner_result = self.find_or_create_partner(partner)
        partner_id = partner_result["id"]

        order_lines = []
        for line in lines:
            product_result = self.find_or_create_product(line["product"])
            vals: dict[str, Any] = {
                "product_id": product_result["id"],
                "product_qty": line.get("quantity", 1),
            }
            if "price_unit" in line:
                vals["price_unit"] = line["price_unit"]
            order_lines.append((0, 0, vals))

        values = {"partner_id": partner_id, "order_line": order_lines, **extra}
        record_id = self.client.create("purchase.order", values)
        return {"id": record_id, "web_url": self.client.web_url("purchase.order", record_id)}

    def smart_create_task(
        self, project: str, name: str,
        user: Optional[str] = None, **extra: Any,
    ) -> dict:
        """Create a task resolving project and assignee by name.

        Args:
            project: Project name (fuzzy-matched or auto-created).
            name: Task title.
            user: Optional assignee name (resolved to user ID).
            **extra: Additional project.task field values.

        Returns:
            Dict with 'id' and 'web_url' of the created task.
        """
        project_result = self.find_or_create_project(project)
        project_id = project_result["id"]

        vals: dict[str, Any] = {"project_id": project_id, "name": name}
        if user:
            user_id = self.resolve_user(user)
            if user_id:
                vals["user_ids"] = [user_id]
        vals.update(extra)
        record_id = self.client.create("project.task", vals)
        return {"id": record_id, "web_url": self.client.web_url("project.task", record_id)}

    def smart_create_lead(
        self, name: str, contact_name: Optional[str] = None,
        email: Optional[str] = None, partner: Optional[str] = None,
        **extra: Any,
    ) -> dict:
        """Create a CRM lead, optionally resolving the partner by name.

        Args:
            name: Lead title.
            contact_name: Optional contact person name.
            email: Optional contact email.
            partner: Optional partner name (fuzzy-matched or auto-created).
            **extra: Additional crm.lead field values.

        Returns:
            Dict with 'id' and 'web_url' of the created lead.
        """
        vals: dict[str, Any] = {"name": name}
        if contact_name:
            vals["contact_name"] = contact_name
        if email:
            vals["email_from"] = email
        if partner:
            partner_result = self.find_or_create_partner(partner)
            vals["partner_id"] = partner_result["id"]
        vals.update(extra)
        record_id = self.client.create("crm.lead", vals)
        return {"id": record_id, "web_url": self.client.web_url("crm.lead", record_id)}

    def smart_create_employee(
        self, name: str, job_title: Optional[str] = None,
        department: Optional[str] = None, **extra: Any,
    ) -> dict:
        """Create an employee, resolving department by name.

        Args:
            name: Employee full name.
            job_title: Optional job title.
            department: Optional department name (resolved to ID).
            **extra: Additional hr.employee field values.

        Returns:
            Dict with 'id' and 'web_url' of the created employee.
        """
        vals: dict[str, Any] = {"name": name}
        if job_title:
            vals["job_title"] = job_title
        if department:
            dept_id = self.resolve_department(department, auto_create=True)
            if dept_id:
                vals["department_id"] = dept_id
        vals.update(extra)
        record_id = self.client.create("hr.employee", vals)
        return {"id": record_id, "web_url": self.client.web_url("hr.employee", record_id)}
