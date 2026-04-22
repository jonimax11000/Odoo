# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CookastShiftPlan(models.Model):
    _name = 'cookast.shift.plan'
    _description = 'Planificación de turno Cookast'
    _rec_name = 'name'
    _order = 'forecast_id, employee_id'

    # ── Relaciones principales ─────────────────────────────────────────────────
    forecast_id = fields.Many2one(
        'cookast.forecast',
        string='Turno / Previsión',
        required=True,
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado',
        required=True,
        index=True,
    )

    # ── Horario planificado ────────────────────────────────────────────────────
    planned_hours = fields.Float(
        string='Horas planificadas',
        default=4.0,
        digits=(5, 2),
    )
    role = fields.Selection(
        [
            ('chef', 'Chef'),
            ('waiter', 'Camarero'),
            ('runner', 'Runner'),
            ('cashier', 'Cajero'),
        ],
        string='Rol en turno',
        required=True,
    )

    # ── Coste ─────────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        related='employee_id.company_id.currency_id',
        readonly=True,
    )
    shift_cost = fields.Monetary(
        string='Coste turno (€)',
        currency_field='currency_id',
        compute='_compute_shift_cost',
        store=True,
    )

    # ── Campos relacionados útiles para vistas ────────────────────────────────
    date = fields.Date(related='forecast_id.date', store=True, string='Fecha')
    shift = fields.Selection(
        related='forecast_id.shift',
        store=True,
        string='Turno',
    )
    location_id = fields.Many2one(
        related='forecast_id.location_id',
        store=True,
        string='Local',
    )

    # ── Campo nombre (no usar display_name, es reservado por el ORM) ──────────
    name = fields.Char(string='Descripción', compute='_compute_name', store=True)

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('employee_id', 'forecast_id')
    def _compute_name(self):
        for rec in self:
            emp = rec.employee_id.name or '—'
            forecast = rec.forecast_id.name or '—'
            rec.name = f"{emp} · {forecast}"

    @api.depends('employee_id.cookast_hourly_cost', 'planned_hours')
    def _compute_shift_cost(self):
        for rec in self:
            rec.shift_cost = rec.employee_id.cookast_hourly_cost * rec.planned_hours
