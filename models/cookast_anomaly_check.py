# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class CookastAnomalyCheck(models.TransientModel):
    _name = 'cookast.anomaly.check'
    _description = 'Manual Anomaly Check Wizard'

    def action_run_checks(self):
        total_alerts = self._run_all_checks()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Anomalías revisadas'),
                'message': _('Se han creado %d nuevas alertas de anomalías.') % total_alerts,
                'type': 'success',
            }
        }

    @api.model
    def _run_all_checks(self):
        rule_models = [
            'cookast.anomaly.rule.foodcost',
            'cookast.anomaly.rule.salesdeviation',
            'cookast.anomaly.rule.stockout',
            'cookast.anomaly.rule.stress',
        ]
        
        total_alerts = 0
        AlertModel = self.env['cookast.anomaly.alert']
        
        for model_name in rule_models:
            if model_name in self.env:
                rule_records = self.env[model_name].search([])
                for rule in rule_records:
                    if hasattr(rule, '_check_anomalies'):
                        new_alerts = rule._check_anomalies()
                        if new_alerts:
                            created_alerts = AlertModel.create(new_alerts)
                            for alert in created_alerts:
                                rule._notify_alert(alert)
                            total_alerts += len(new_alerts)
        return total_alerts
