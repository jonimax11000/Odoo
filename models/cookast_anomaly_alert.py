# -*- coding: utf-8 -*-
from odoo import models, fields

class CookastAnomalyAlert(models.Model):
    _name = "cookast.anomaly.alert"
    _description = "Cookast Anomaly Alert"

    rule_id = fields.Many2one(
        "cookast.anomaly.rule", 
        string="Rule", 
        required=True, 
        ondelete="cascade"
    )
    model = fields.Char(string="Model", required=True)
    res_id = fields.Integer(string="Resource ID", required=True)
    message = fields.Text(string="Message")
    create_date = fields.Datetime(string="Created On", default=fields.Datetime.now)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("notified", "Notified"),
        ],
        string="Status",
        default="draft",
        required=True,
    )
