from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import timedelta

class ShiftPlanningSlot(models.Model):
    _name = 'shift.planning.slot'
    _description = 'Shift Planning Slot'
    _order = 'start_datetime, id'

    name = fields.Char(string='Description', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=False, index=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, required=True)
    
    start_datetime = fields.Datetime(string='Start Date', required=True)
    end_datetime = fields.Datetime(string='End Date', required=True)
    
    project_id = fields.Many2one('project.project', string='Project')
    task_id = fields.Many2one('project.task', string='Task', domain="[('project_id', '=?', project_id)]")
    
    required_skill_ids = fields.Many2many('shift.skill', string='Required Skills')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('done', 'Done'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    job_id = fields.Many2one('hr.job', string='Role/Job Position')
    
    planned_hours = fields.Float(string='Planned Hours', compute='_compute_planned_hours', store=True)
    real_hours = fields.Float(string='Real Hours')
    has_conflict = fields.Boolean(string='Has Conflict', compute='_compute_has_conflict', store=True)

    @api.depends('employee_id', 'start_datetime', 'end_datetime')
    def _compute_has_conflict(self):
        for slot in self:
            if not slot.employee_id or not slot.start_datetime or not slot.end_datetime:
                slot.has_conflict = False
                continue
            
            # Overlap check
            overlap = self.search_count([
                ('employee_id', '=', slot.employee_id.id),
                ('id', '!=', slot.id),
                ('start_datetime', '<', slot.end_datetime),
                ('end_datetime', '>', slot.start_datetime),
            ])
            
            # Leave check
            leave = self.env['hr.leave'].search_count([
                ('employee_id', '=', slot.employee_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<', slot.end_datetime),
                ('date_to', '>', slot.start_datetime),
            ])
            
            slot.has_conflict = overlap > 0 or leave > 0

    @api.depends('start_datetime', 'end_datetime')
    def _compute_planned_hours(self):
        for slot in self:
            if slot.start_datetime and slot.end_datetime:
                delta = slot.end_datetime - slot.start_datetime
                slot.planned_hours = delta.total_seconds() / 3600.0
            else:
                slot.planned_hours = 0.0

    @api.constrains('start_datetime', 'end_datetime', 'employee_id')
    def _check_overlap_and_leaves(self):
        for slot in self:
            if not slot.start_datetime or not slot.end_datetime or not slot.employee_id:
                continue
            
            if slot.start_datetime >= slot.end_datetime:
                raise ValidationError(_('The start date must be earlier than the end date.'))
            
            # Check overlap with other slots
            domain = [
                ('employee_id', '=', slot.employee_id.id),
                ('id', '!=', slot.id),
                ('start_datetime', '<', slot.end_datetime),
                ('end_datetime', '>', slot.start_datetime),
            ]
            overlapping_slots = self.search(domain)
            if overlapping_slots:
                raise ValidationError(_('The shift overlaps with another shift for employee %s.') % slot.employee_id.name)
            
            # Check leaves
            leave_domain = [
                ('employee_id', '=', slot.employee_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<', slot.end_datetime),
                ('date_to', '>', slot.start_datetime),
            ]
            leaves = self.env['hr.leave'].search(leave_domain)
            if leaves:
                raise ValidationError(_('The employee %s is on leave during this period.') % slot.employee_id.name)

    @api.constrains('start_datetime', 'end_datetime', 'employee_id')
    def _check_max_weekly_hours(self):
        for slot in self:
            if not slot.start_datetime or not slot.end_datetime or not slot.employee_id:
                continue
            # calculate start of week (Monday)
            start_of_week = slot.start_datetime - timedelta(days=slot.start_datetime.weekday())
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_week = start_of_week + timedelta(days=7)
            
            domain = [
                ('employee_id', '=', slot.employee_id.id),
                ('start_datetime', '>=', start_of_week),
                ('start_datetime', '<', end_of_week),
            ]
            week_slots = self.search(domain)
            total_hours = sum(week_slots.mapped('planned_hours'))
            
            if total_hours > slot.employee_id.shift_max_weekly_hours:
                raise ValidationError(_('The employee %(emp)s exceeds the maximum weekly hours (%(max)s). Planned: %(total)s') % {
                    'emp': slot.employee_id.name,
                    'max': slot.employee_id.shift_max_weekly_hours,
                    'total': total_hours
                })
