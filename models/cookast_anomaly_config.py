# -*- coding: utf-8 -*-
from odoo import models, fields

class CookastAnomalyConfig(models.Model):
    _name = "cookast.anomaly.config"
    _description = "Cookast Anomaly Detection Configuration"

    company_id = fields.Many2one(
        "res.company", 
        string="Company", 
        required=True, 
        default=lambda self: self.env.company
    )
    max_food_cost_pct = fields.Float(string="Max Food Cost (%)", default=35.0)
    max_sales_deviation_pct = fields.Float(string="Max Sales Deviation (%)", default=-30.0)
    stress_levels_to_alert = fields.Char(string="Stress Levels to Alert", default="high,critical")
    stock_check_active = fields.Boolean(string="Stock Check Active", default=True)

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)', 'Anomaly configuration must be unique per company!')
    ]
