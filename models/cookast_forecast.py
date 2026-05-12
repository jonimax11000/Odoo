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
    local_id = fields.Many2one(
        'cookast.local',
        string='Local',
        required=True,
        index=True,
        ondelete='restrict',
        help='Local/sucursal al que pertenece esta previsión.',
    )
    # location_id se deriva del almacén del local. Se mantiene como stored
    # para compatibilidad con la SQL view de cookast.material.need y filtros.
    location_id = fields.Many2one(
        'stock.location',
        string='Ubicación de stock',
        related='local_id.location_id',
        store=True,
        readonly=True,
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
        aggregator='avg',
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

    # ── Relación con necesidades de personal y planificador ──────────────────
    staffing_need_id = fields.Many2one(
        'cookast.staffing.need',
        string='Necesidad de personal',
        readonly=True,
    )
    planning_slot_ids = fields.One2many(
        'shift.planning.slot',
        'cookast_forecast_id',
        string='Turnos Planificados'
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
        ('unique_forecast', 'UNIQUE(date, local_id, shift)',
         'Ya existe una previsión para este local, fecha y turno.'),
    ]

    @api.constrains('date', 'local_id', 'shift')
    def _check_unique_forecast(self):
        for rec in self:
            duplicate = self.search([
                ('date', '=', rec.date),
                ('local_id', '=', rec.local_id.id),
                ('shift', '=', rec.shift),
                ('id', '!=', rec.id),
            ])
            if duplicate:
                raise ValidationError((
                    'Ya existe una previsión para este local, fecha y turno.'
                ))

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('date', 'local_id', 'shift')
    def _compute_name(self):
        shift_labels = dict(self._fields['shift'].selection)
        for rec in self:
            loc = rec.local_id.name or '—'
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

    @api.depends('actual_revenue', 'date', 'local_id', 'shift')
    def _compute_purchase_stats(self):
        for rec in self:
            total_pur = 0.0
            if rec.date:
                start_dt = fields.Datetime.to_datetime(rec.date)
                end_dt = start_dt.replace(hour=23, minute=59, second=59)

                domain = [
                    ('state', 'in', ['purchase', 'done']),
                    ('date_order', '>=', start_dt),
                    ('date_order', '<=', end_dt),
                ]

                # Filtrar por almacén del local si está configurado
                if rec.local_id and rec.local_id.warehouse_id:
                    domain.append(
                        ('picking_type_id.warehouse_id', '=', rec.local_id.warehouse_id.id)
                    )

                purchases = self.env['purchase.order'].search(domain)
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
        - Ajustado por factor meteorológico (si cookast_weather está instalado)
        """
        config = self.env['cookast.forecast.config'].search([('active', '=', True)], limit=1)
        if not config:
            config = self.env['cookast.forecast.config'].create({'name': 'Configuración Forecast'})

        day_factor_map = self._get_day_factor_map(config)
        month_factor_map = self._get_month_factor_map(config)

        # Detectar si el módulo cookast_weather está instalado (modelo registrado)
        has_weather = 'cookast.weather.forecast' in self.env

        for record in self:
            # Si ya tiene un valor manual y no se fuerza recálculo, no lo sobrescribimos
            if record.forecast_revenue > 0 and not self.env.context.get('force_recompute'):
                continue

            weekday = record.date.weekday()
            month = record.date.month

            # Buscar histórico del mismo día de semana, mismo local y turno
            past_forecasts = self.search([
                ('local_id', '=', record.local_id.id),
                ('shift', '=', record.shift),
                ('date', '<', record.date),
                ('actual_revenue', '>', 0),
            ]).filtered(lambda f: f.date.weekday() == weekday)

            # Limitar al número de semanas configurado
            past_forecasts = past_forecasts.sorted(key=lambda f: f.date, reverse=True)[:config.historical_weeks]

            if past_forecasts:
                avg_revenue = sum(past_forecasts.mapped('actual_revenue')) / len(past_forecasts)
            else:
                avg_revenue = config.default_base_revenue

            # Aplicar factores base
            day_factor = day_factor_map.get(weekday, 1.0)
            month_factor = month_factor_map.get(month, 1.0)
            base_forecast = avg_revenue * day_factor * month_factor * config.trend_factor

            # ── Factor meteorológico (si el módulo cookast_weather está instalado) ──
            weather_multiplier = 1.0
            weather_info = ""
            if has_weather:
                WeatherForecast = self.env['cookast.weather.forecast']
                weather = WeatherForecast.search([
                    ('local_id', '=', record.local_id.id),
                    ('date', '=', record.date),
                ], limit=1)

                if weather and weather.weather_factor:
                    weather_multiplier = 1.0 + (weather.weather_factor / 100.0)
                    weather_info = (
                        f" | clima: {weather.weather_condition}"
                        f" ({weather.temp_min:.0f}–{weather.temp_max:.0f}°C,"
                        f" lluvia: {weather.rain_mm:.1f}mm)"
                        f" → ajuste: {weather.weather_factor:+.1f}%"
                    )
                elif not weather:
                    _logger.debug(
                        "Sin previsión meteorológica para %s el %s. Se usa factor neutro (1.0).",
                        record.local_id.name, record.date
                    )

            record.forecast_revenue = base_forecast * weather_multiplier

            _logger.info(
                "Forecast %s | %s | %s | base: %.0f€ × día:%.2f × mes:%.2f × tend:%.2f × clima:%.3f = %.0f€%s",
                record.date, record.local_id.name, record.shift,
                avg_revenue, day_factor, month_factor, config.trend_factor,
                weather_multiplier, record.forecast_revenue, weather_info
            )

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
        """Al modificar fecha/local/turno/forecast_revenue, recalcular dependientes."""
        res = super().write(vals)
        if any(f in vals for f in ['date', 'location_id', 'shift', 'forecast_revenue']):
            if 'forecast_revenue' in vals:
                # Forzar recálculo del staffing_need asociado
                for record in self:
                    if record.staffing_need_id:
                        record.staffing_need_id._compute_staffing()
            else:
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

    def action_view_planning_slots(self):
        self.ensure_one()
        import pytz
        from datetime import datetime, time
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_of_day = user_tz.localize(datetime.combine(self.date, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end_of_day = user_tz.localize(datetime.combine(self.date, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)

        action = self.env['ir.actions.act_window']._for_xml_id('shift_planner_community.action_shift_planning_slot')
        action['domain'] = [
            ('start_datetime', '>=', start_of_day),
            ('start_datetime', '<=', end_of_day),
            ('cookast_local_id', '=', self.local_id.id)
        ]
        action['context'] = {
            'default_cookast_forecast_id': self.id,
        }
        return action

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

                # Obtener el local desde la config del TPV
                local = None
                if order.config_id.cookast_local_id:
                    local = order.config_id.cookast_local_id
                else:
                    # Fallback: buscar por ubicación si el TPV no tiene local asignado
                    src_location = order.config_id.picking_type_id.default_location_src_id
                    if src_location:
                        local = self.env['cookast.local'].search(
                            [('location_id', '=', src_location.id)], limit=1
                        )

                if not local:
                    continue

                forecast = self.search([
                    ('date', '=', order_date),
                    ('local_id', '=', local.id),
                    ('shift', '=', shift),
                ], limit=1)

                if not forecast:
                    forecast = self.create({
                        'date': order_date,
                        'local_id': local.id,
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
                # Para ventas: buscar el local por el almacén del pedido
                local = self.env['cookast.local'].search(
                    [('warehouse_id', '=', order.warehouse_id.id)], limit=1
                )

                if not local:
                    continue

                forecast = self.search([
                    ('date', '=', order_date),
                    ('local_id', '=', local.id),
                    ('shift', '=', shift),
                ], limit=1)

                if not forecast:
                    forecast = self.create({
                        'date': order_date,
                        'local_id': local.id,
                        'shift': shift,
                        'forecast_revenue': 0.0,
                    })

                order.cookast_forecast_id = forecast
                count += 1

            Log._log('cookast.forecast_sales', count, 'success')
        except Exception as e:
            Log._log('cookast.forecast_sales', count, 'error', str(e))
            raise

    def action_apply_weather_to_all_forecasts(self):
        """
        Aplica el factor meteorológico a todos los forecasts futuros que aún
        no tengan previsión calculada, o fuerza el recálculo de todos.
        Útil tras instalar cookast_weather o tras un cambio en los datos meteorológicos.
        """
        if 'cookast.weather.forecast' not in self.env:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Módulo no disponible'),
                    'message': _('El módulo cookast_weather no está instalado.'),
                    'type': 'warning',
                }
            }

        # Buscar forecasts desde hoy en adelante
        today = fields.Date.context_today(self)
        forecasts = self.search([
            ('date', '>=', today),
        ])

        if forecasts:
            forecasts.with_context(force_recompute=True)._compute_forecast_revenue()
            # También recalcular staffing needs asociados
            staffing_needs = self.env['cookast.staffing.need'].search([
                ('forecast_id', 'in', forecasts.ids),
            ])
            if staffing_needs:
                staffing_needs._compute_staffing()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Ajuste meteorológico aplicado'),
                'message': _('Se han recalculado %d previsiones con los datos meteorológicos actuales.') % len(forecasts),
                'type': 'success',
            }
        }
            


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cookast_forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Previsión Turno Cookast',
        ondelete='set null',
        index=True,
    )


class PurchaseOrder(models.Model):
    """
    Hook en purchase.order:
    Al confirmar, cancelar o modificar el importe de una compra,
    invalida los forecasts afectados para que recalculen
    total_purchases y food_cost_pct.
    """
    _inherit = 'purchase.order'

    cookast_local_id = fields.Many2one(
        'cookast.local',
        string='Local Cookast',
        compute='_compute_cookast_local_id',
        store=True,
        index=True,
        help='Local calculado a partir del almacén del tipo de operación.',
    )

    @api.depends('picking_type_id', 'picking_type_id.warehouse_id')
    def _compute_cookast_local_id(self):
        Local = self.env['cookast.local']
        for po in self:
            if po.picking_type_id and po.picking_type_id.warehouse_id:
                local = Local.search(
                    [('warehouse_id', '=', po.picking_type_id.warehouse_id.id)], limit=1
                )
                po.cookast_local_id = local.id if local else False
            else:
                po.cookast_local_id = False

    def _invalidate_cookast_forecasts(self):
        """Encuentra y recalcula los forecasts del día/almacén de estas compras."""
        Forecast = self.env['cookast.forecast']
        for po in self:
            if not po.date_order:
                continue
            order_date = fields.Date.to_date(po.date_order)
            warehouse = po.picking_type_id.warehouse_id if po.picking_type_id else None

            domain = [('date', '=', order_date)]
            if warehouse:
                domain.append(('local_id.warehouse_id', '=', warehouse.id))

            forecasts = Forecast.search(domain)
            if forecasts:
                # Forzar recálculo de los campos de compra en esos forecasts
                forecasts._compute_purchase_stats()
                # Guardar los nuevos valores en BD
                for f in forecasts:
                    f.write({
                        'total_purchases': f.total_purchases,
                        'food_cost_pct': f.food_cost_pct,
                    })

    def button_confirm(self):
        res = super().button_confirm()
        self._invalidate_cookast_forecasts()
        return res

    def button_cancel(self):
        res = super().button_cancel()
        self._invalidate_cookast_forecasts()
        return res

    def write(self, vals):
        res = super().write(vals)
        if 'amount_total' in vals or 'state' in vals:
            self._invalidate_cookast_forecasts()
        return res