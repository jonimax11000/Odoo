# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CookastStaffingKpi(models.TransientModel):
    """
    Modelo transitorio que almacena los 4 KPI cards del dashboard de Turnos/Personal.

    Tarjetas:
      1. Personas por turno totales
      2. Coste total del periodo
      3. % coste del personal / ventas
      4. Turnos con tensión (high o critical)
    """

    _name = 'cookast.staffing.kpi'
    _description = 'KPI Cards – Personal'
    _order = 'sequence'

    sequence = fields.Integer(default=10)
    kpi_type = fields.Selection(
        [
            ('persons', 'Total Personas'),
            ('cost', 'Coste Total'),
            ('cost_pct', '% Coste / Ventas'),
            ('tension', 'Turnos con Tensión'),
        ],
        string='Tipo KPI',
        required=True,
    )
    title = fields.Char(string='Título', readonly=True)
    subtitle = fields.Char(string='Subtítulo', readonly=True)
    value = fields.Float(string='Valor', digits=(16, 2), readonly=True)
    value_char = fields.Char(string='Valor (texto)', readonly=True)
    icon = fields.Char(string='Icono FA', readonly=True)
    color_class = fields.Char(string='Clase de color', readonly=True)

    @api.model
    def _compute_kpis(self, domain=None):
        """Calcula los 4 KPIs sobre cookast.staffing.need con el domain dado."""
        StaffingNeed = self.env['cookast.staffing.need']
        needs = StaffingNeed.search(domain or [])

        # KPI 1: Personas totales requeridas
        total_persons = sum(needs.mapped('total_persons'))

        # KPI 2: Coste total del periodo
        total_cost = sum(needs.mapped('estimated_cost'))

        # KPI 3: % coste del personal / ventas
        total_sales = sum(needs.mapped('forecast_revenue'))
        cost_pct = (total_cost / total_sales * 100) if total_sales > 0 else 0.0

        # KPI 4: Turnos con tensión
        tension_count = len(needs.filtered(lambda n: n.stress_level in ('high', 'critical')))

        sym = self.env.company.currency_id.symbol or '€'

        return [
            {
                'sequence': 1,
                'kpi_type': 'persons',
                'title': 'Personas Totales',
                'subtitle': 'Personal necesario en el periodo',
                'value': float(total_persons),
                'value_char': str(int(total_persons)),
                'icon': 'fa-users',
                'color_class': 'kpi-blue',
            },
            {
                'sequence': 2,
                'kpi_type': 'cost',
                'title': 'Coste Total',
                'subtitle': 'Estimación salarial del periodo',
                'value': total_cost,
                'value_char': f'{total_cost:,.2f} {sym}',
                'icon': 'fa-money',
                'color_class': 'kpi-green',
            },
            {
                'sequence': 3,
                'kpi_type': 'cost_pct',
                'title': '% Coste Personal',
                'subtitle': 'Sobre el total de ventas previstas',
                'value': cost_pct,
                'value_char': f'{cost_pct:,.2f} %',
                'icon': 'fa-pie-chart',
                'color_class': 'kpi-orange',  # Podemos reutilizar las clases de CSS
            },
            {
                'sequence': 4,
                'kpi_type': 'tension',
                'title': 'Turnos en Tensión',
                'subtitle': 'Turnos con nivel alto o crítico',
                'value': float(tension_count),
                'value_char': str(int(tension_count)),
                'icon': 'fa-exclamation-triangle',
                'color_class': 'kpi-red',
            },
        ]

    @api.model
    def _refresh_kpis(self, domain=None):
        self.search([]).unlink()
        kpi_list = self._compute_kpis(domain=domain)
        for data in kpi_list:
            self.create(data)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        """Asegura que siempre existan 3 tarjetas KPI al abrir la vista."""
        if not self.search_count([]):
            self._refresh_kpis(domain=[])
        return super().search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)


class CookastStaffingKpiWizard(models.TransientModel):
    """
    Wizard de filtros para el dashboard KPI de Turnos/Personal.
    """
    _name = 'cookast.staffing.kpi.wizard'
    _description = 'Filtros KPI – Personal'

    date_from = fields.Date(
        string='Desde',
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    date_to = fields.Date(
        string='Hasta',
        default=fields.Date.context_today,
    )
    local_ids = fields.Many2many(
        'cookast.local',
        string='Locales',
        help='Deja vacío para incluir todos los locales.',
    )

    def action_apply_filters(self):
        self.ensure_one()
        domain = []
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        if self.local_ids:
            domain.append(('local_id', 'in', self.local_ids.ids))

        self.env['cookast.staffing.kpi']._refresh_kpis(domain=domain)

        return {
            'name': 'Personal – Resumen KPI',
            'type': 'ir.actions.act_window',
            'res_model': 'cookast.staffing.kpi',
            'view_mode': 'kanban',
            'target': 'current',
            'context': {'create': False, 'edit': False},
        }
