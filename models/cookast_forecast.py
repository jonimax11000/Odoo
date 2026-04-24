# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

# Horarios de turnos (hora local de la compañía)
SHIFT_LUNCH_START = 13   # 13:00
SHIFT_LUNCH_END = 16     # 16:00
SHIFT_DINNER_START = 20  # 20:00
SHIFT_DINNER_END = 24    # 00:00


class CookastForecast(models.Model):
    _name = 'cookast.forecast'
    _description = 'Previsión de demanda por turno'
    _rec_name = 'name'
    _order = 'date desc, shift'

    # ── Identificación ────────────────────────────────────────────────────────
    name = fields.Char(string='Referencia', compute='_compute_name', store=True)
    date = fields.Date(string='Fecha', required=True)
    location_id = fields.Many2one(
        'stock.location',
        string='Local',
        domain=[('usage', '=', 'internal')],
        required=True,
    )
    shift = fields.Selection(
        [('lunch', 'Comida'), ('dinner', 'Cena')],
        string='Turno',
        required=True,
    )

    # ── Ingresos ──────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    forecast_revenue = fields.Monetary(
        string='Previsión (€)',
        currency_field='currency_id',
    )
    actual_revenue = fields.Monetary(
        string='Real POS (€)',
        currency_field='currency_id',
        compute='_compute_actual_revenue',
        store=True,
        readonly=True,
    )

    deviation = fields.Monetary(
        string='Desviación (Real - Previsión)',
        currency_field='currency_id',
        compute='_compute_deviation',
        store=True,
    )

    @api.depends('actual_revenue', 'forecast_revenue')
    def _compute_deviation(self):
        for rec in self:
            rec.deviation = rec.actual_revenue - rec.forecast_revenue
    
    # ── KPIs Compras ──────────────────────────────────────────────────────────
    total_purchases = fields.Monetary(
        string='Compras Confirmadas (€)',
        currency_field='currency_id',
        compute='_compute_purchase_stats',
        store=True,
    )
    food_cost_pct = fields.Float(
        string='Food Cost (%)',
        compute='_compute_purchase_stats',
        store=True,
        group_operator='avg',
    )

    # ── Pedidos POS y Ventas vinculados ──────────────────────────────────────────
    pos_order_ids = fields.One2many(
        'pos.order',
        'cookast_forecast_id',
        string='Pedidos POS',
    )
    sale_order_ids = fields.One2many(
        'sale.order',
        'cookast_forecast_id',
        string='Pedidos de Venta',
    )

    # ── Relación One2one con Staffing Need ────────────────────────────────────
    staffing_need_id = fields.Many2one(
        'cookast.staffing.need',
        string='Necesidad de personal',
        ondelete='restrict',
        readonly=False,
    )

    shift_plan_ids = fields.One2many(
        'cookast.shift.plan',
        compute='_compute_shift_plan_ids',
        string='Asignaciones de personal',
    )
    
    @api.depends('staffing_need_id.shift_plan_ids')
    def _compute_shift_plan_ids(self):
        for rec in self:
            if rec.staffing_need_id:
                rec.shift_plan_ids = rec.staffing_need_id.shift_plan_ids
            else:
                rec.shift_plan_ids = False

    # ── Constraints ──────────────────────────────────────────────────────────
    _sql_constraints = [
        ('unique_forecast', 'UNIQUE(date, location_id, shift)',
         'Ya existe una previsión para este local, fecha y turno.'),
    ]

    @api.constrains('date', 'location_id', 'shift')
    def _check_unique_forecast(self):
        for rec in self:
            duplicate = self.search([
                ('date', '=', rec.date),
                ('location_id', '=', rec.location_id.id),
                ('shift', '=', rec.shift),
                ('id', '!=', rec.id),
            ])
            if duplicate:
                raise ValidationError((
                    'Ya existe una previsión para este local, fecha y turno.'
                ))

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('date', 'location_id', 'shift')
    def _compute_name(self):
        shift_labels = dict(self._fields['shift'].selection)
        for rec in self:
            loc = rec.location_id.name or '—'
            shift = shift_labels.get(rec.shift, rec.shift or '—')
            rec.name = f"{rec.date} · {loc} · {shift}"

    @api.depends('pos_order_ids.amount_total', 'pos_order_ids.state', 
                 'sale_order_ids.amount_total', 'sale_order_ids.state')
    def _compute_actual_revenue(self):
        for rec in self:
            confirmed_pos = rec.pos_order_ids.filtered(
                lambda o: o.state in ('paid', 'done', 'invoiced')
            )
            confirmed_sales = rec.sale_order_ids.filtered(
                lambda o: o.state in ('sale', 'done')
            )
            rec.actual_revenue = sum(confirmed_pos.mapped('amount_total')) + \
                                 sum(confirmed_sales.mapped('amount_total'))

    @api.depends('actual_revenue')
    def _compute_purchase_stats(self):
        for rec in self:
            total_pur = 0.0
            if rec.date:
                start_dt = fields.Datetime.to_datetime(rec.date)
                end_dt = start_dt.replace(hour=23, minute=59, second=59)
                
                purchases = self.env['purchase.order'].search([
                    ('state', 'in', ['purchase', 'done']),
                    ('date_order', '>=', start_dt),
                    ('date_order', '<=', end_dt),
                ])
                total_pur = sum(purchases.mapped('amount_total'))
            
            rec.total_purchases = total_pur
            if rec.actual_revenue > 0:
                rec.food_cost_pct = (total_pur / rec.actual_revenue) * 100
            else:
                rec.food_cost_pct = 0.0

    # ── Métodos de Cálculo del Forecast ──────────────────────────────────────
    def _get_day_factor_map(self, config):
        """Devuelve un diccionario con los factores por día de la semana."""
        return {
            0: config.day_factor_mon,
            1: config.day_factor_tue,
            2: config.day_factor_wed,
            3: config.day_factor_thu,
            4: config.day_factor_fri,
            5: config.day_factor_sat,
            6: config.day_factor_sun,
        }
    
    def _get_month_factor_map(self, config):
        """Devuelve un diccionario con los factores por mes."""
        return {
            1: config.month_factor_jan,
            2: config.month_factor_feb,
            3: config.month_factor_mar,
            4: config.month_factor_apr,
            5: config.month_factor_may,
            6: config.month_factor_jun,
            7: config.month_factor_jul,
            8: config.month_factor_aug,
            9: config.month_factor_sep,
            10: config.month_factor_oct,
            11: config.month_factor_nov,
            12: config.month_factor_dec,
        }
    
    def _compute_forecast_revenue(self):
        """
        Calcula forecast_revenue basado en:
        - Media de actual_revenue de los últimos N mismos días de la semana
        - Multiplicado por factor día, factor mes y tendencia general
        """
        config = self.env['cookast.forecast.config'].search([('active', '=', True)], limit=1)
        if not config:
            config = self.env['cookast.forecast.config'].create({'name': 'Configuración Forecast'})
        
        day_factor_map = self._get_day_factor_map(config)
        month_factor_map = self._get_month_factor_map(config)
        
        for record in self:
            # Si ya tiene un valor manual (distinto de 0), no lo sobrescribimos
            if record.forecast_revenue > 0 and not self.env.context.get('force_recompute'):
                continue
            
            weekday = record.date.weekday()
            month = record.date.month
            
            # Buscar histórico del mismo día de semana, mismo local y turno
            past_forecasts = self.search([
                ('location_id', '=', record.location_id.id),
                ('shift', '=', record.shift),
                ('date', '<', record.date),
                ('actual_revenue', '>', 0),
            ]).filtered(lambda f: f.date.weekday() == weekday)
            
            # Limitar al número de semanas configurado
            past_forecasts = past_forecasts.sorted(key=lambda f: f.date, reverse=True)[:config.historical_weeks]
            
            if past_forecasts:
                avg_revenue = sum(past_forecasts.mapped('actual_revenue')) / len(past_forecasts)
            else:
                # Si no hay histórico, usar valor base
                avg_revenue = config.default_base_revenue
            
            # Aplicar factores
            day_factor = day_factor_map.get(weekday, 1.0)
            month_factor = month_factor_map.get(month, 1.0)
            
            record.forecast_revenue = avg_revenue * day_factor * month_factor * config.trend_factor

    # ── Creación y Escritura ──────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        
        # Recalcular forecast si es necesario
        records_to_compute = records.filtered(lambda r: r.forecast_revenue == 0)
        if records_to_compute:
            records_to_compute._compute_forecast_revenue()
        
        # Crear staffing_need automáticamente para cada forecast nuevo
        for record in records:
            if not record.staffing_need_id:
                staffing = self.env['cookast.staffing.need'].create({
                    'forecast_id': record.id,
                })
                record.staffing_need_id = staffing.id
        
        return records
    
    def write(self, vals):
        """Al modificar fecha/local/turno, recalcular forecast si es necesario."""
        res = super().write(vals)
        if any(f in vals for f in ['date', 'location_id', 'shift']):
            self._compute_forecast_revenue()
        return res
    
    # ── Acciones de Botón ─────────────────────────────────────────────────────
    def action_recompute_forecast(self):
        """Botón para forzar el recálculo del forecast."""
        self.with_context(force_recompute=True)._compute_forecast_revenue()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Forecast recalculado'),
                'message': _('Se ha recalculado la previsión para %s registros.') % len(self),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_recompute_all_forecasts(self):
        """Acción desde menú para recalcular todos los forecasts pendientes."""
        forecasts = self.search([('forecast_revenue', '=', 0)])
        if forecasts:
            forecasts._compute_forecast_revenue()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Forecast recalculado'),
                'message': _('Se ha recalculado la previsión para %s registros.') % len(forecasts),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_generate_shift_plans(self):
        """Delega la generación de asignaciones al staffing_need asociado."""
        self.ensure_one()
        
        if not self.staffing_need_id:
            staffing = self.env['cookast.staffing.need'].create({
                'forecast_id': self.id,
            })
            self.staffing_need_id = staffing.id
        
        # Generar las asignaciones
        self.staffing_need_id.action_generate_shift_plans()
        
        # Abrir el formulario de staffing_need para ver las asignaciones
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cookast.staffing.need',
            'res_id': self.staffing_need_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Sincronización POS ────────────────────────────────────────────────────
    @api.model
    def _sync_pos_orders(self):
        """
        CRON: Agrupa pos.order por fecha, local y turno y los vincula
        al cookast.forecast correspondiente (creándolo si no existe).
        """
        Log = self.env['cookast.sync.log']
        count = 0
        try:
            orders = self.env['pos.order'].search([
                ('state', 'in', ['paid', 'done', 'invoiced']),
                ('cookast_forecast_id', '=', False),
            ])
            for order in orders:
                if not order.date_order:
                    continue
                order_dt = fields.Datetime.context_timestamp(order, order.date_order)
                hour = order_dt.hour
                if SHIFT_LUNCH_START <= hour < SHIFT_LUNCH_END:
                    shift = 'lunch'
                elif SHIFT_DINNER_START <= hour < SHIFT_DINNER_END:
                    shift = 'dinner'
                else:
                    continue

                order_date = order_dt.date()
                location = order.config_id.picking_type_id.default_location_src_id

                if not location:
                    continue

                forecast = self.search([
                    ('date', '=', order_date),
                    ('location_id', '=', location.id),
                    ('shift', '=', shift),
                ], limit=1)

                if not forecast:
                    forecast = self.create({
                        'date': order_date,
                        'location_id': location.id,
                        'shift': shift,
                        'forecast_revenue': 0.0,
                    })

                order.cookast_forecast_id = forecast
                count += 1

            Log._log('cookast.forecast', count, 'success')
            self._sync_sale_orders()
            
        except Exception as e:
            Log._log('cookast.forecast', count, 'error', str(e))
            raise

    @api.model
    def _sync_sale_orders(self):
        """Sincroniza sale.order con cookast.forecast"""
        Log = self.env['cookast.sync.log']
        count = 0
        try:
            orders = self.env['sale.order'].search([
                ('state', 'in', ['sale', 'done']),
                ('cookast_forecast_id', '=', False),
            ])
            for order in orders:
                if not order.date_order:
                    continue
                order_dt = fields.Datetime.context_timestamp(order, order.date_order)
                hour = order_dt.hour
                if SHIFT_LUNCH_START <= hour < SHIFT_LUNCH_END:
                    shift = 'lunch'
                elif SHIFT_DINNER_START <= hour < SHIFT_DINNER_END:
                    shift = 'dinner'
                else:
                    continue

                order_date = order_dt.date()
                location = order.warehouse_id.lot_stock_id

                if not location:
                    continue

                forecast = self.search([
                    ('date', '=', order_date),
                    ('location_id', '=', location.id),
                    ('shift', '=', shift),
                ], limit=1)

                if not forecast:
                    forecast = self.create({
                        'date': order_date,
                        'location_id': location.id,
                        'shift': shift,
                        'forecast_revenue': 0.0,
                    })

                order.cookast_forecast_id = forecast
                count += 1

            Log._log('cookast.forecast_sales', count, 'success')
        except Exception as e:
            Log._log('cookast.forecast_sales', count, 'error', str(e))
            raise


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cookast_forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Previsión Turno Cookast',
        ondelete='set null',
        index=True,
    )