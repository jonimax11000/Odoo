# -*- coding: utf-8 -*-
from odoo import models

class CookastAnomalyRuleStockout(models.Model):
    _name = 'cookast.anomaly.rule.stockout'
    _inherit = 'cookast.anomaly.rule'
    _description = 'Anomaly Rule: Stockout'

    def _check_anomalies(self):
        config = self.env['cookast.anomaly.config'].search([], limit=1)
        if not config or not config.stock_check_active:
            return []

        needs = self.env['cookast.material.need'].search([
            ('stock_status', '=', 'out')
        ])
        
        alerts = []
        for need in needs:
            alerts.append({
                'rule_id': self.id if 'rule_id' in self._fields else False,
                'res_model': 'cookast.material.need',
                'res_id': need.id,
                'message': f"El producto {need.product_name} se ha quedado sin stock (Estado: Sin Stock).",
            })
        return alerts
