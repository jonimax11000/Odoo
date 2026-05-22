# -*- coding: utf-8 -*-
import re
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CookastMaterialNeed(models.Model):
    _inherit = "cookast.material.need"

    def _build_ai_material_prompt(self):
        self.ensure_one()
        product = self.product_id
        local = self.local_id
        today = fields.Date.context_today(self)
        end_date = today + timedelta(days=7)

        stock = self.qty_available
        immediate_need = self.total_needed

        forecasts = self.env["cookast.forecast"].search(
            [
                ("local_id", "=", local.id),
                ("date", ">=", today),
                ("date", "<=", end_date),
            ]
        )
        total_forecast = sum(forecasts.mapped("forecast_revenue"))

        purchase_lines = self.env["purchase.order.line"].search(
            [
                ("product_id", "=", product.id),
                ("state", "in", ["purchase", "done"]),
            ],
            order="id desc",
            limit=4,
        )
        hist_qtys = [line.product_qty for line in purchase_lines]
        hist_str = (
            ", ".join(str(q) for q in hist_qtys) if hist_qtys else "sin historial"
        )

        pending_qty = 0.0
        if local.warehouse_id:
            po_lines = (
                self.env["purchase.order.line"]
                .sudo()
                .search(
                    [
                        ("product_id", "=", product.id),
                        ("order_id.state", "=", "purchase"),
                        (
                            "order_id.picking_type_id.warehouse_id",
                            "=",
                            local.warehouse_id.id,
                        ),
                    ]
                )
            )
            for line in po_lines:
                pending_qty += line.product_qty - line.qty_received

        prompt = f"""Producto: {product.display_name} ({self.uom_id.name})
Local: {local.name}
Stock actual: {stock} {self.uom_id.name}
Necesidad semanal estimada: {immediate_need} {self.uom_id.name}
Ingresos previstos para la próxima semana: {total_forecast:.0f}€
Cantidad ya pedida y pendiente: {pending_qty} {self.uom_id.name}
Compras anteriores: {hist_str}

Recomienda cuántas unidades comprar esta semana. Responde solo con el número."""
        return prompt

    def action_ai_suggest_purchase(self):
        """Devuelve la cantidad sugerida por la IA sin modificar el registro."""
        self.ensure_one()
        if "cookast.ai.config" not in self.env:
            raise UserError(_("El módulo Cookast AI no está configurado."))

        ai_config = self.env["cookast.ai.config"]._get_active_config()
        prompt = self._build_ai_material_prompt()
        response = ai_config._query_ai(prompt)

        numbers = re.findall(r"\d+", response)
        if not numbers:
            _logger.warning(
                "La IA no devolvió un número para %s. Respuesta: %s",
                self.product_id.display_name,
                response,
            )
            raise UserError(
                _("La IA no devolvió un número para %s.\nRespuesta: %s")
                % (self.product_id.display_name, response)
            )

        return int(numbers[0])

    def action_ai_suggest_all_purchases(self):
        """Genera pedidos de compra con las cantidades sugeridas por la IA para
        todos los productos con necesidad, sin necesidad de seleccionar ninguno.
        """
        needs = self.search([])
        supplier_local_lines = {}
        no_supplier = []
        updated = 0
        for need in needs:
            try:
                suggested_qty = need.action_ai_suggest_purchase()
                if suggested_qty <= 0:
                    continue
                updated += 1
                sellers = need.product_id.seller_ids
                if sellers:
                    supplier = sellers[0].partner_id
                    key = (supplier.id, need.local_id.id)
                    if key not in supplier_local_lines:
                        supplier_local_lines[key] = {
                            "partner": supplier,
                            "local": need.local_id,
                            "lines": [],
                        }
                    supplier_local_lines[key]["lines"].append(
                        {
                            "product": need.product_id,
                            "qty": suggested_qty,
                            "uom": need.uom_id,
                            "cost": need.unit_cost,
                        }
                    )
                else:
                    no_supplier.append(need.product_id.display_name)
            except Exception as e:
                _logger.error("Error IA compra %s: %s", need.product_id.display_name, e)

        if not supplier_local_lines and not no_supplier:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sin sugerencias"),
                    "message": _("No se generaron sugerencias de compra."),
                    "type": "warning",
                },
            }

        created_pos = self.env["purchase.order"]
        for (supplier_id, local_id), data in supplier_local_lines.items():
            po_lines = [
                (
                    0,
                    0,
                    {
                        "product_id": line["product"].id,
                        "name": line["product"].display_name,
                        "product_qty": line["qty"],
                        "product_uom_id": line["uom"].id,
                        "price_unit": line["cost"],
                    },
                )
                for line in data["lines"]
            ]

            picking_type = self.env["stock.picking.type"].search(
                [
                    ("warehouse_id", "=", data["local"].warehouse_id.id),
                    ("code", "=", "incoming"),
                ],
                limit=1,
            )

            po_vals = {
                "partner_id": data["partner"].id,
                "order_line": po_lines,
            }
            if picking_type:
                po_vals["picking_type_id"] = picking_type.id

            po = self.env["purchase.order"].create(po_vals)
            created_pos |= po

        message = _("Se actualizaron %d productos.") % updated
        if no_supplier:
            message += (
                "\n" + _("Productos sin proveedor:") + " " + ", ".join(no_supplier)
            )

        if len(created_pos) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Pedido de Compra Sugerido por IA"),
                "res_model": "purchase.order",
                "res_id": created_pos.id,
                "view_mode": "form",
                "target": "current",
            }

        return {
            "type": "ir.actions.act_window",
            "name": _("Pedidos de Compra Sugeridos por IA"),
            "res_model": "purchase.order",
            "domain": [("id", "in", created_pos.ids)],
            "view_mode": "list,form",
            "target": "current",
        }
