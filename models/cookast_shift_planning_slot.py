# -*- coding: utf-8 -*-
from odoo import models, fields

class ShiftPlanningSlot(models.Model):
    _inherit = 'shift.planning.slot'

    cookast_forecast_id = fields.Many2one('cookast.forecast', string='Previsión Cookast', ondelete='cascade', index=True)
    cookast_local_id = fields.Many2one('cookast.local', string='Local Cookast', related='cookast_forecast_id.local_id', store=True)
