from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    shift_max_weekly_hours = fields.Float(string='Max Weekly Hours', default=40.0, help='Maximum allowed working hours per week for shift planning.')
    shift_skill_ids = fields.Many2many('shift.skill', string='Planning Skills')

