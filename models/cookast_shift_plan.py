# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


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
    staffing_need_id = fields.Many2one(
        'cookast.staffing.need',
        string='Necesidad de personal',
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
    local_id = fields.Many2one(
        related='forecast_id.local_id',
        store=True,
        string='Local',
    )

    # ── Campo nombre (no usar display_name, es reservado por el ORM) ──────────
    name = fields.Char(string='Descripción', compute='_compute_name', store=True)

    _sql_constraints = [
        ('unique_employee_shift', 'UNIQUE(forecast_id, employee_id)',
         'El empleado ya está asignado a este turno.'),
    ]

    # ── CRUD ──────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-set forecast_id from staffing_need_id when not provided."""
        for vals in vals_list:
            if not vals.get('forecast_id') and vals.get('staffing_need_id'):
                staffing = self.env['cookast.staffing.need'].browse(
                    vals['staffing_need_id']
                )
                if staffing.forecast_id:
                    vals['forecast_id'] = staffing.forecast_id.id
        return super().create(vals_list)

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

    @api.constrains('forecast_id', 'employee_id')
    def _check_unique_employee_shift(self):
        for rec in self:
            duplicate = self.search([
                ('forecast_id', '=', rec.forecast_id.id),
                ('employee_id', '=', rec.employee_id.id),
                ('id', '!=', rec.id),
            ])
            if duplicate:
                raise ValidationError(_('El empleado ya está asignado a este turno.'))

    @api.constrains('employee_id', 'date', 'shift')
    def _check_no_overlap_across_locals(self):
        """
        Impide que un empleado sea asignado a dos turnos del mismo tipo
        en el mismo día aunque sean en locales distintos.
        Previene solapamientos en empleados que trabajan en múltiples sucursales.
        """
        for rec in self:
            if not rec.date or not rec.shift:
                continue
            overlap = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '=', rec.date),
                ('shift', '=', rec.shift),
                ('id', '!=', rec.id),
            ])
            if overlap:
                other_local = overlap[0].local_id.name or _('otro local')
                raise ValidationError(_(
                    'El empleado "%s" ya tiene asignado el turno de %s del %s '
                    'en "%s". No se pueden solapar turnos aunque sean en locales distintos.'
                ) % (
                    rec.employee_id.name,
                    dict(rec._fields['shift'].selection).get(rec.shift, rec.shift),
                    rec.date,
                    other_local,
                ))

