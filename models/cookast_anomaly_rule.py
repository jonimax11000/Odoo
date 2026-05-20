# -*- coding: utf-8 -*-
from odoo import models, fields

class CookastAnomalyRule(models.AbstractModel):
    _name = "cookast.anomaly.rule"
    _description = "Cookast Anomaly Rule"

    name = fields.Char(string="Rule Name", required=True)
    active = fields.Boolean(string="Active", default=True)
    rule_type = fields.Selection(
        [
            ("foodcost", "Food Cost"),
            ("salesdeviation", "Sales Deviation"),
            ("stockout", "Stockout"),
            ("stress", "Stress Level"),
        ],
        string="Rule Type",
        required=True,
    )

    def _check_anomalies(self):
        """
        Check for anomalies. Must be implemented by subclasses.
        Returns a list of dicts: [{'model': '...', 'res_id': ..., 'message': '...'}]
        """
        raise NotImplementedError("Subclasses must implement _check_anomalies method")
