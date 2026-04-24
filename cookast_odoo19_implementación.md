# Implementación Cookast en Odoo 19
## Contexto del Proyecto
Objetivo: Replicar las funcionalidades del dashboard Cookast (forecast de ventas, planificación de personal y presupuesto de compras) 100% dentro de Odoo 19, eliminando dependencias externas.

## Módulo: cookast_connector

Enfoque: Algoritmos sencillos (medias móviles, reglas de negocio) sin IA compleja.

## Estructura del Módulo
```
    cookast_connector/
    ├── __manifest__.py
    ├── models/
    │   ├── __init__.py
    │   ├── cookast_sync_log.py
    │   ├── cookast_forecast.py
    │   ├── cookast_forecast_config.py
    │   ├── cookast_staffing_need.py
    │   ├── cookast_shift_plan.py
    │   ├── cookast_pos_order.py (herencia)
    │   └── hr_employee.py (herencia)
    ├── views/
    │   ├── cookast_menu.xml
    │   ├── dashboard_views.xml
    │   ├── forecast_config_views.xml
    │   ├── employee_views.xml
    │   ├── shift_plan_views.xml
    │   ├── staffing_need_views.xml
    │   ├── purchase_views.xml
    │   └── ai_placeholder.xml
    ├── security/
    │   └── ir.model.access.csv
    └── data/
        └── (cron.xml - actualmente no usado)

```
## Fases de Implementación

### ✅ Fase 1: Forecast con Medias Móviles (COMPLETADA)
#### Modelos creados:

* cookast.forecast.config - Configuración de factores
* cookast.forecast - Previsión por fecha/local/turno

#### Funcionalidades:

* Cálculo automático de forecast_revenue al crear registros
* Basado en media histórica del mismo día de semana
* Factores configurables: día, mes, tendencia
* Sincronización automática de POS y ventas
* Vistas graph/pivot/list para análisis

### ✅ Fase 2: Planificación de Personal (COMPLETADA)
#### Modelos creados/modificados:

* cookast.staffing.need - Necesidad de personal por turno
* cookast.shift.plan - Añadido campo staffing_need_id
* hr.employee - Campos Cookast (nivel, coste/hora, horas máx, responsable)

#### Funcionalidades:

* Cálculo automático de personas necesarias (total, R, S, J)
* Basado en forecast_revenue / ratio_eur_per_person
* Coste estimado del turno
* Clasificación de tensión (bajo/medio/alto/crítico)
* Generación automática de asignaciones a empleados

### ⏳ Fase 3: Presupuesto de Compras (PENDIENTE)
#### Modelos a crear:

* cookast.purchase.category - Categorías de compra
* cookast.purchase.budget - Presupuesto por categoría y forecast

#### Funcionalidades previstas:

* Cálculo de presupuesto por categoría (% sobre forecast_revenue)
* Estimación de cantidades (kg/uds)
* Tabla resumen por período
* Alertas de picos de compra

### ⏳ Fase 4: Compras Inteligentes (PENDIENTE)
#### Modelos a crear:

* cookast.smart.purchase - Pedidos sugeridos por ingrediente

#### Funcionalidades previstas:

* Explosión de BOMs (si existen) o ratios históricos
* Cálculo de necesidad neta (stock actual - previsión)
* Sugerencia de cantidades a pedir
* Generación de borradores de purchase.order

### ⏳ Fase 5: Mise en Place (PENDIENTE)
#### Funcionalidades previstas:

* Cálculo de cantidades exactas a preparar por día
* Agrupación por tipo de tarea (descongelar, cortar, etc.)
* Vista imprimible para cocina

