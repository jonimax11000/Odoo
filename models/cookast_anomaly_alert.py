# -*- coding: utf-8 -*-
from odoo import models, fields

class CookastAnomalyAlert(models.Model):
    _inherit = 'cookast.anomaly.alert'
    
    notification_sent = fields.Boolean(string="Notification Sent", default=False)
