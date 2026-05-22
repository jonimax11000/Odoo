# -*- coding: utf-8 -*-
from datetime import timedelta, date
import json, re
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CookastAIChat(models.TransientModel):
    _name = "cookast.ai.chat"
    _description = "Chat con IA Cookast"

    question = fields.Text(string="Tu pregunta", required=True)
    response = fields.Text(string="Respuesta", readonly=True)

    def _find_locals_from_text(self, text):
        """Busca locales cuyos nombres aparezcan en el texto, con coincidencia parcial."""
        text_lower = text.lower()
        all_locals = self.env["cookast.local"].search([])
        found = []
        for loc in all_locals:
            if loc.name.lower() in text_lower:
                found.append(loc.id)
        return found

    def _get_pos_sales_context(self, local_ids=None):
        """Obtiene las ventas de TPV de hoy agrupadas por local."""
        from datetime import datetime, time
        import pytz

        today = fields.Date.context_today(self)
        user_tz = self.env.user.tz or 'UTC'
        try:
            local_tz = pytz.timezone(user_tz)
        except Exception:
            local_tz = pytz.utc

        # Convertir hoy local a datetimes UTC para la búsqueda en la BD
        start_local = datetime.combine(today, time.min)
        end_local = datetime.combine(today, time.max)
        
        start_utc = local_tz.localize(start_local).astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = local_tz.localize(end_local).astimezone(pytz.utc).replace(tzinfo=None)

        domain = [
            ('state', 'in', ['paid', 'done', 'invoiced']),
            ('date_order', '>=', start_utc),
            ('date_order', '<=', end_utc),
        ]
        if local_ids:
            domain.append(('cookast_local_id', 'in', local_ids))

        orders = self.env['pos.order'].search(domain)
        if not orders:
            return []

        # Agrupar ventas por local
        sales_by_local = {}
        for order in orders:
            local = order.cookast_local_id
            local_name = local.name if local else "Sin Local"
            if local_name not in sales_by_local:
                sales_by_local[local_name] = {'amount': 0.0, 'count': 0}
            sales_by_local[local_name]['amount'] += order.amount_total
            sales_by_local[local_name]['count'] += 1

        lines = []
        for loc_name, data in sales_by_local.items():
            lines.append(f"{loc_name}: {data['count']} pedidos, {data['amount']:.2f} €")

        return lines

    def _get_inventory_context(self, local_ids=None):
        """Obtiene todos los productos en el inventario real (stock.quant) para los locales dados."""
        domain_local = []
        if local_ids:
            domain_local.append(('id', 'in', local_ids))
        locales = self.env['cookast.local'].search(domain_local)
        
        lines = []
        for local in locales:
            if not local.location_id:
                continue
                
            quants = self.env['stock.quant'].search([
                ('location_id', 'child_of', local.location_id.id)
            ])
            
            product_qty = {}
            for q in quants:
                if q.product_id.detailed_type != 'product':
                    continue
                prod_name = q.product_id.display_name
                if prod_name not in product_qty:
                    product_qty[prod_name] = {'qty': 0.0, 'uom': q.product_uom_id.name}
                product_qty[prod_name]['qty'] += q.quantity
                
            if product_qty:
                lines.append(f"{local.name}:")
                for prod_name, data in product_qty.items():
                    lines.append(f" - {prod_name}: {data['qty']} {data['uom']}")
            else:
                lines.append(f"{local.name}: No hay datos de inventario registrados.")
                
        return lines

    def _extract_query_params(self, question):
        today = fields.Date.context_today(self)
        prompt = f"""Analiza la siguiente pregunta y devuelve ÚNICAMENTE un objeto JSON con esta estructura exacta:
{{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "locals": ["nombre exacto del local"],
  "shift": "lunch" | "dinner" | null,
  "data_types": ["forecast", "staffing", "weather", "material", "pos_sales"]
}}

Reglas:
- Si no se especifica fecha, usa hoy: {today}.
- "esta semana" o "próximos días": start_date = {today}, end_date = {(fields.Date.context_today(self) + timedelta(days=7)).strftime('%Y-%m-%d')}.
- "mes pasado": primer día del mes anterior al último.
- "el 15 de mayo": start_date = end_date = 2026-05-15.
- locals: [] si se refiere a todos.
- shift: null si no se menciona.
- data_types: incluye los relevantes (weather para clima, material para compras/materias primas, pos_sales para ventas/caja/pedidos/ingresos de hoy).

Pregunta: "{question}"
JSON:"""
        try:
            ai_config = self.env["cookast.ai.config"]._get_active_config()
            response = ai_config._query_ai(prompt)
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                params = json.loads(match.group())
                # Convertir fechas
                if params.get("start_date"):
                    params["start_date"] = date.fromisoformat(params["start_date"])
                if params.get("end_date"):
                    params["end_date"] = date.fromisoformat(params["end_date"])
                # Buscar locales
                if params.get("locals"):
                    locales = self.env["cookast.local"].search(
                        [("name", "in", params["locals"])]
                    )
                    if not locales:
                        locales = self._find_locals_from_text(question)
                    params["local_ids"] = locales.ids
                else:
                    params["local_ids"] = self._find_locals_from_text(question) or []
                # Forzar data_types según palabras clave
                q_lower = question.lower()
                if any(w in q_lower for w in ["cliente", "persona", "previsi", "venta", "facturaci", "ingreso"]):
                    if "forecast" not in params.setdefault("data_types", []):
                        params["data_types"].append("forecast")
                if any(w in q_lower for w in ["personal", "staff", "camarero", "cocinero", "necesito", "plantilla"]):
                    if "staffing" not in params.setdefault("data_types", []):
                        params["data_types"].append("staffing")
                if any(w in q_lower for w in ["clima", "meteorol", "lluvia", "temperatura", "tiempo"]):
                    if "weather" not in params.setdefault("data_types", []):
                        params["data_types"].append("weather")
                if any(w in q_lower for w in ["compra", "materia prima", "stock", "ingrediente"]):
                    if "material" not in params.setdefault("data_types", []):
                        params["data_types"].append("material")
                if any(w in q_lower for w in ["venta", "caja", "tpv", "facturaci", "pedido", "ingreso"]):
                    if "pos_sales" not in params.setdefault("data_types", []):
                        params["data_types"].append("pos_sales")
                
                # Si a pesar de todo data_types está vacío, poner todos por defecto
                if not params.get("data_types"):
                    params["data_types"] = ["forecast", "staffing", "weather", "material", "pos_sales"]
                    
                return params
        except Exception as e:
            _logger.warning("Error extrayendo parámetros: %s", e)

        return {
            "start_date": today - timedelta(days=7),
            "end_date": today + timedelta(days=7),
            "local_ids": [],
            "shift": None,
            "data_types": ["forecast", "staffing", "weather", "material", "pos_sales"],
        }

    def _get_context_data(self, params):
        start = params.get("start_date")
        end = params.get("end_date")
        local_ids = params.get("local_ids", [])
        shift = params.get("shift")
        data_types = params.get("data_types", [])

        domain_base = [("date", ">=", start), ("date", "<=", end)]
        if local_ids:
            domain_base.append(("local_id", "in", local_ids))

        context_parts = []
        today_date = fields.Date.context_today(self)
        tomorrow_date = today_date + timedelta(days=1)

        def _format_date(d):
            if d == today_date:
                return f"{d} (Hoy)"
            elif d == tomorrow_date:
                return f"{d} (Mañana)"
            return str(d)

        if "forecast" in data_types or "staffing" in data_types:
            forecast_domain = domain_base[:]
            if shift:
                forecast_domain.append(("shift", "=", shift))
            forecasts = self.env["cookast.forecast"].search(forecast_domain)
            if forecasts:
                lines = []
                for fc in forecasts:
                    shift_name = dict(fc._fields["shift"].selection).get(
                        fc.shift, fc.shift
                    )
                    date_label = _format_date(fc.date)
                    line = f"{date_label} | {fc.local_id.name} | {shift_name}: Previsión tradicional: {fc.forecast_revenue:.0f}€, Previsión IA: {fc.ai_forecast_revenue:.0f}€"
                    if "staffing" in data_types and fc.staffing_need_id:
                        sn = fc.staffing_need_id
                        line += f" | Personal: {sn.total_persons} pers (R:{sn.responsible_qty}, S:{sn.senior_qty}, J:{sn.junior_qty})"
                    lines.append(line)
                context_parts.append("=== PREVISIONES Y PERSONAL ===")
                context_parts.extend(lines)

        if "weather" in data_types and "cookast.weather.forecast" in self.env:
            weather_domain = domain_base[:]
            weathers = self.env["cookast.weather.forecast"].search(weather_domain)
            if weathers:
                lines = []
                for w in weathers:
                    date_label = _format_date(w.date)
                    lines.append(
                        f"{date_label} | {w.local_id.name}: {w.weather_condition}, "
                        f"{w.temp_min:.0f}–{w.temp_max:.0f}°C, lluvia: {w.rain_mm:.1f}mm, "
                        f"viento: {w.wind_kmh:.0f}km/h, factor: {w.weather_factor:+.1f}%"
                    )
                context_parts.append("\n=== CLIMA ===")
                context_parts.extend(lines)
            else:
                context_parts.append(
                    "\n=== CLIMA ===\nNo hay datos meteorológicos para el período/local solicitado."
                )

        if "material" in data_types and "cookast.material.need" in self.env:
            mat_domain = [("stock_status", "in", ["out", "low"])]
            if local_ids:
                mat_domain.append(("local_id", "in", local_ids))
            needs = self.env["cookast.material.need"].search(mat_domain)
            if needs:
                lines = []
                for mn in needs:
                    lines.append(
                        f"{mn.local_id.name}: {mn.product_name} – stock: {mn.qty_available} {mn.uom_id.name}, "
                        f"necesidad: {mn.total_needed} {mn.uom_id.name}, "
                        f"a comprar: {mn.qty_to_purchase} {mn.uom_id.name}"
                    )
                context_parts.append("\n=== NECESIDADES DE MATERIAS PRIMAS ===")
                context_parts.extend(lines)
            
            # Obtener TODO el inventario de los locales
            inventory_lines = self._get_inventory_context(local_ids=local_ids)
            context_parts.append("\n=== INVENTARIO GENERAL EN LOCALES ===")
            if inventory_lines:
                context_parts.extend(inventory_lines)
            else:
                context_parts.append("No hay registros de inventario disponibles.")

        if "pos_sales" in data_types:
            pos_lines = self._get_pos_sales_context(local_ids=local_ids)
            context_parts.append("\n=== VENTAS TPV HOY ===")
            if pos_lines:
                context_parts.extend(pos_lines)
            else:
                context_parts.append("No hay ventas TPV registradas hoy.")

        return (
            "\n".join(context_parts)
            if context_parts
            else "No hay datos para el período solicitado."
        )


    @api.model
    def _process_query(self, user_id, question):
        if "cookast.ai.config" not in self.env:
            return "El módulo Cookast AI no está configurado."

        params = self._extract_query_params(question)
        context = self._get_context_data(params)

        ai_config = self.env["cookast.ai.config"]._get_active_config()
        today_str = fields.Date.context_today(self).strftime('%Y-%m-%d')
        tomorrow_str = (fields.Date.context_today(self) + timedelta(days=1)).strftime('%Y-%m-%d')
        
        prompt = f"""Eres un asistente de IA experto en restaurantes.
IMPORTANTE - CALENDARIO:
- Hoy es: {today_str}
- Mañana es: {tomorrow_str}

DATOS DISPONIBLES EN SISTEMA:
{context}

Pregunta del usuario: "{question}"

Instrucciones para responder:
1. Responde en español, de forma clara y amable.
2. Basa tu respuesta EXCLUSIVAMENTE en los DATOS DISPONIBLES arriba.
3. Cruza la palabra "hoy" con {today_str} y "mañana" con {tomorrow_str}. Si tienes los datos, dalos directamente.
4. Cuando des previsiones, especifica la fecha, local y turno de forma amigable.
5. Si no hay datos, dilo explícitamente.

Respuesta:"""

        response = ai_config._query_ai(prompt)
        return response

    def action_send(self):
        self.ensure_one()
        self.response = self._process_query(self.env.uid, self.question)
        return {
            "type": "ir.actions.act_window",
            "res_model": "cookast.ai.chat",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": "Chat IA Cookast",
        }
