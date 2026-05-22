# -*- coding: utf-8 -*-
"""cookast_ai – Capa de refinamiento con IA para la predicción de clientes.

Este módulo extiende `cookast.forecast` (definido en cookast) para añadir:
- `action_ai_predict_customers`: llama a la IA para refinar la estimación base.
- `_build_customer_traffic_prompt`: construye el prompt para el LLM.

La lógica algorítmica pura (sin IA) vive en cookast.forecast_customers.
"""
from odoo import models, _
import logging
import re

_logger = logging.getLogger(__name__)


class CookastForecastAI(models.Model):
    _inherit = 'cookast.forecast'

    # ── Refinamiento con IA ────────────────────────────────────────────────────

    def action_ai_predict_customers(self):
        """Calcula clientes con el algoritmo base y luego refina con IA.

        Si la IA no está configurada o falla, se usa el resultado algorítmico.
        Escribe en `expected_customers` (campo definido en cookast).
        """
        for record in self:
            # 1. Base algorítmica (siempre disponible, definida en cookast)
            baseline, avg_ticket = record._compute_customer_baseline()

            # 2. Refinar con IA si está disponible
            ai_config = self.env['cookast.ai.config'].search(
                [('active', '=', True)], limit=1
            )
            predicted = baseline
            if ai_config:
                try:
                    prompt   = record._build_customer_traffic_prompt(baseline, avg_ticket)
                    response = ai_config._query_ai(prompt)
                    match    = re.search(r'\b(\d+)\b', response)
                    if match:
                        ai_value = int(match.group(1))
                        # Aceptar solo si es razonablemente coherente con la base
                        if baseline * 0.3 <= ai_value <= baseline * 3:
                            predicted = ai_value
                        else:
                            _logger.info(
                                "IA devolvió %s clientes (baseline %s): fuera de rango, ignorado.",
                                ai_value, baseline,
                            )
                except Exception as e:
                    _logger.warning("Error al consultar la IA para clientes: %s", e)

            record.expected_customers = predicted

        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   _('Predicción IA completada'),
                'message': _('Clientes estimados (IA): %s  |  Ticket medio: %.2f €') % (predicted, avg_ticket),
                'sticky':  False,
                'type':    'success',
            },
        }

    # ── Construcción del prompt ────────────────────────────────────────────────

    def _build_customer_traffic_prompt(self, baseline, avg_ticket):
        """Construye el prompt que se envía al LLM para refinar la estimación."""
        self.ensure_one()

        # Historial reciente (mismo local + turno)
        past = self.search([
            ('local_id',       '=', self.local_id.id),
            ('shift',          '=', self.shift),
            ('date',           '<', self.date),
            ('actual_revenue', '>', 0),
        ], order='date desc', limit=7)

        lines = []
        for pf in past:
            n = len(pf.pos_order_ids)
            if n > 0:
                lines.append(
                    f"- {pf.date}: {pf.actual_revenue:.0f}€, "
                    f"{n} pedidos, ticket {pf.actual_revenue / n:.1f}€"
                )
            else:
                lines.append(f"- {pf.date}: {pf.actual_revenue:.0f}€ (sin detalle de pedidos)")

        historical = "\n".join(lines) if lines else "Sin historial disponible."

        # Clima (opcional)
        weather_info = ""
        if 'cookast.weather.forecast' in self.env:
            weather = self.env['cookast.weather.forecast'].search([
                ('local_id', '=', self.local_id.id),
                ('date',     '=', self.date),
            ], limit=1)
            if weather:
                weather_info = f"\nClima: {weather.temp_max}ºC máx, {weather.rain_mm} mm lluvia."

        return (
            f"LOCAL: {self.local_id.name} | TURNO: {self.shift} | "
            f"FECHA: {self.date} ({self.date.strftime('%A')})\n"
            f"INGRESO PREVISTO: {self.forecast_revenue:.0f}€\n"
            f"TICKET MEDIO REAL: {avg_ticket:.2f}€\n"
            f"ESTIMACIÓN BASE (ingresos/ticket): {baseline} clientes{weather_info}\n\n"
            f"Historial reciente (mismo local y turno):\n{historical}\n\n"
            f"Ajusta la estimación base teniendo en cuenta el día de la semana y el clima.\n"
            f"RESPONDE SOLO CON UN NÚMERO ENTERO. Ejemplo: 34"
        )
