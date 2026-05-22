# -*- coding: utf-8 -*-
from odoo import models

class CookastAnomalyRuleStress(models.Model):
    _name = 'cookast.anomaly.rule.stress'
    _inherit = 'cookast.anomaly.rule'
    _description = 'Anomaly Rule: Staffing Stress'

    def _check_anomalies(self):
        config = self.env['cookast.anomaly.config'].search([], limit=1)
        if not config or not config.stress_levels_to_alert:
            return []

        # Assuming stress_levels_to_alert is a comma-separated string
        levels = [level.strip() for level in config.stress_levels_to_alert.split(',') if level.strip()]
        if not levels:
            return []

        needs = self.env['cookast.staffing.need'].search([
            ('stress_level', 'in', levels)
        ])
        
        alerts = []
        for need in needs:
            alerts.append({
                'rule_id': self.id if 'rule_id' in self._fields else False,
                'res_model': 'cookast.staffing.need',
                'res_id': need.id,
                'message': f"Alerta de estrés de personal: Nivel '{need.stress_level}' en {need.local_id.name if need.local_id else 'el local'}.",
            })
        return alerts
