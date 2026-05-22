# -*- coding: utf-8 -*-
from odoo import models

class CookastAnomalyRuleSalesDeviation(models.Model):
    _name = 'cookast.anomaly.rule.salesdeviation'
    _inherit = 'cookast.anomaly.rule'
    _description = 'Anomaly Rule: Sales Deviation'

    def _check_anomalies(self):
        config = self.env['cookast.anomaly.config'].search([], limit=1)
        if not config or not config.max_sales_deviation_pct:
            return []

        # search forecasts where actual_revenue > 0, deviation < 0, and abs(deviation)/forecast_revenue*100 > abs(config.max_sales_deviation_pct)
        # Odoo domain can't easily express this complex formula, so we filter in Python
        forecasts = self.env['cookast.forecast'].search([
            ('actual_revenue', '>', 0),
            ('forecast_revenue', '>', 0)
        ])
        
        alerts = []
        max_dev = abs(config.max_sales_deviation_pct)
        for fc in forecasts:
            # Assume deviation is something like actual_revenue - forecast_revenue
            # The prompt asks: deviation < 0, abs(deviation)/forecast_revenue*100 > max_dev
            deviation = fc.actual_revenue - fc.forecast_revenue
            if deviation < 0:
                dev_pct = (abs(deviation) / fc.forecast_revenue) * 100
                if dev_pct > max_dev:
                    alerts.append({
                        'rule_id': self.id if 'rule_id' in self._fields else False,
                        'res_model': 'cookast.forecast',
                        'res_id': fc.id,
                        'message': f"Desviación de ventas negativa ({dev_pct:.2f}%) supera el límite máximo permitido ({max_dev:.2f}%).",
                    })
        return alerts
