# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class CookastForecastCustomers(models.Model):
    """Extensión de cookast.forecast para la predicción algorítmica de clientes.
    
    No depende de IA. Calcula el número de clientes esperados usando
    el histórico de pedidos POS del mismo local y turno.
    """
    _inherit = 'cookast.forecast'

    expected_customers = fields.Integer(
        string='Clientes Esperados',
        help=(
            "Número de clientes estimado para este turno. "
            "Calculado automáticamente con datos históricos POS. "
            "Puede ajustarse manualmente o refinarse con IA (módulo cookast_ai)."
        ),
    )

    # ── Cálculo algorítmico puro ───────────────────────────────────────────────

    def _compute_customer_baseline(self):
        """Devuelve (n_clientes, ticket_medio) sin usar ningún modelo de IA.

        Jerarquía de fuentes:
        1. Ticket medio real  = avg(actual_revenue / n_pedidos_POS) de los
           últimos 14 días del mismo local+turno con ingresos > 0.
        2. Si no hay pedidos POS: heurístico staffing × 3 clientes/persona.
        3. Fallback final: 18 € ticket medio estándar de restaurante.
        """
        self.ensure_one()

        past = self.search([
            ('local_id',      '=', self.local_id.id),
            ('shift',         '=', self.shift),
            ('date',          '<', self.date),
            ('actual_revenue', '>', 0),
        ], order='date desc', limit=14)

        total_ticket = 0.0
        valid_days   = 0
        for pf in past:
            n = len(pf.pos_order_ids)
            if n > 0:
                total_ticket += pf.actual_revenue / n
                valid_days   += 1

        if valid_days > 0:
            avg_ticket = total_ticket / valid_days
        else:
            staffing = self.staffing_need_id
            if staffing and staffing.total_persons > 0:
                covers     = staffing.total_persons * 3
                avg_ticket = self.forecast_revenue / covers if covers else 18.0
            else:
                avg_ticket = 18.0

        if avg_ticket > 0 and self.forecast_revenue > 0:
            return max(1, round(self.forecast_revenue / avg_ticket)), avg_ticket
        return 1, avg_ticket

    def action_compute_customers(self):
        """Botón de cálculo algorítmico (sin IA). Disponible siempre."""
        for record in self:
            n, avg_ticket = record._compute_customer_baseline()
            record.expected_customers = n

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('Clientes calculados'),
                'message': _('%s clientes estimados (ticket medio %.2f €)') % (n, avg_ticket),
                'sticky': False,
                'type':   'success',
            },
        }
