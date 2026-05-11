from odoo import api, fields, models

class ShiftTemplate(models.Model):
    _name = 'shift.template'
    _description = 'Shift Template'

    name = fields.Char(string='Name', required=True, placeholder="e.g. Morning Shift (8:00 - 16:00)")
    start_time = fields.Float(string='Start Time', required=True)
    end_time = fields.Float(string='End Time', required=True)
    job_id = fields.Many2one('hr.job', string='Role/Job Position')
    project_id = fields.Many2one('project.project', string='Project')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    planned_hours = fields.Float(string='Planned Hours', compute='_compute_planned_hours', store=True)

    @api.depends('start_time', 'end_time')
    def _compute_planned_hours(self):
        for template in self:
            if template.end_time >= template.start_time:
                template.planned_hours = template.end_time - template.start_time
            else:
                # crosses midnight
                template.planned_hours = (24.0 - template.start_time) + template.end_time
