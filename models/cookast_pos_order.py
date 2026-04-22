# -*- coding: utf-8 -*-
from odoo import models, fields


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cookast_forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Turno Cookast',
        index=True,
        ondelete='set null',
        copy=False,
    )
