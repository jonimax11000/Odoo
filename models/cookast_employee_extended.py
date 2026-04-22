# -*- coding: utf-8 -*-
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ── Datos Cookast ─────────────────────────────────────────────────────────
    cookast_level = fields.Selection(
        [
            ('responsible', 'Responsable'),
            ('senior', 'Senior'),
            ('junior', 'Junior'),
        ],
        string='Nivel Cookast',
        default='junior',
    )
    cookast_hourly_cost = fields.Monetary(
        string='Coste/hora (€)',
        currency_field='currency_id',
    )
    cookast_max_weekly_hours = fields.Float(
        string='Máx. horas/semana',
        default=40.0,
        digits=(5, 2),
    )
    cookast_manages_shift = fields.Boolean(
        string='Responsable de turno',
        default=False,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )

    # ── Relación con planificaciones ──────────────────────────────────────────
    shift_plan_ids = fields.One2many(
        'cookast.shift.plan',
        'employee_id',
        string='Turnos planificados',
    )
