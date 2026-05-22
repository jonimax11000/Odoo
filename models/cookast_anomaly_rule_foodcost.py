# -*- coding: utf-8 -*-
from odoo import models

class CookastAnomalyRuleFoodcost(models.Model):
    _name = 'cookast.anomaly.rule.foodcost'
    _inherit = 'cookast.anomaly.rule'
    _description = 'Anomaly Rule: Foodcost Exceeds Limit'

    def _check_anomalies(self):
        config = self.env['cookast.anomaly.config'].search([], limit=1)
        if not config or not config.max_food_cost_pct:
            return []

        forecasts = self.env['cookast.forecast'].search([
            ('food_cost_pct', '>', config.max_food_cost_pct)
        ])
        
        alerts = []
        for fc in forecasts:
            alerts.append({
                'rule_id': self.id if 'rule_id' in self._fields else False,
                'res_model': 'cookast.forecast',
                'res_id': fc.id,
                'message': f"El coste de los alimentos ({fc.food_cost_pct:.2f}%) supera el límite máximo permitido ({config.max_food_cost_pct:.2f}%).",
            })
        return alerts
