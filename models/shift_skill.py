from odoo import fields, models

class ShiftSkill(models.Model):
    _name = 'shift.skill'
    _description = 'Shift Skill'

    name = fields.Char(string='Skill Name', required=True)
    color = fields.Integer(string='Color Index')
