# -*- coding: utf-8 -*-
from odoo import models, fields, api
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

    # ── Constraints ──────────────────────────────────────────────────────────
    _sql_constraints = [
        ('unique_forecast', 'UNIQUE(date, location_id, shift)',
         'Ya existe una previsión para este local, fecha y turno.'),
    ]

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('date', 'location_id', 'shift')
    def _compute_name(self):
        shift_labels = dict(self._fields['shift'].selection)
        for rec in self:
            loc = rec.location_id.name or '—'
            shift = shift_labels.get(rec.shift, rec.shift or '—')
            rec.name = f"{rec.date} · {loc} · {shift}"

    @api.depends('pos_order_ids.amount_total', 'pos_order_ids.state', 'sale_order_ids.amount_total', 'sale_order_ids.state')
    def _compute_actual_revenue(self):
        for rec in self:
            confirmed_pos = rec.pos_order_ids.filtered(
                lambda o: o.state in ('paid', 'done', 'invoiced')
            )
            confirmed_sales = rec.sale_order_ids.filtered(
                lambda o: o.state in ('sale', 'done')
            )
            rec.actual_revenue = sum(confirmed_pos.mapped('amount_total')) + sum(confirmed_sales.mapped('amount_total'))

    @api.depends('actual_revenue')
    def _compute_purchase_stats(self):
        for rec in self:
            total_pur = 0.0
            if rec.date:
                start_dt = fields.Datetime.to_datetime(rec.date)
                end_dt = start_dt.replace(hour=23, minute=59, second=59)
                
                # Fetch confirmed purchase orders for this day
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

    # ── Sincronización POS ────────────────────────────────────────────────────
    @api.model
    def _sync_pos_orders(self):
        """
        CRON: Agrupa pos.order por fecha, local y turno y los vincula
        al cookast.forecast correspondiente (creándolo si no existe).
        Turno Comida: 13:00 – 16:00 | Turno Cena: 20:00 – 00:00
        """
        Log = self.env['cookast.sync.log']
        count = 0
        try:
            # Órdenes confirmadas sin previsión asignada
            orders = self.env['pos.order'].search([
                ('state', 'in', ['paid', 'done', 'invoiced']),
                ('cookast_forecast_id', '=', False),
            ])
            for order in orders:
                if not order.date_order:
                    continue
                # Convertir a hora local de la compañía
                order_dt = fields.Datetime.context_timestamp(order, order.date_order)
                hour = order_dt.hour
                if SHIFT_LUNCH_START <= hour < SHIFT_LUNCH_END:
                    shift = 'lunch'
                elif SHIFT_DINNER_START <= hour < SHIFT_DINNER_END:
                    shift = 'dinner'
                else:
                    continue  # Fuera de turno, ignorar

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
            
            # Encadenar sincronización de pedidos de venta (sale.order)
            self._sync_sale_orders()
            
        except Exception as e:
            Log._log('cookast.forecast', count, 'error', str(e))
            raise

    @api.model
    def _sync_sale_orders(self):
        """
        Agrupa sale.order por fecha, local y turno y los vincula
        al cookast.forecast correspondiente (creándolo si no existe).
        Turno Comida: 13:00 – 16:00 | Turno Cena: 20:00 – 00:00
        """
        Log = self.env['cookast.sync.log']
        count = 0
        try:
            # Órdenes de venta confirmadas sin previsión asignada
            orders = self.env['sale.order'].search([
                ('state', 'in', ['sale', 'done']),
                ('cookast_forecast_id', '=', False),
            ])
            for order in orders:
                if not order.date_order:
                    continue
                # Convertir a hora local de la compañía
                order_dt = fields.Datetime.context_timestamp(order, order.date_order)
                hour = order_dt.hour
                if SHIFT_LUNCH_START <= hour < SHIFT_LUNCH_END:
                    shift = 'lunch'
                elif SHIFT_DINNER_START <= hour < SHIFT_DINNER_END:
                    shift = 'dinner'
                else:
                    continue  # Fuera de turno, ignorar

                order_date = order_dt.date()
                
                # Para sale.order, la ubicación estándar es warehouse_id.lot_stock_id
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