## Código Implementado
### manifest.py
```python
# -*- coding: utf-8 -*-
{
    'name': 'Cookast Connector',
    'version': '19.0.1.0.0',
    'category': 'Operations/Foodservice',
    'summary': 'Integración con Cookast: Previsiones, Compras y Personal',
    'description': """
        Fase 1: Sincronización de datos Odoo → tablas resumen Cookast.
        - Previsiones de venta por local y turno (POS)
        - Presupuesto vs gasto real de compras por categoría
        - Extensión de empleados con datos de nivel Cookast
        - Planificación de turnos y coste
        - Log de sincronizaciones automáticas
    """,
    'author': 'Apunts Informática',
    'website': 'https://apuntsinformatica.apuntserp.es/',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'point_of_sale',
        'purchase',
        'sale_management',
        'hr',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/cookast_menu.xml',
        'views/dashboard_views.xml',
        'views/forecast_config_views.xml',
        'views/employee_views.xml',
        'views/shift_plan_views.xml',
        'views/staffing_need_views.xml',
        'views/purchase_views.xml',
        'views/ai_placeholder.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
```
### models/init.py
```python
# -*- coding: utf-8 -*-
from . import (
    cookast_sync_log,
    cookast_forecast,
    cookast_forecast_config,
    cookast_staffing_need,
    cookast_pos_order,
    cookast_employee_extended,
    cookast_shift_plan,
)
```
### models/cookast_sync_log.py
```python
# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CookastSyncLog(models.Model):
    _name = 'cookast.sync.log'
    _description = 'Log de sincronizaciones Cookast'
    _order = 'sync_date desc'
    _rec_name = 'sync_date'

    sync_date = fields.Datetime(
        string='Fecha de sincronización',
        default=fields.Datetime.now,
        readonly=True,
    )
    model_synced = fields.Char(string='Modelo sincronizado', readonly=True)
    records_processed = fields.Integer(string='Registros procesados', readonly=True)
    status = fields.Selection(
        [('success', 'Éxito'), ('error', 'Error')],
        string='Estado',
        readonly=True,
    )
    error_message = fields.Text(string='Mensaje de error', readonly=True)

    @api.model
    def _log(self, model_name, records_processed, status, error_message=None):
        """Helper para crear entradas de log desde otros métodos."""
        self.create({
            'model_synced': model_name,
            'records_processed': records_processed,
            'status': status,
            'error_message': error_message,
        })
        if status == 'error':
            _logger.error("Cookast sync error on %s: %s", model_name, error_message)
        else:
            _logger.info("Cookast sync OK on %s: %d records", model_name, records_processed)
```
### models/cookast_forecast_config.py
```python
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class CookastForecastConfig(models.Model):
    _name = 'cookast.forecast.config'
    _description = 'Configuración del Motor de Forecast'
    
    name = fields.Char(
        string='Nombre',
        default='Configuración General',
        required=True,
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
    )
    
    # Factores por día de la semana
    day_factor_mon = fields.Float(string='Lunes', default=0.85)
    day_factor_tue = fields.Float(string='Martes', default=0.80)
    day_factor_wed = fields.Float(string='Miércoles', default=0.85)
    day_factor_thu = fields.Float(string='Jueves', default=0.90)
    day_factor_fri = fields.Float(string='Viernes', default=1.20)
    day_factor_sat = fields.Float(string='Sábado', default=1.50)
    day_factor_sun = fields.Float(string='Domingo', default=1.10)
    
    # Factores por mes (estacionalidad)
    month_factor_jan = fields.Float(string='Enero', default=0.90)
    month_factor_feb = fields.Float(string='Febrero', default=0.95)
    month_factor_mar = fields.Float(string='Marzo', default=1.00)
    month_factor_apr = fields.Float(string='Abril', default=1.05)
    month_factor_may = fields.Float(string='Mayo', default=1.10)
    month_factor_jun = fields.Float(string='Junio', default=1.15)
    month_factor_jul = fields.Float(string='Julio', default=1.05)
    month_factor_aug = fields.Float(string='Agosto', default=0.85)
    month_factor_sep = fields.Float(string='Septiembre', default=1.00)
    month_factor_oct = fields.Float(string='Octubre', default=1.05)
    month_factor_nov = fields.Float(string='Noviembre', default=0.95)
    month_factor_dec = fields.Float(string='Diciembre', default=1.20)
    
    # Factores generales
    trend_factor = fields.Float(string='Tendencia General (YoY)', default=1.00)
    historical_weeks = fields.Integer(string='Semanas históricas', default=8)
    default_base_revenue = fields.Float(string='Ingreso base por defecto (€)', default=500.0)
    
    # Ratio para cálculo de personal
    ratio_eur_per_person = fields.Float(string='Ratio € / persona', default=375.0)
    
    _sql_constraints = [
        ('historical_weeks_positive', 'CHECK(historical_weeks > 0)',
         'El número de semanas históricas debe ser mayor que 0.'),
    ]
    
    @api.constrains('day_factor_mon', 'day_factor_tue', 'day_factor_wed',
                    'day_factor_thu', 'day_factor_fri', 'day_factor_sat', 'day_factor_sun')
    def _check_day_factors_positive(self):
        for rec in self:
            factors = [
                rec.day_factor_mon, rec.day_factor_tue, rec.day_factor_wed,
                rec.day_factor_thu, rec.day_factor_fri, rec.day_factor_sat, rec.day_factor_sun,
            ]
            if any(f <= 0 for f in factors):
                raise ValidationError(("Los factores por día deben ser mayores que 0."))
```
### models/cookast_forecast.py
```python
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

    # Identificación
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

    # Ingresos
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

    # KPIs Compras
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

    # Pedidos POS y Ventas vinculados
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

    _sql_constraints = [
        ('unique_forecast', 'UNIQUE(date, location_id, shift)',
         'Ya existe una previsión para este local, fecha y turno.'),
    ]

    # ── Computes básicos ─────────────────────────────────────────────────────
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

    @api.depends('actual_revenue', 'forecast_revenue')
    def _compute_deviation(self):
        for rec in self:
            rec.deviation = rec.actual_revenue - rec.forecast_revenue

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
            rec.food_cost_pct = (total_pur / rec.actual_revenue * 100) if rec.actual_revenue > 0 else 0.0

    # ── Métodos de Cálculo del Forecast ──────────────────────────────────────
    def _get_day_factor_map(self, config):
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
        """Calcula forecast_revenue basado en histórico del mismo día de semana"""
        config = self.env['cookast.forecast.config'].search([('active', '=', True)], limit=1)
        if not config:
            config = self.env['cookast.forecast.config'].create({'name': 'Configuración Forecast'})
        
        day_factor_map = self._get_day_factor_map(config)
        month_factor_map = self._get_month_factor_map(config)
        
        for record in self:
            if record.forecast_revenue > 0 and not self.env.context.get('force_recompute'):
                continue
            
            weekday = record.date.weekday()
            month = record.date.month
            
            past_forecasts = self.search([
                ('location_id', '=', record.location_id.id),
                ('shift', '=', record.shift),
                ('date', '<', record.date),
                ('actual_revenue', '>', 0),
            ]).filtered(lambda f: f.date.weekday() == weekday)
            
            past_forecasts = past_forecasts.sorted(key=lambda f: f.date, reverse=True)[:config.historical_weeks]
            
            if past_forecasts:
                avg_revenue = sum(past_forecasts.mapped('actual_revenue')) / len(past_forecasts)
            else:
                avg_revenue = config.default_base_revenue
            
            day_factor = day_factor_map.get(weekday, 1.0)
            month_factor = month_factor_map.get(month, 1.0)
            
            record.forecast_revenue = avg_revenue * day_factor * month_factor * config.trend_factor

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records_to_compute = records.filtered(lambda r: r.forecast_revenue == 0)
        if records_to_compute:
            records_to_compute._compute_forecast_revenue()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ['date', 'location_id', 'shift']):
            self._compute_forecast_revenue()
        return res

    def action_recompute_forecast(self):
        self.with_context(force_recompute=True)._compute_forecast_revenue()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Forecast recalculado',
                'message': f'Se ha recalculado la previsión para {len(self)} registros.',
                'type': 'success',
                'sticky': False,
            }
        }

    # ── Sincronización POS ────────────────────────────────────────────────────
    @api.model
    def _sync_pos_orders(self):
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
    
```
### models/cookast_staffing_need.py
```python
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import math


class CookastStaffingNeed(models.Model):
    _name = 'cookast.staffing.need'
    _description = 'Necesidad de personal por turno'
    _rec_name = 'display_name'
    _order = 'forecast_id'
    
    forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Previsión',
        required=True,
        ondelete='cascade',
        index=True,
    )
    display_name = fields.Char(
        string='Descripción',
        compute='_compute_display_name',
        store=True,
    )
    
    date = fields.Date(related='forecast_id.date', store=True)
    shift = fields.Selection(related='forecast_id.shift', store=True)
    location_id = fields.Many2one(related='forecast_id.location_id', store=True)
    forecast_revenue = fields.Monetary(related='forecast_id.forecast_revenue', store=True)
    currency_id = fields.Many2one(related='forecast_id.currency_id')
    
    total_persons = fields.Integer(
        string='Total personas',
        compute='_compute_staffing',
        store=True,
    )
    responsible_qty = fields.Integer(
        string='Responsables (R)',
        compute='_compute_staffing',
        store=True,
    )
    senior_qty = fields.Integer(
        string='Senior (S)',
        compute='_compute_staffing',
        store=True,
    )
    junior_qty = fields.Integer(
        string='Junior (J)',
        compute='_compute_staffing',
        store=True,
    )
    
    estimated_cost = fields.Monetary(
        string='Coste estimado (€)',
        currency_field='currency_id',
        compute='_compute_estimated_cost',
        store=True,
    )
    
    stress_level = fields.Selection([
        ('low', 'Bajo'),
        ('medium', 'Medio'),
        ('high', 'Alto'),
        ('critical', 'Crítico'),
    ], string='Nivel de tensión', compute='_compute_stress_level', store=True)
    
    shift_plan_ids = fields.One2many(
        'cookast.shift.plan',
        'staffing_need_id',
        string='Asignaciones generadas',
    )
    
    _sql_constraints = [
        ('unique_staffing_need', 'UNIQUE(forecast_id)',
         'Ya existe una necesidad de personal para esta previsión.'),
    ]
    
    @api.depends('forecast_id', 'forecast_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"Personal: {rec.forecast_id.display_name or '—'}"
    
    @api.depends('forecast_revenue')
    def _compute_staffing(self):
        config = self.env['cookast.forecast.config'].search([('active', '=', True)], limit=1)
        ratio = config.ratio_eur_per_person if config else 375.0
        
        for rec in self:
            revenue = rec.forecast_revenue or 0.0
            
            if revenue <= 0:
                rec.total_persons = 0
                rec.responsible_qty = 0
                rec.senior_qty = 0
                rec.junior_qty = 0
                continue
            
            total = max(2, min(9, math.ceil(revenue / ratio)))
            rec.total_persons = total
            
            resp = 1 if total >= 2 else 0
            rec.responsible_qty = resp
            
            remaining = total - resp
            senior = math.ceil(remaining * 0.6)
            junior = remaining - senior
            
            rec.senior_qty = senior
            rec.junior_qty = junior
    
    @api.depends('responsible_qty', 'senior_qty', 'junior_qty')
    def _compute_estimated_cost(self):
        avg_cost_resp = 16.50
        avg_cost_senior = 12.50
        avg_cost_junior = 10.50
        hours_per_shift = 5.0
        
        for rec in self:
            cost = (
                rec.responsible_qty * avg_cost_resp * hours_per_shift +
                rec.senior_qty * avg_cost_senior * hours_per_shift +
                rec.junior_qty * avg_cost_junior * hours_per_shift
            )
            rec.estimated_cost = cost
    
    @api.depends('total_persons')
    def _compute_stress_level(self):
        for rec in self:
            total = rec.total_persons
            if total >= 7:
                rec.stress_level = 'critical'
            elif total >= 5:
                rec.stress_level = 'high'
            elif total >= 3:
                rec.stress_level = 'medium'
            else:
                rec.stress_level = 'low'
    
    def action_generate_shift_plans(self):
        self.ensure_one()
        
        employees_resp = self.env['hr.employee'].search([
            ('cookast_level', '=', 'responsible'),
        ])
        employees_senior = self.env['hr.employee'].search([
            ('cookast_level', '=', 'senior'),
        ])
        employees_junior = self.env['hr.employee'].search([
            ('cookast_level', '=', 'junior'),
        ])
        
        self.shift_plan_ids.unlink()
        
        for i in range(self.responsible_qty):
            if i < len(employees_resp):
                self.env['cookast.shift.plan'].create({
                    'forecast_id': self.forecast_id.id,
                    'staffing_need_id': self.id,
                    'employee_id': employees_resp[i].id,
                    'role': 'chef',
                    'planned_hours': 5.0,
                })
        
        for i in range(self.senior_qty):
            if i < len(employees_senior):
                self.env['cookast.shift.plan'].create({
                    'forecast_id': self.forecast_id.id,
                    'staffing_need_id': self.id,
                    'employee_id': employees_senior[i].id,
                    'role': 'waiter',
                    'planned_hours': 5.0,
                })
        
        for i in range(self.junior_qty):
            if i < len(employees_junior):
                self.env['cookast.shift.plan'].create({
                    'forecast_id': self.forecast_id.id,
                    'staffing_need_id': self.id,
                    'employee_id': employees_junior[i].id,
                    'role': 'runner',
                    'planned_hours': 5.0,
                })
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asignaciones generadas'),
            'res_model': 'cookast.shift.plan',
            'view_mode': 'list,form',
            'domain': [('staffing_need_id', '=', self.id)],
            'target': 'current',
        }
```
### models/cookast_shift_plan.py (modificado)
```python
# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CookastShiftPlan(models.Model):
    _name = 'cookast.shift.plan'
    _description = 'Planificación de turno Cookast'
    _rec_name = 'name'
    _order = 'forecast_id, employee_id'

    forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Turno / Previsión',
        required=True,
        ondelete='cascade',
        index=True,
    )
    staffing_need_id = fields.Many2one(
        'cookast.staffing.need',
        string='Necesidad de personal',
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado',
        required=True,
        index=True,
    )

    planned_hours = fields.Float(
        string='Horas planificadas',
        default=4.0,
        digits=(5, 2),
    )
    role = fields.Selection(
        [
            ('chef', 'Chef'),
            ('waiter', 'Camarero'),
            ('runner', 'Runner'),
            ('cashier', 'Cajero'),
        ],
        string='Rol en turno',
        required=True,
    )

    currency_id = fields.Many2one(
        related='employee_id.company_id.currency_id',
        readonly=True,
    )
    shift_cost = fields.Monetary(
        string='Coste turno (€)',
        currency_field='currency_id',
        compute='_compute_shift_cost',
        store=True,
    )

    date = fields.Date(related='forecast_id.date', store=True, string='Fecha')
    shift = fields.Selection(
        related='forecast_id.shift',
        store=True,
        string='Turno',
    )
    location_id = fields.Many2one(
        related='forecast_id.location_id',
        store=True,
        string='Local',
    )

    name = fields.Char(string='Descripción', compute='_compute_name', store=True)

    @api.depends('employee_id', 'forecast_id')
    def _compute_name(self):
        for rec in self:
            emp = rec.employee_id.name or '—'
            forecast = rec.forecast_id.name or '—'
            rec.name = f"{emp} · {forecast}"

    @api.depends('employee_id.cookast_hourly_cost', 'planned_hours')
    def _compute_shift_cost(self):
        for rec in self:
            rec.shift_cost = rec.employee_id.cookast_hourly_cost * rec.planned_hours
```
### models/cookast_pos_order.py
```python
# -*- coding: utf-8 -*-
from odoo import models, fields


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cookast_forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Turno Cookast',
        index=True,
        ondelete='set null',
        copy=False,
    )

```
### models/hr_employee.py
```python
# -*- coding: utf-8 -*-
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    cookast_level = fields.Selection(
        [
            ('responsible', 'Responsable'),
            ('senior', 'Senior'),
            ('junior', 'Junior'),
        ],
        string='Nivel Cookast',
        default='junior',
    )
    cookast_hourly_cost = fields.Monetary(
        string='Coste/hora (€)',
        currency_field='currency_id',
    )
    cookast_max_weekly_hours = fields.Float(
        string='Máx. horas/semana',
        default=40.0,
        digits=(5, 2),
    )
    cookast_manages_shift = fields.Boolean(
        string='Responsable de turno',
        default=False,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )

    shift_plan_ids = fields.One2many(
        'cookast.shift.plan',
        'employee_id',
        string='Turnos planificados',
    )

```
### security/ir.model.access.csv
```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_cookast_sync_log,cookast.sync.log,model_cookast_sync_log,base.group_user,1,1,1,0
access_cookast_forecast,cookast.forecast,model_cookast_forecast,base.group_user,1,1,1,1
access_cookast_shift_plan,cookast.shift.plan,model_cookast_shift_plan,base.group_user,1,1,1,1
access_cookast_forecast_config,cookast.forecast.config,model_cookast_forecast_config,base.group_user,1,1,1,0
access_cookast_staffing_need,cookast.staffing.need,model_cookast_staffing_need,base.group_user,1,1,1,1
```

### Mejora Fase 2: Relación One2one Forecast-Staffing

**Objetivo:** Acceder directamente a la necesidad de personal desde el formulario de forecast.

**Cambios realizados:**
1. Añadido campo `staffing_need_id` (Many2one) en `cookast.forecast`.
2. Método `create()` modificado para crear automáticamente `cookast.staffing.need`.
3. Vista formulario de forecast actualizada con:
   - Enlace directo a la necesidad de personal (form incrustado).
   - Pestaña "Asignaciones de personal" con los `shift_plan_ids`.
   - Botón "Generar asignaciones" en el header.

**Resultado:**
- Al crear un forecast, se crea automáticamente su `staffing_need`.
- El personal necesario se calcula y muestra directamente en el formulario de forecast.
- Se pueden generar asignaciones a empleados con un solo clic.

## Próximos Pasos

* Fase 3: Presupuesto de Compras
* Fase 4: Compras Inteligentes
* Fase 5: Mise en Place

