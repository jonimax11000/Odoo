# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ── Local principal ("home local") ────────────────────────────────────────
    cookast_local_id = fields.Many2one(
        'cookast.local',
        string='Local principal',
        help='Local donde trabaja habitualmente. Si se rota a otro local '
             'para un turno concreto, se refleja en el plan de turno.',
    )
    cookast_local_ids = fields.Many2many(
        'cookast.local',
        'cookast_local_employee_rel',
        'employee_id',
        'local_id',
        string='Locales asignados',
        help='Todos los locales en los que puede trabajar este empleado. '
             'El local principal se añade automáticamente.',
    )

    # ── Datos Cookast de turno y coste ────────────────────────────────────────
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

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._sync_cookast_level_skills()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if 'cookast_level' in vals:
            self._sync_cookast_level_skills()
        return res

    def _sync_cookast_level_skills(self):
        Skill = self.env['shift.skill'].sudo()
        mapping = {
            'responsible': 'Responsable',
            'senior': 'Senior',
            'junior': 'Junior',
        }
        for emp in self:
            if not emp.cookast_level:
                continue
                
            skill_name = mapping.get(emp.cookast_level)
            if not skill_name:
                continue
                
            skill = Skill.search([('name', '=', skill_name)], limit=1)
            if not skill:
                skill = Skill.create({'name': skill_name})
                
            # Keep existing skills, just add the new one
            if skill.id not in emp.shift_skill_ids.ids:
                emp.shift_skill_ids = [(4, skill.id)]
