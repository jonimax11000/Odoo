# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 1200.0  # € – turnos con forecast_revenue > este umbral


class CookastForecastKpi(models.TransientModel):
    """
    Modelo transitorio que almacena los 3 KPI cards del dashboard de previsiones.

    Flujo:
      1. El usuario abre "Previsiones" desde el menú → server action llama
         `_refresh_kpis` con domain vacío → se crean/actualizan 3 registros.
      2. El usuario aplica filtros (local, fecha) y pulsa "Actualizar KPIs"
         → wizard `CookastForecastKpiWizard` recoge los filtros y llama
         `_refresh_kpis` con el domain construido.

    Tarjetas:
      - 'forecast'  → sum(forecast_revenue)
      - 'avg'       → sum diario / nº días únicos
      - 'alerts'    → count(forecast_revenue > 1200 €)
    """

    _name = 'cookast.forecast.kpi'
    _description = 'KPI Cards – Previsiones'
    _order = 'sequence'

    sequence = fields.Integer(default=10)
    kpi_type = fields.Selection(
        [
            ('forecast', 'Venta Prevista'),
            ('avg', 'Media Diaria'),
            ('alerts', 'Alertas'),
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

    # ── Cálculo ───────────────────────────────────────────────────────────────

    @api.model
    def _compute_kpis(self, domain=None):
        """Calcula los 3 KPIs sobre cookast.forecast con el domain dado."""
        Forecast = self.env['cookast.forecast']
        forecasts = Forecast.search(domain or [])

        # KPI 1: Venta prevista total
        total_forecast = sum(forecasts.mapped('forecast_revenue'))

        # KPI 2: Media diaria
        dates_sum = {}
        for f in forecasts:
            dates_sum.setdefault(f.date, 0.0)
            dates_sum[f.date] += f.forecast_revenue
        daily_avg = (sum(dates_sum.values()) / len(dates_sum)) if dates_sum else 0.0

        # KPI 3: Alertas (turnos con previsión > umbral)
        alert_count = len(forecasts.filtered(
            lambda f: f.forecast_revenue > ALERT_THRESHOLD
        ))

        sym = self.env.company.currency_id.symbol or '€'
        thr = int(ALERT_THRESHOLD)

        return [
            {
                'sequence': 1,
                'kpi_type': 'forecast',
                'title': 'Venta Prevista',
                'subtitle': 'Total del período seleccionado',
                'value': total_forecast,
                'value_char': f'{total_forecast:,.2f} {sym}',
                'icon': 'fa-line-chart',
                'color_class': 'kpi-blue',
            },
            {
                'sequence': 2,
                'kpi_type': 'avg',
                'title': 'Media Diaria',
                'subtitle': 'Promedio de ingresos por día',
                'value': daily_avg,
                'value_char': f'{daily_avg:,.2f} {sym}',
                'icon': 'fa-calendar-check-o',
                'color_class': 'kpi-green',
            },
            {
                'sequence': 3,
                'kpi_type': 'alerts',
                'title': 'Alertas',
                'subtitle': f'Turnos con previsión > {thr:,} {sym}',
                'value': float(alert_count),
                'value_char': str(alert_count),
                'icon': 'fa-bell',
                'color_class': 'kpi-orange',
            },
        ]

    @api.model
    def _refresh_kpis(self, domain=None):
        """Elimina los KPIs anteriores y crea los 3 nuevos con el domain dado."""
        self.search([]).unlink()
        kpi_list = self._compute_kpis(domain=domain)
        for data in kpi_list:
            self.create(data)

    # ── Acción que abre el kanban ─────────────────────────────────────────────

    @api.model
    def action_open_dashboard(self, domain=None):
        """Regenera KPIs y devuelve la acción para abrir el kanban."""
        self._refresh_kpis(domain=domain)
        return {
            'name': 'Previsiones – Resumen KPI',
            'type': 'ir.actions.act_window',
            'res_model': 'cookast.forecast.kpi',
            'view_mode': 'kanban,list',
            'target': 'current',
            'context': {'create': False, 'edit': False},
        }


class CookastForecastKpiWizard(models.TransientModel):
    """
    Wizard de filtros para el dashboard KPI.
    Permite al usuario seleccionar locales y rango de fechas y
    regenerar las 3 tarjetas con los datos filtrados.
    """

    _name = 'cookast.forecast.kpi.wizard'
    _description = 'Filtros KPI – Previsiones'

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
        """Construye el domain y regenera las KPI cards."""
        self.ensure_one()
        domain = []
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        if self.local_ids:
            domain.append(('local_id', 'in', self.local_ids.ids))

        self.env['cookast.forecast.kpi']._refresh_kpis(domain=domain)

        # Volver al kanban KPI
        return {
            'name': 'Previsiones – Resumen KPI',
            'type': 'ir.actions.act_window',
            'res_model': 'cookast.forecast.kpi',
            'view_mode': 'kanban,list',
            'target': 'current',
            'context': {'create': False, 'edit': False},
        }
