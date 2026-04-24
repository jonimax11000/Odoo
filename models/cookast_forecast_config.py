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
    
    # ── Factores por día de la semana ────────────────────────────────────────
    day_factor_mon = fields.Float(
        string='Lunes',
        default=0.85,
        help='Factor multiplicador para los lunes (1.0 = media histórica)',
    )
    day_factor_tue = fields.Float(
        string='Martes',
        default=0.80,
        help='Factor multiplicador para los martes (1.0 = media histórica)',
    )
    day_factor_wed = fields.Float(
        string='Miércoles',
        default=0.85,
        help='Factor multiplicador para los miércoles (1.0 = media histórica)',
    )
    day_factor_thu = fields.Float(
        string='Jueves',
        default=0.90,
        help='Factor multiplicador para los jueves (1.0 = media histórica)',
    )
    day_factor_fri = fields.Float(
        string='Viernes',
        default=1.20,
        help='Factor multiplicador para los viernes (1.0 = media histórica)',
    )
    day_factor_sat = fields.Float(
        string='Sábado',
        default=1.50,
        help='Factor multiplicador para los sábados (1.0 = media histórica)',
    )
    day_factor_sun = fields.Float(
        string='Domingo',
        default=1.10,
        help='Factor multiplicador para los domingos (1.0 = media histórica)',
    )
    
    # ── Factores por mes (estacionalidad) ─────────────────────────────────────
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
    
    # ── Factores generales ────────────────────────────────────────────────────
    trend_factor = fields.Float(
        string='Tendencia General (YoY)',
        default=1.00,
        help='> 1.0 para crecimiento, < 1.0 para decrecimiento',
    )
    historical_weeks = fields.Integer(
        string='Semanas históricas',
        default=8,
        help='Número de semanas hacia atrás para calcular la media histórica',
    )
    default_base_revenue = fields.Float(
        string='Ingreso base por defecto (€)',
        default=500.0,
        help='Valor usado cuando no hay suficiente histórico para un turno',
    )
    
    # ── Ratio para cálculo de personal ────────────────────────────────────────
    ratio_eur_per_person = fields.Float(
        string='Ratio € / persona',
        default=375.0,
        help='Facturación necesaria para justificar una persona adicional en el turno',
    )
    
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